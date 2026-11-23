import os
import threading
import time
from typing import Any, Dict, List, Optional

import serial
from commonwealth.utils.interface_board import is_interface_board
from serial.tools import list_ports

CHANNEL_NAMES = ("Camera Back", "Camera Mid", "Camera Front", "PLC", "GNSS")
RETRIES = 3
RETRY_DELAY = 0.2
TIMEOUT = 0.6


class BoardError(Exception):
    pass


class StateMismatch(Exception):
    def __init__(self, status: Dict[str, Any]) -> None:
        self.status = status
        super().__init__("The observed channel state does not match the requested state")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class InterfaceBoard:
    def __init__(self, port: str = "auto", baud: int = 115200, slave: int = 1) -> None:
        if not 1 <= slave <= 247:
            raise ValueError("Modbus slave address must be between 1 and 247")
        self.port = port
        self.baud = baud
        self.slave = slave
        self.serial: Optional[serial.Serial] = None
        self.lock = threading.Lock()

    def _connect(self) -> None:
        if self.serial is not None:
            return
        port = self.port
        if port == "auto":
            matches = [
                candidate.device
                for candidate in list_ports.comports()
                if candidate.device.startswith("/dev/ttyACM") and is_interface_board(candidate)
            ]
            if not matches:
                raise BoardError("Interface board not found")
            if len(matches) != 1:
                raise BoardError("Multiple interface boards found; configure a serial port")
            port = matches[0]
        try:
            self.serial = serial.Serial(port, self.baud, timeout=TIMEOUT, write_timeout=TIMEOUT, exclusive=True)
        except (serial.SerialException, OSError, ValueError) as error:
            raise BoardError(f"Cannot open interface board: {error}") from error

    def _close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def close(self) -> None:
        with self.lock:
            self._close()

    def _transact_once(self, request: bytes, expected: int) -> bytes:
        assert self.serial is not None
        checksum = crc16(request)
        packet = request + checksum.to_bytes(2, "little")
        try:
            self.serial.reset_input_buffer()
            if self.serial.write(packet) != len(packet):
                raise BoardError("Incomplete Modbus request")
            deadline = time.monotonic() + TIMEOUT
            self.serial.timeout = TIMEOUT
            response = bytes(self.serial.read(3))
            if len(response) != 3:
                raise BoardError("Incomplete Modbus response")
            length = 5 if response[1] & 0x80 else expected
            self.serial.timeout = max(0.0, deadline - time.monotonic())
            response += bytes(self.serial.read(length - 3))
        except (serial.SerialException, OSError) as error:
            raise BoardError(f"Serial communication failed: {error}") from error
        if len(response) != length:
            raise BoardError("Incomplete Modbus response")
        if crc16(response[:-2]) != int.from_bytes(response[-2:], "little"):
            raise BoardError("Modbus CRC mismatch")
        if response[0] != self.slave:
            raise BoardError("Unexpected Modbus slave address")
        if response[1] == (request[1] | 0x80):
            raise BoardError(f"Modbus exception {response[2]}")
        if response[1] != request[1]:
            raise BoardError("Unexpected Modbus function")
        if request[1] == 4 and response[2] != 28:
            raise BoardError("Unexpected Modbus register count")
        if request[1] == 5 and response[:-2] != request:
            raise BoardError("Unexpected Modbus write response")
        return response

    def _transact(self, request: bytes, expected: int) -> bytes:
        for attempt in range(RETRIES):
            try:
                return self._transact_once(request, expected)
            except BoardError:
                if attempt == RETRIES - 1:
                    self._close()
                    raise
                time.sleep(RETRY_DELAY)
        raise AssertionError("unreachable")

    def _snapshot(self) -> Dict[str, Any]:
        response = self._transact(bytes((self.slave, 4, 0, 0, 0, 14)), 33)
        registers = [int.from_bytes(response[3 + i * 2 : 5 + i * 2], "big") for i in range(14)]
        enabled, fault, firmware = registers[10], registers[11], registers[12]
        channels: List[Dict[str, Any]] = [
            {
                "number": index + 1,
                "name": name,
                "enabled": bool(enabled & (1 << index)),
                "fault": bool(fault & (1 << index)),
                "current_ma": registers[index],
            }
            for index, name in enumerate(CHANNEL_NAMES)
        ]
        return {"firmware": f"{firmware >> 8}.{firmware & 0xFF}", "channels": channels}

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            self._connect()
            return self._snapshot()

    def set_channel(self, channel: int, enabled: bool) -> Dict[str, Any]:
        if not 1 <= channel <= len(CHANNEL_NAMES):
            raise ValueError("Invalid channel number")
        with self.lock:
            self._connect()
            value = 0xFF00 if enabled else 0
            request = bytes((self.slave, 5, 0, channel - 1, value >> 8, value & 0xFF))
            try:
                self._transact(request, 8)
                for attempt in range(RETRIES):
                    status = self._snapshot()
                    if status["channels"][channel - 1]["enabled"] == enabled:
                        return status
                    if attempt < RETRIES - 1:
                        time.sleep(RETRY_DELAY)
            except BoardError as error:
                raise BoardError(f"{error}; channel state may be unknown after the write") from error
            raise StateMismatch(status)


def board_from_environment() -> InterfaceBoard:
    return InterfaceBoard(
        port=os.environ.get("INTERFACE_BOARD_PORT", "auto"),
        baud=int(os.environ.get("INTERFACE_BOARD_BAUD", "115200")),
        slave=int(os.environ.get("INTERFACE_BOARD_SLAVE", "1")),
    )
