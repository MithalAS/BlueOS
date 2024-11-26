from typing import List, Type

from smbus2 import SMBus

from typedefs import FlightController, PlatformType, Serial


class LinuxFlightController(FlightController):
    """Linux-based Flight-controller board."""

    @property
    def type(self) -> PlatformType:
        return PlatformType.Linux

    def detect(self) -> bool:
        raise NotImplementedError

    def get_serials(self) -> List[Serial]:
        raise NotImplementedError

    def check_for_i2c_device(self, bus_number: int, address: int) -> bool:
        try:
            print(f"Trying to read from bus {bus_number}, address {address}")
            bus = SMBus(bus_number)
            bus.read_byte_data(address, 0)
            print(f"Successfully read from bus {bus_number}, address {address}")
            return True
        except OSError as e:
            print(f"Failed to read from bus {bus_number}, address {address}: {e}")
            return False

    @classmethod
    def get_all_boards(cls) -> List[Type["LinuxFlightController"]]:
        all_subclasses = []

        for subclass in cls.__subclasses__():
            all_subclasses.append(subclass)
            all_subclasses.extend(subclass.get_all_boards())

        return all_subclasses
