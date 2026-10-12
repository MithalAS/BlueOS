from flight_controller_detector.linux.navigator import NavigatorPi4
from typedefs import Platform


class Argonot(NavigatorPi4):
    name = "Argonot"
    manufacturer = "SymbyTech"
    platform = Platform.Argonot

    required_devices = {
        "swap_multiplexer": (0x77, 1),
    }

    def detect(self) -> bool:
        if self.is_pi5():
            return False
        return all(self.check_for_i2c_device(bus, address) for address, bus in self.required_devices.values())
