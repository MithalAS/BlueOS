import os
import struct
import threading
import time
from typing import List, Optional

import serial
from commonwealth.utils.interface_board import is_interface_board
from pydantic import BaseModel
from serial.tools import list_ports

SERIAL_PORT = "auto"
BAUDRATE = 115200
TIMEOUT_S = 1.0
DEFAULT_SLAVE = 1
RETRIES = 3
RETRY_DELAY = 0.2
CHANNEL_NAMES = ["CAM1", "CAM2", "CAM3", "PLC", "GNSS"]
NUM_CHANNELS = len(CHANNEL_NAMES)

FC_READ_COILS = 0x01
FC_READ_INPUT_REGISTERS = 0x04
FC_READ_HOLDING_REGISTERS = 0x03
FC_WRITE_COIL = 0x05
FC_WRITE_REGISTER = 0x06

COIL_RESET_FAULT_BASE = 5
COIL_RESET_ALL = 10
COIL_REBOOT = 11
COIL_REBOOT_DFU = 12
SNAPSHOT_REGISTERS = 14


class ModbusError(Exception):
    """Communication failure or Modbus exception response."""


class ModbusTimeout(ModbusError):
    pass


class DeviceNotFound(ModbusError):
    pass


class StateMismatch(Exception):
    def __init__(self, status: "BoardStatus") -> None:
        self.status = status
        super().__init__("The observed channel state does not match the requested state")


class Fuse(BaseModel):
    channel: int
    name: str
    enabled: bool
    fault: bool
    current_ma: int
    fault_count: int


class BoardStatus(BaseModel):
    fuses: List[Fuse]
    firmware_version: str
    slave_address: int


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(slave: int, function: int, payload: bytes) -> bytes:
    body = bytes([slave, function]) + payload
    return body + struct.pack("<H", crc16(body))


def parse_status(registers: List[int]) -> BoardStatus:
    if len(registers) < SNAPSHOT_REGISTERS:
        raise ModbusError(f"Expected {SNAPSHOT_REGISTERS} registers, got {len(registers)}")
    enable_bitmap, fault_bitmap = registers[10], registers[11]
    fuses = [
        Fuse(
            channel=i + 1,
            name=CHANNEL_NAMES[i],
            enabled=bool(enable_bitmap >> i & 1),
            fault=bool(fault_bitmap >> i & 1),
            current_ma=registers[i],
            fault_count=registers[5 + i],
        )
        for i in range(NUM_CHANNELS)
    ]
    version = registers[12]
    return BoardStatus(fuses=fuses, firmware_version=f"{version >> 8}.{version & 0xFF}", slave_address=registers[13])


