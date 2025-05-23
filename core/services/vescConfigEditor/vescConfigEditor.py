import struct
import time
from pathlib import Path
from typing import Any, List, Optional

import requests
import serial

USERDATA: Path = Path("/usr/blueos/userdata/")
COMM_GET_APPCONF: int = 17
COMM_SET_APPCONF: int = 16


class vescConfigEditor:
    """Manager for config changes on vesc motor controllers."""

    def crc16(self, data: bytes) -> int:
        crc: int = 0
        for b in data:
            crc = ((crc >> 8) | (crc << 8)) & 0xFFFF
            crc ^= b
            crc ^= (crc & 0xFF) >> 4
            crc ^= (crc << 12) & 0xFFFF
            crc ^= ((crc & 0xFF) << 5) & 0xFFFF
        return crc & 0xFFFF

    def encode_packet(self, payload: bytes) -> bytes:
        payload_len: int = len(payload)
        if payload_len <= 255:
            header: bytes = bytes([2, payload_len])
        else:
            header = bytes([3, (payload_len >> 8) & 0xFF, payload_len & 0xFF])
        crc: bytes = struct.pack(">H", self.crc16(payload))
        return header + payload + crc + bytes([3])

    def get_appconf(self, ser: serial.Serial) -> Optional[bytearray]:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        payload: bytes = bytes([COMM_GET_APPCONF])
        packet: bytes = self.encode_packet(payload)
        print(f"Sending packet: {packet.hex()}")
        ser.write(packet)
        time.sleep(0.2)
        response: bytearray = bytearray()
        start_time: float = time.time()
        while time.time() - start_time < 2.0:
            if ser.in_waiting:
                response += ser.read(ser.in_waiting)
            if response and response[-1] == 3:
                break
            time.sleep(0.01)
        return response if response else None

    def set_appconf(self, ser: serial.Serial, payload: bytes) -> None:
        payload = bytes([COMM_SET_APPCONF]) + payload
        packet: bytes = self.encode_packet(payload)
        print(f"Sending packet: {packet.hex()}")
        ser.write(packet)
        time.sleep(0.2)

    def extract_payload_from_response(self, response: bytes) -> bytes:
        i: int = 0
        while i < len(response) - 6:
            if response[i] == 0x03:
                if i + 3 >= len(response):
                    break
                high: int = response[i + 1]
                low: int = response[i + 2]
                length: int = (high << 8) | low
                end_index: int = i + 3 + length + 2 + 1
                if end_index > len(response):
                    break
                if response[end_index - 1] != 0x03:
                    i += 1
                    continue
                payload: bytes = response[i + 3 : i + 3 + length]
                crc_received: bytes = response[i + 3 + length : i + 3 + length + 2]
                crc_expected: bytes = struct.pack(">H", self.crc16(payload))
                if crc_received != crc_expected:
                    i += 1
                    continue
                return payload
            i += 1
        raise ValueError("Valid extended VESC packet not found.")

    def change_timeout(self, port: str, new_timeout_sec: int) -> None:
        timeout: int = new_timeout_sec * 1000
        try:
            ser: serial.Serial = serial.Serial(port, baudrate=115200, timeout=0.3)
            response: Optional[bytearray] = self.get_appconf(ser)
            if response:
                payload: bytes = self.extract_payload_from_response(response)
                if payload[0] == COMM_GET_APPCONF:
                    payload = payload[1:]

                payload = bytearray(payload)
                payload[5:9] = struct.pack(">I", timeout)
                self.set_appconf(ser, bytes(payload))
            else:
                print("No response received.")
            ser.close()
        except serial.SerialException as e:
            print(f"Error: {e}")

    def available_serial_ports(self) -> List[str]:
        try:
            response: requests.Response = requests.get("http://localhost:6030/serial", timeout=1)
            data: Any = response.json()
            return [port["name"] for port in data["ports"] if port["name"] is not None]
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            return []
