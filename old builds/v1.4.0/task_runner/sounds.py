"""Original short retro sound effects, independently disabled in settings."""
import json
import sys
from .paths import data_root, asset_path

DEFAULTS = {"sounds": True, "confirm_shutdown": True, "save_failure_screenshots": True, "minimize_during_manual_runs": True}

class Preferences:
    def __init__(self):
        self.path = data_root() / "settings.json"
        try:
            self.values = {**DEFAULTS, **json.loads(self.path.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            self.values = dict(DEFAULTS)

    def get(self, name):
        return self.values.get(name, DEFAULTS.get(name))

    def set(self, name, value):
        self.values[name] = value
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.values,indent=2),encoding="utf-8")
        temp.replace(self.path)

    def play(self, event: str, blocking: bool = False):
        if not self.get("sounds") or sys.platform != "win32":
            return
        try:
            import winsound
            flags=winsound.SND_FILENAME | winsound.SND_NODEFAULT
            if not blocking:flags|=winsound.SND_ASYNC
            winsound.PlaySound(str(asset_path(f"{event}.wav")),flags)
        except (OSError,RuntimeError):
            pass
