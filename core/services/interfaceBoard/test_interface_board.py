import asyncio
import importlib.util
import json
import os
import pty
import select
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import serial
from serial.tools import list_ports

SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

import board

spec = importlib.util.spec_from_file_location("interface_board_main", SERVICE_DIR / "main.py")
assert spec is not None and spec.loader is not None
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class FakeSerial:
    firmware = 0x0203
    timeout = 0.6

    def __init__(self) -> None:
        self.enabled = 0
        self.fault = 0
        self.currents = [123, 234, 345, 456, 567]
        self.response = b""
        self.requests: list[bytes] = []
        self.behavior = SimpleNamespace(drop_writes=0, drop_reads=0, corrupt_crc=False, apply_writes=True)
        self.closed = False

    def reset_input_buffer(self) -> None:
        self.response = b""

    def write(self, request: bytes) -> int:
        assert board.crc16(request[:-2]) == int.from_bytes(request[-2:], "little")
        self.requests.append(request)
        if request[1] == 4:
            if self.behavior.drop_reads:
                self.behavior.drop_reads -= 1
                return len(request)
            registers = self.currents + [0] * 5 + [self.enabled, self.fault, self.firmware, 0]
            body = bytes((request[0], 4, 28)) + b"".join(value.to_bytes(2, "big") for value in registers)
        else:
            index = request[3]
            if self.behavior.apply_writes:
                if request[4:6] == b"\xff\x00":
                    self.enabled |= 1 << index
                else:
                    self.enabled &= ~(1 << index)
            if self.behavior.drop_writes:
                self.behavior.drop_writes -= 1
                return len(request)
            body = request[:-2]
        crc = board.crc16(body) ^ int(self.behavior.corrupt_crc)
        self.response = body + crc.to_bytes(2, "little")
        return len(request)

    def read(self, length: int) -> bytes:
        data, self.response = self.response[:length], self.response[length:]
        return data

    def close(self) -> None:
        self.closed = True


@pytest.fixture(name="serial_board")
def make_serial_board(monkeypatch: pytest.MonkeyPatch) -> tuple[board.InterfaceBoard, FakeSerial]:
    fake = FakeSerial()
    monkeypatch.setattr(serial, "Serial", lambda *args, **kwargs: fake)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return board.InterfaceBoard(port="/dev/explicit"), fake


def usb_port(device: str, **changes: Any) -> SimpleNamespace:
    values = {
        "device": device,
        "manufacturer": "Remora Robotics",
        "product": "POD Interface Board",
        "vid": 0x0483,
        "pid": 0x5740,
    }
    return SimpleNamespace(**(values | changes))


def test_snapshot_and_all_channel_writes(serial_board: tuple[board.InterfaceBoard, FakeSerial]) -> None:
    controller, fake = serial_board
    fake.fault = 1 << 3
    status = controller.snapshot()
    assert status["firmware"] == "2.3"
    assert [channel["current_ma"] for channel in status["channels"]] == fake.currents
    assert status["channels"][3]["fault"]
    assert not any(channel["enabled"] for channel in status["channels"])

    for channel in range(1, 6):
        status = controller.set_channel(channel, True)
        assert status["channels"][channel - 1]["enabled"]
    assert fake.enabled == 0x1F
    controller.set_channel(4, False)
    assert fake.enabled == 0x17
    assert any(request[:6] == bytes((1, 5, 0, 3, 0, 0)) for request in fake.requests)


def test_real_serial_transport_with_simulated_board() -> None:
    master, slave = pty.openpty()
    fake = FakeSerial()
    stop = threading.Event()

    def serve() -> None:
        pending = b""
        while not stop.is_set():
            if not select.select([master], [], [], 0.05)[0]:
                continue
            pending += os.read(master, 8 - len(pending))
            if len(pending) == 8:
                fake.write(pending)
                os.write(master, fake.response)
                pending = b""

    thread = threading.Thread(target=serve)
    thread.start()
    controller = board.InterfaceBoard(port=os.ttyname(slave))
    try:
        assert controller.snapshot()["firmware"] == "2.3"
        assert controller.set_channel(4, True)["channels"][3]["enabled"]
    finally:
        controller.close()
        stop.set()
        thread.join(timeout=2)
        os.close(master)
        os.close(slave)
    assert not thread.is_alive()


