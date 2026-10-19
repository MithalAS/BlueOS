import struct
import threading
import time
from typing import List

import serial
from pydantic import BaseModel

SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 115200
TIMEOUT_S = 1.0
DEFAULT_SLAVE = 1
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
    def __init__(self, port: str = SERIAL_PORT, slave: int = DEFAULT_SLAVE) -> None:
        self.port = port
        self.slave = slave
        self._lock = threading.Lock()

    def _read_exact(self, ser: serial.Serial, size: int) -> bytes:
        data = b""
        deadline = time.time() + TIMEOUT_S
        while len(data) < size and time.time() < deadline:
            data += ser.read(size - len(data))
        if len(data) < size:
            raise ModbusTimeout("Timed out waiting for response from board")
        return data

    def _transact(self, function: int, payload: bytes, expect_data: bool) -> bytes:
        """Returns the response bytes after the function code (without CRC)."""
        request = build_frame(self.slave, function, payload)
        try:
            with self._lock, serial.Serial(self.port, BAUDRATE, timeout=0.1, write_timeout=TIMEOUT_S) as ser:
                ser.reset_input_buffer()
                ser.write(request)
                head = self._read_exact(ser, 3)
                if head[1] & 0x80:
                    self._read_exact(ser, 2)
                    raise ModbusError(f"Modbus exception code {head[2]} for function {function:#04x}")
                if expect_data:
                    rest = self._read_exact(ser, head[2] + 2)
                    frame = head + rest
                else:
                    frame = head + self._read_exact(ser, 5)
        except serial.SerialException as e:
            raise DeviceNotFound(f"Serial port {self.port} unavailable: {e}") from e
        if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
            raise ModbusError("CRC mismatch in response")
        if frame[0] != self.slave or frame[1] != function:
            raise ModbusError("Unexpected response header")
        return frame[2:-2]

    def read_input_registers(self, start: int, count: int) -> List[int]:
        data = self._transact(FC_READ_INPUT_REGISTERS, struct.pack(">HH", start, count), True)
        if data[0] != count * 2:
            raise ModbusError("Unexpected response length")
        return list(struct.unpack(f">{count}H", data[1:]))

    def write_coil(self, address: int, value: bool = True) -> None:
        self._transact(FC_WRITE_COIL, struct.pack(">HH", address, 0xFF00 if value else 0), False)

    def write_register(self, address: int, value: int) -> None:
        self._transact(FC_WRITE_REGISTER, struct.pack(">HH", address, value), False)

    def status(self) -> BoardStatus:
        return parse_status(self.read_input_registers(0, SNAPSHOT_REGISTERS))

    def fuse(self, channel: int) -> Fuse:
        return self.status().fuses[self._index(channel)]

    @staticmethod
    def _index(channel: int) -> int:
        if not 1 <= channel <= NUM_CHANNELS:
            raise ValueError(f"Channel must be between 1 and {NUM_CHANNELS}")
        return channel - 1

    def set_enabled(self, channel: int, enabled: bool) -> Fuse:
        self.write_coil(self._index(channel), enabled)
        return self.fuse(channel)

    def reset_fault(self, channel: int) -> None:
        self.write_coil(COIL_RESET_FAULT_BASE + self._index(channel))

    def reset_all(self) -> None:
        self.write_coil(COIL_RESET_ALL)

    def reboot(self) -> None:
        self.write_coil(COIL_REBOOT)

    def reboot_dfu(self) -> None:
        self.write_coil(COIL_REBOOT_DFU)

    def set_slave_address(self, address: int) -> None:
        if not 1 <= address <= 247:
            raise ValueError("Slave address must be between 1 and 247")
        self.write_register(0, address)
        self.slave = address
