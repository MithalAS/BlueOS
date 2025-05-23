from pathlib import Path
from typing import List
import struct
import time
import serial
import requests

USERDATA = Path("/usr/blueos/userdata/")
COMM_GET_APPCONF = 17
COMM_SET_APPCONF = 16


class vescConfigEditor:
    """Manager for config changes on vesc motor controllers."""

    def crc16(self, data):
        crc = 0
        for b in data:
            crc = ((crc >> 8) | (crc << 8)) & 0xFFFF
            crc ^= b
            crc ^= (crc & 0xFF) >> 4
            crc ^= (crc << 12) & 0xFFFF
            crc ^= ((crc & 0xFF) << 5) & 0xFFFF
        return crc & 0xFFFF

    def encode_packet(self, payload):
        payload_len = len(payload)
        if payload_len <= 255:
            header = bytes([2, payload_len])
        else:
            header = bytes([3, (payload_len >> 8) & 0xFF, payload_len & 0xFF])
        crc = struct.pack(">H", self.crc16(payload))
        return header + payload + crc + bytes([3])

    def get_appconf(self, ser):
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        payload = bytes([COMM_GET_APPCONF])
        packet = self.encode_packet(payload)
        print(f"Sending packet: {packet.hex()}")
        ser.write(packet)
        time.sleep(0.2)
        response = bytearray()
        start_time = time.time()
        while time.time() - start_time < 2.0:
            if ser.in_waiting:
                response += ser.read(ser.in_waiting)
            if response and response[-1] == 3:
                break
            time.sleep(0.01)
        return response if response else None

    def set_appconf(self, ser, payload):
        payload = bytes([COMM_SET_APPCONF]) + payload
        packet = self.encode_packet(payload)
        print(f"Sending packet: {packet.hex()}")
        ser.write(packet)
        time.sleep(0.2)

    def extract_payload_from_response(self, response):
        i = 0
        while i < len(response) - 6:
            if response[i] == 0x03:
                if i + 3 >= len(response):
                    break
                high = response[i + 1]
                low = response[i + 2]
                length = (high << 8) | low
                end_index = i + 3 + length + 2 + 1
                if end_index > len(response):
                    break
                if response[end_index - 1] != 0x03:
                    i += 1
                    continue
                payload = response[i + 3 : i + 3 + length]
                crc_received = response[i + 3 + length : i + 3 + length + 2]
                crc_expected = struct.pack(">H", self.crc16(payload))
                if crc_received != crc_expected:
                    i += 1
                    continue
                return payload
            i += 1
        raise ValueError("Valid extended VESC packet not found.")

    def change_timeout(self, port, new_timeout_sec):
        timeout = new_timeout_sec * 1000
        try:
            ser = serial.Serial(port, baudrate=115200, timeout=0.3)
            response = self.get_appconf(ser)
            if response:
                payload = self.extract_payload_from_response(response)
                if payload[0] == COMM_GET_APPCONF:
                    payload = payload[1:]

                payload[5:9] = struct.pack(">I", timeout)
                self.set_appconf(ser, payload)
            else:
                print("No response received.")
            ser.close()
        except serial.SerialException as e:
            print(f"Error: {e}")

    def available_serial_ports(self) -> List[str]:
        try:
            response = requests.get("http://localhost:6030/serial", timeout=1)
            data = response.json()
            return [port["name"] for port in data["ports"] if port["name"] is not None]
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            return []