def test_discovery_only_opens_a_unique_matching_board(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSerial()
    opened: list[str] = []

    def open_serial(path: str, *_args: Any, **_kwargs: Any) -> FakeSerial:
        opened.append(path)
        return fake

    monkeypatch.setattr(serial, "Serial", open_serial)
    ports = [usb_port("/dev/ttyACM0", product="Other"), usb_port("/dev/ttyACM1")]
    monkeypatch.setattr(list_ports, "comports", lambda: ports)
    controller = board.InterfaceBoard()
    controller.snapshot()
    assert opened == ["/dev/ttyACM1"]
    controller.close()
    ports.append(usb_port("/dev/ttyACM2"))
    with pytest.raises(board.BoardError, match="Multiple"):
        controller.snapshot()
    assert opened == ["/dev/ttyACM1"]


def test_crc_failure_retries_and_closes_connection(serial_board: tuple[board.InterfaceBoard, FakeSerial]) -> None:
    controller, fake = serial_board
    fake.behavior.corrupt_crc = True
    with pytest.raises(board.BoardError, match="CRC"):
        controller.snapshot()
    assert len(fake.requests) == 3
    assert fake.closed
    fake.behavior.corrupt_crc = False
    assert controller.snapshot()["firmware"] == "2.3"


def test_response_timeout_covers_the_entire_frame(
    serial_board: tuple[board.InterfaceBoard, FakeSerial], monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, fake = serial_board
    ticks = iter((10.0, 10.4))
    monkeypatch.setattr(board, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    timeouts = []
    read = fake.read

    def timed_read(length: int) -> bytes:
        timeouts.append(fake.timeout)
        return read(length)

    monkeypatch.setattr(fake, "read", timed_read)
    controller.snapshot()
    assert timeouts == pytest.approx([0.6, 0.2])


def test_write_timeout_reports_unknown_even_if_board_applied_it(
    serial_board: tuple[board.InterfaceBoard, FakeSerial],
) -> None:
    controller, fake = serial_board
    fake.behavior.drop_writes = 3
    with pytest.raises(board.BoardError, match="state may be unknown"):
        controller.set_channel(4, True)
    assert fake.enabled & 8
    assert controller.snapshot()["channels"][3]["enabled"]


def test_status_read_failure_after_write_reports_unknown(
    serial_board: tuple[board.InterfaceBoard, FakeSerial],
) -> None:
    controller, fake = serial_board
    fake.behavior.drop_reads = 3
    with pytest.raises(board.BoardError, match="state may be unknown"):
        controller.set_channel(1, True)
    assert fake.enabled == 1


def test_write_status_mismatch_reports_last_snapshot(serial_board: tuple[board.InterfaceBoard, FakeSerial]) -> None:
    controller, fake = serial_board
    fake.behavior.apply_writes = False
    with pytest.raises(board.StateMismatch) as error:
        controller.set_channel(5, True)
    assert not error.value.status["channels"][4]["enabled"]
    assert [request[1] for request in fake.requests] == [5, 4, 4, 4]


def api_request(method: str, path: str, body: Any = None) -> tuple[int, Any]:
    async def run() -> tuple[int, Any]:
        sent = []
        payload = json.dumps(body).encode() if body is not None else b""
        received = False

        async def receive() -> dict[str, Any]:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await api.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [(b"content-type", b"application/json")],
                "client": ("127.0.0.1", 12345),
                "server": ("test", 80),
            },
            receive,
            send,
        )
        data = b"".join(m.get("body", b"") for m in sent[1:])
        if b"application/json" in dict(sent[0]["headers"]).get(b"content-type", b""):
            return sent[0]["status"], json.loads(data)
        return sent[0]["status"], data.decode()

    return asyncio.run(run())


def test_api_validation_status_and_uncertain_write(serial_board: tuple[board.InterfaceBoard, FakeSerial]) -> None:
    controller, fake = serial_board
    with patch.object(api, "board", controller):
        status, result = api_request("GET", "/v1.0/board")
        assert status == 200 and result["channels"][0]["number"] == 1
        assert api_request("PUT", "/v1.0/channels/6", {"enabled": True})[0] == 422
        assert api_request("PUT", "/v1.0/channels/1", {"enabled": "true"})[0] == 422
        assert api_request("PUT", "/v1.0/channels/4", {"enabled": True})[1]["channels"][3]["enabled"]
        fake.behavior.drop_writes = 3
        status, result = api_request("PUT", "/v1.0/channels/4", {"enabled": False})
        assert status == 503 and "state may be unknown" in result["detail"]
        fake.behavior.apply_writes = False
        status, result = api_request("PUT", "/v1.0/channels/5", {"enabled": True})
        assert status == 409 and not result["detail"]["status"]["channels"][4]["enabled"]


def test_api_docs_work_with_direct_and_proxied_paths() -> None:
    status, html = api_request("GET", "/api-docs")
    assert status == 200 and "url: 'v1.0/openapi.json'" in html
    status, schema = api_request("GET", "/v1.0/openapi.json")
    assert status == 200 and schema["servers"] == [{"url": "."}]


def test_unavailable_board_returns_503_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(list_ports, "comports", lambda: [])
    controller = board.InterfaceBoard()
    with patch.object(api, "board", controller):
        assert api_request("GET", "/v1.0/board")[0] == 503
        assert api_request("PUT", "/v1.0/channels/1", {"enabled": True})[0] == 503
