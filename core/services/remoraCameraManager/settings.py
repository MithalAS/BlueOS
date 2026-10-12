from typing import Any, Dict

from commonwealth.settings import settings
from pykson import (
    BooleanField,
    IntegerField,
    JsonObject,
    ObjectField,
    Pykson,
    StringField,
)

pyk = Pykson()


# ---------- Typed schema -----------------------------------------------------
class CameraSideConfig(JsonObject):
    usb_hub_port = IntegerField()
    device = StringField()
    resolution = StringField()
    fps = IntegerField()
    name = StringField()
    kbitrate = IntegerField()
    preset = StringField()


class CameraConfig(JsonObject):
    port = IntegerField()
    ip = StringField()
    use_hw_enc = BooleanField()
    usb_hub = StringField()
    front = ObjectField(CameraSideConfig)
    back = ObjectField(CameraSideConfig)


# ---------- Settings container (single version) ------------------------------
class SettingsV1(settings.BaseSettings):
    """
    - Persists to a JSON file via BaseSettings.
    - Seeds file with `default_config` on first run.
    - Future: bump VERSION and extend `migrate` to add new defaults without
      overwriting user values.
    """

    VERSION = 1
    camera = ObjectField(CameraConfig)

    def __init__(self, *args: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.VERSION = SettingsV1.VERSION

    def migrate(self, data: Dict[str, Any]) -> None:
        stored_version = data.get("VERSION", 0)
        if stored_version == SettingsV1.VERSION:
            return
        if stored_version < SettingsV1.VERSION:
            super().migrate(data)
        data["VERSION"] = SettingsV1.VERSION
