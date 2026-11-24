import struct
from unittest.mock import patch

import pytest

from fuseboard import FuseBoard, ModbusError, build_frame, crc16, parse_status


def test_crc_known_vector() -> None:
    assert crc16(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])) == 0xCDC5


def test_build_frame_appends_crc() -> None:
    frame = build_frame(1, 4, struct.pack(">HH", 0, 14))
    assert frame[:6] == bytes([1, 4, 0, 0, 0, 14])
    assert crc16(frame) == 0


def test_parse_status() -> None:
    regs = [100, 200, 0, 0, 5, 0, 1, 0, 0, 2, 0b00101, 0b00100, 0x0104, 1]
    status = parse_status(regs)
    assert status.firmware_version == "1.4"
    assert [f.enabled for f in status.fuses] == [True, False, True, False, False]
    assert status.fuses[2].fault and not status.fuses[0].fault
    assert status.fuses[1].current_ma == 200
    assert status.fuses[4].fault_count == 2


def test_invalid_channel() -> None:
    with pytest.raises(ValueError):
        FuseBoard().reset_fault(6)
    with pytest.raises(ValueError):
        FuseBoard().set_slave_address(0)


def test_status_via_transact() -> None:
    regs = [0] * 14
    data = bytes([28]) + struct.pack(">14H", *regs)
    board = FuseBoard()
    with patch.object(board, "_transact", return_value=data):
        assert board.status().slave_address == 0
    with patch.object(board, "_transact", return_value=bytes([2, 0, 0])), pytest.raises(ModbusError):
        board.status()