class FuseBoard:
    def __init__(self, port: str = SERIAL_PORT, slave: int = DEFAULT_SLAVE, baud: int = BAUDRATE) -> None:
        if not 1 <= slave <= 247:
            raise ValueError("Slave address must be between 1 and 247")
        self.port = port
        self.slave = slave
        self.baud = baud
        self._lock = threading.RLock()
        self._serial: Optional[serial.Serial] = None

    def _connect(self) -> None:
        if self._serial is not None:
            return
        port = self.port
        if port == "auto":
            matches = [
                candidate.device
                for candidate in list_ports.comports()
                if candidate.device.startswith("/dev/ttyACM") and is_interface_board(candidate)
            ]
            if not matches:
                raise DeviceNotFound("Interface board not found")
            if len(matches) != 1:
                raise DeviceNotFound("Multiple interface boards found; configure a serial port")
            port = matches[0]
        try:
            self._serial = serial.Serial(port, self.baud, timeout=TIMEOUT_S, write_timeout=TIMEOUT_S, exclusive=True)
        except (serial.SerialException, OSError, ValueError) as e:
            raise DeviceNotFound(f"Cannot open interface board: {e}") from e

    def _close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def close(self) -> None:
        with self._lock:
            self._close()

    def _read_exact(self, ser: serial.Serial, size: int, deadline: float) -> bytes:
        data = b""
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ser.timeout = remaining
            data += ser.read(size - len(data))
        if len(data) < size:
            raise ModbusTimeout("Timed out waiting for response from board")
        return data

    def _transact_once(self, function: int, payload: bytes, expect_data: bool) -> bytes:
        """Returns the response bytes after the function code (without CRC)."""
        request = build_frame(self.slave, function, payload)
        self._connect()
        assert self._serial is not None
        ser = self._serial
        try:
            ser.reset_input_buffer()
            if ser.write(request) != len(request):
                raise ModbusError("Incomplete Modbus request")
            deadline = time.monotonic() + TIMEOUT_S
            head = self._read_exact(ser, 3, deadline)
            if head[1] & 0x80:
                frame = head + self._read_exact(ser, 2, deadline)
            elif expect_data:
                frame = head + self._read_exact(ser, head[2] + 2, deadline)
            else:
                frame = head + self._read_exact(ser, 5, deadline)
        except (serial.SerialException, OSError) as e:
            raise ModbusError(f"Serial communication failed: {e}") from e
        if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
            raise ModbusError("CRC mismatch in response")
        if frame[0] != self.slave:
            raise ModbusError("Unexpected response header")
        if frame[1] == function | 0x80:
            raise ModbusError(f"Modbus exception code {head[2]} for function {function:#04x}")
        if frame[1] != function:
            raise ModbusError("Unexpected response header")
        if expect_data and function == FC_READ_INPUT_REGISTERS and frame[2] != struct.unpack(">H", payload[2:])[0] * 2:
            raise ModbusError("Unexpected response length")
        if not expect_data and frame[2:-2] != payload:
            raise ModbusError("Unexpected Modbus write response")
        return frame[2:-2]

    def _transact(self, function: int, payload: bytes, expect_data: bool, retry: bool = True) -> bytes:
        with self._lock:
            attempts = RETRIES if retry else 1
            for attempt in range(attempts):
                try:
                    return self._transact_once(function, payload, expect_data)
                except ModbusError:
                    if attempt == attempts - 1:
                        self._close()
                        raise
                    time.sleep(RETRY_DELAY)
            raise AssertionError("unreachable")

    def read_input_registers(self, start: int, count: int) -> List[int]:
        data = self._transact(FC_READ_INPUT_REGISTERS, struct.pack(">HH", start, count), True)
        if data[0] != count * 2:
            raise ModbusError("Unexpected response length")
        return list(struct.unpack(f">{count}H", data[1:]))

    def write_coil(self, address: int, value: bool = True, retry: bool = True) -> None:
        self._transact(FC_WRITE_COIL, struct.pack(">HH", address, 0xFF00 if value else 0), False, retry)

    def write_register(self, address: int, value: int) -> None:
        self._transact(FC_WRITE_REGISTER, struct.pack(">HH", address, value), False, False)

    def status(self) -> BoardStatus:
        return parse_status(self.read_input_registers(0, SNAPSHOT_REGISTERS))

    def fuse(self, channel: int) -> Fuse:
        index = self._index(channel)
        return self.status().fuses[index]

    @staticmethod
    def _index(channel: int) -> int:
        if not 1 <= channel <= NUM_CHANNELS:
            raise ValueError(f"Channel must be between 1 and {NUM_CHANNELS}")
        return channel - 1

    def set_enabled(self, channel: int, enabled: bool) -> Fuse:
        index = self._index(channel)
        with self._lock:
            self._connect()
            try:
                self.write_coil(index, enabled)
                for attempt in range(RETRIES):
                    status = self.status()
                    if status.fuses[index].enabled == enabled:
                        return status.fuses[index]
                    if attempt < RETRIES - 1:
                        time.sleep(RETRY_DELAY)
            except ModbusError as e:
                raise type(e)(f"{e}; channel state may be unknown after the write") from e
            raise StateMismatch(status)

    def reset_fault(self, channel: int) -> None:
        self.write_coil(COIL_RESET_FAULT_BASE + self._index(channel), retry=False)

    def reset_all(self) -> None:
        self.write_coil(COIL_RESET_ALL, retry=False)

    def reboot(self) -> None:
        self.write_coil(COIL_REBOOT, retry=False)

    def reboot_dfu(self) -> None:
        self.write_coil(COIL_REBOOT_DFU, retry=False)

    def set_slave_address(self, address: int) -> None:
        if not 1 <= address <= 247:
            raise ValueError("Slave address must be between 1 and 247")
        with self._lock:
            self.write_register(0, address)
            self.slave = address


def board_from_environment() -> FuseBoard:
    return FuseBoard(
        port=os.environ.get("INTERFACE_BOARD_PORT", SERIAL_PORT),
        baud=int(os.environ.get("INTERFACE_BOARD_BAUD", str(BAUDRATE))),
        slave=int(os.environ.get("INTERFACE_BOARD_SLAVE", str(DEFAULT_SLAVE))),
    )
