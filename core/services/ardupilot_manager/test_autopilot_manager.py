# pylint: disable=redefined-outer-name
import asyncio
from typing import List, Type, Union
from unittest.mock import AsyncMock, Mock, patch

import psutil
import pytest

from autopilot_manager import AutoPilotManager
from exceptions import AutoPilotProcessKillFail
from typedefs import Platform


@pytest.fixture
def manager() -> AutoPilotManager:
    instance = object.__new__(AutoPilotManager)
    instance.should_be_running = True
    instance._start_fail_count = 0
    instance._max_start_failures = 10
    instance._heartbeat_fail_count = 0
    instance._max_heartbeat_failures = 10
    instance.vehicle_manager = Mock(is_heart_beating=AsyncMock())
    return instance


def run_watchdog(manager: AutoPilotManager, iterations: int) -> None:
    sleep = AsyncMock(side_effect=[None] * (iterations - 1) + [asyncio.CancelledError()])
    with patch("autopilot_manager.asyncio.sleep", sleep):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(manager.auto_restart_ardupilot())
    assert sleep.await_count == iterations


@pytest.mark.parametrize(
    "heartbeats, expected_restarts, expected_failures",
    [
        ([True] * 10, 0, 0),
        ([False] * 9, 0, 9),
        ([False] * 10, 1, 0),
        ([False] * 5 + [True] + [False] * 5, 0, 5),
        ([RuntimeError("Heartbeat unavailable")] * 10, 1, 0),
    ],
)
def test_heartbeat_watchdog(
    manager: AutoPilotManager,
    heartbeats: List[Union[bool, Exception]],
    expected_restarts: int,
    expected_failures: int,
) -> None:
    manager.vehicle_manager.is_heart_beating.side_effect = heartbeats
    with patch.object(manager, "is_running", return_value=True):
        with patch.object(manager, "restart_ardupilot", new_callable=AsyncMock) as restart:
            run_watchdog(manager, len(heartbeats))
    assert restart.await_count == expected_restarts
    assert manager._heartbeat_fail_count == expected_failures


def test_disabled_watchdog_does_not_check_heartbeat(manager: AutoPilotManager) -> None:
    manager.should_be_running = False
    with patch.object(manager, "is_running", return_value=False):
        run_watchdog(manager, 2)
    manager.vehicle_manager.is_heart_beating.assert_not_awaited()


def test_watchdog_survives_process_inspection_error(manager: AutoPilotManager) -> None:
    manager.vehicle_manager.is_heart_beating.return_value = True
    with patch.object(manager, "is_running", side_effect=[RuntimeError("Inspection failed"), True, True, True]):
        run_watchdog(manager, 2)
    manager.vehicle_manager.is_heart_beating.assert_awaited_once()


def test_watchdog_survives_restart_error(manager: AutoPilotManager) -> None:
    manager.vehicle_manager.is_heart_beating.return_value = False
    with patch.object(manager, "is_running", return_value=True):
        with patch.object(manager, "restart_ardupilot", new_callable=AsyncMock) as restart:
            restart.side_effect = RuntimeError("Restart failed")
            run_watchdog(manager, 11)
    restart.assert_awaited_once()
    assert manager._heartbeat_fail_count == 1


def test_start_failures_remain_capped(manager: AutoPilotManager) -> None:
    async def fail_start() -> None:
        manager.should_be_running = True
        raise RuntimeError("Start failed")

    with patch.object(manager, "is_running", return_value=False):
        with patch.object(manager, "kill_ardupilot", new_callable=AsyncMock):
            with patch.object(manager, "start_ardupilot", new_callable=AsyncMock) as start:
                start.side_effect = fail_start
                run_watchdog(manager, 11)
    assert start.await_count == 10
    assert manager._start_fail_count == 10
    assert not manager.should_be_running
    manager.vehicle_manager.is_heart_beating.assert_not_awaited()


def test_running_autopilot_resets_start_failures(manager: AutoPilotManager) -> None:
    manager._start_fail_count = 5
    manager.vehicle_manager.is_heart_beating.return_value = True
    with patch.object(manager, "is_running", return_value=True):
        run_watchdog(manager, 1)
    assert manager._start_fail_count == 0


def test_stopped_autopilot_is_restarted(manager: AutoPilotManager) -> None:
    manager.vehicle_manager.is_heart_beating.return_value = True
    with patch.object(manager, "is_running", return_value=False) as running:

        async def start_autopilot() -> None:
            manager.should_be_running = True
            running.return_value = True

        with patch.object(manager, "kill_ardupilot", new_callable=AsyncMock) as kill:
            with patch.object(manager, "start_ardupilot", new_callable=AsyncMock) as start:
                start.side_effect = start_autopilot
                run_watchdog(manager, 1)
    kill.assert_awaited_once()
    start.assert_awaited_once()
    manager.vehicle_manager.is_heart_beating.assert_awaited_once()


@pytest.mark.parametrize("termination_fails", [False, True])
def test_kill_prunes_after_termination(manager: AutoPilotManager, termination_fails: bool) -> None:
    manager._current_board = Mock(platform=Platform.SITL)
    manager.mavlink_manager = Mock(stop=AsyncMock())
    with patch.object(manager, "terminate_ardupilot_subprocess", new_callable=AsyncMock) as terminate:
        if termination_fails:
            terminate.side_effect = AutoPilotProcessKillFail("Termination timed out")
        with patch.object(manager, "prune_ardupilot_processes", new_callable=AsyncMock) as prune:
            asyncio.run(manager.kill_ardupilot())
    terminate.assert_awaited_once()
    prune.assert_awaited_once()
    manager.mavlink_manager.stop.assert_awaited_once()
    assert not manager.should_be_running


def test_kill_propagates_pruning_failure(manager: AutoPilotManager) -> None:
    manager._current_board = Mock(platform=Platform.SITL)
    manager.mavlink_manager = Mock(stop=AsyncMock())
    with patch.object(manager, "terminate_ardupilot_subprocess", new_callable=AsyncMock) as terminate:
        terminate.side_effect = AutoPilotProcessKillFail("Termination timed out")
        with patch.object(manager, "prune_ardupilot_processes", new_callable=AsyncMock) as prune:
            prune.side_effect = AutoPilotProcessKillFail("Pruning failed")
            with pytest.raises(AutoPilotProcessKillFail, match="Pruning failed"):
                asyncio.run(manager.kill_ardupilot())
    manager.mavlink_manager.stop.assert_not_awaited()


@pytest.mark.parametrize("error_type", [psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied])
def test_process_inspection_skips_unavailable_processes(
    manager: AutoPilotManager, error_type: Type[psutil.Error]
) -> None:
    unavailable = Mock(pid=1)
    unavailable.cmdline.side_effect = error_type(1)
    autopilot = Mock(pid=2)
    autopilot.cmdline.return_value = ["/firmware/ardupilot"]
    unrelated = Mock(pid=3)
    unrelated.cmdline.return_value = ["unrelated"]
    manager.firmware_manager = Mock()
    manager.firmware_manager.firmware_path.return_value = "/firmware/ardupilot"
    with patch("autopilot_manager.psutil.process_iter", return_value=[unavailable, autopilot, unrelated]):
        assert manager.running_ardupilot_processes() == [autopilot]
    for process in (unavailable, autopilot, unrelated):
        process.cmdline.assert_called_once()
