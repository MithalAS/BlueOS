from typing import List, Tuple, Type
from unittest.mock import patch

import pytest

from flight_controller_detector.linux.argonot import Argonot
from flight_controller_detector.linux.linux_boards import LinuxFlightController
from flight_controller_detector.linux.navigator import (
    NaviCubePi4,
    NavigatorPi4,
    NavigatorPi5,
)

BOARD_DEVICES = [
    (NavigatorPi4, False, [(1, 0x48), (1, 0x76), (4, 0x40)], [(1, 0x0C), (1, 0x1E)]),
    (NavigatorPi5, True, [(1, 0x48), (1, 0x76), (3, 0x40)], [(1, 0x0C), (1, 0x1E)]),
    (NaviCubePi4, False, [(1, 0x48), (0, 0x58)], [(1, 0x1C), (1, 0x14)]),
]


@pytest.mark.parametrize(
    "board_type, is_pi5, required, magnetometers, present_mask",
    [
        (board_type, is_pi5, required, magnetometers, present_mask)
        for board_type, is_pi5, required, magnetometers in BOARD_DEVICES
        for present_mask in range(1 << (len(required) + len(magnetometers)))
    ],
)
def test_detection_device_combinations(
    board_type: Type[LinuxFlightController],
    is_pi5: bool,
    required: List[Tuple[int, int]],
    magnetometers: List[Tuple[int, int]],
    present_mask: int,
) -> None:
    present = {device for index, device in enumerate(required + magnetometers) if present_mask & (1 << index)}
    with patch("flight_controller_detector.linux.navigator.platform.machine", return_value="armv7l"):
        board = board_type()
    with patch.object(board_type, "is_pi5", return_value=is_pi5):
        with patch.object(
            board_type, "check_for_i2c_device", side_effect=lambda bus, address: (bus, address) in present
        ) as check:
            assert board.detect() == (
                all(device in present for device in required) and any(device in present for device in magnetometers)
            )
    assert all(call.args in required + magnetometers for call in check.call_args_list)


@pytest.mark.parametrize("board_type, is_pi5", [(board_type, is_pi5) for board_type, is_pi5, _, _ in BOARD_DEVICES])
def test_detection_rejects_wrong_pi(
    board_type: Type[LinuxFlightController],
    is_pi5: bool,
) -> None:
    with patch("flight_controller_detector.linux.navigator.platform.machine", return_value="armv7l"):
        board = board_type()
    with patch.object(board_type, "is_pi5", return_value=not is_pi5):
        with patch.object(board_type, "check_for_i2c_device", return_value=True) as check:
            assert not board.detect()
    check.assert_not_called()


@pytest.mark.parametrize("is_pi5, multiplexer_present", [(False, False), (False, True), (True, True)])
def test_argonot_detection(is_pi5: bool, multiplexer_present: bool) -> None:
    with patch("flight_controller_detector.linux.navigator.platform.machine", return_value="armv7l"):
        board = Argonot()
    with patch.object(Argonot, "is_pi5", return_value=is_pi5):
        with patch.object(Argonot, "check_for_i2c_device", return_value=multiplexer_present) as check:
            assert board.detect() == (not is_pi5 and multiplexer_present)
    if is_pi5:
        check.assert_not_called()
    else:
        check.assert_called_once_with(1, 0x77)


@pytest.mark.parametrize(
    "board_type, release, expected",
    [
        (NavigatorPi5, "bookworm", ["/dev/ttyAMA0", "/dev/ttyAMA2", "/dev/ttyAMA3", "/dev/ttyAMA4"]),
        (NavigatorPi4, "bullseye", ["/dev/ttyS0", "/dev/ttyAMA1", "/dev/ttyAMA2", "/dev/ttyAMA3"]),
        (NavigatorPi4, "bookworm", ["/dev/ttyS0", "/dev/ttyAMA3", "/dev/ttyAMA4", "/dev/ttyAMA5"]),
        (NaviCubePi4, "bullseye", ["/dev/ttyAMA0", "/dev/ttyAMA1", "/dev/ttyAMA2", "/dev/ttyAMA3"]),
        (NaviCubePi4, "bookworm", ["/dev/ttyAMA0", "/dev/ttyAMA3", "/dev/ttyAMA4", "/dev/ttyAMA5"]),
    ],
)
def test_serial_mappings(board_type: Type[LinuxFlightController], release: str, expected: List[str]) -> None:
    with patch("flight_controller_detector.linux.navigator.platform.machine", return_value="armv7l"):
        board = board_type()
    with patch("flight_controller_detector.linux.navigator.load_file", return_value=release):
        with patch("pathlib.Path.exists", return_value=True):
            serials = board.get_serials()
    assert [serial.port for serial in serials] == ["C", "B", "E", "F"]
    assert [serial.endpoint for serial in serials] == expected
