from typing import Any


def is_interface_board(port: Any) -> bool:
    manufacturer = (getattr(port, "manufacturer", None) or "").strip().casefold()
    product = (getattr(port, "product", None) or "").strip().casefold()
    vendor_id = getattr(port, "vid", None)
    product_id = getattr(port, "pid", None)
    return (
        manufacturer == "remora robotics"
        and product == "pod interface board"
        and vendor_id in (None, 0x0483)
        and product_id in (None, 0x5740)
    )
