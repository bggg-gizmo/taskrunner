"""Persistent files and frozen application resources."""
import os
import sys
from pathlib import Path


def data_root() -> Path:
    override = os.environ.get("TASKRUNNER_HOME")
    if override:
        path = Path(override).expanduser().resolve()
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TaskRunner"
    else:
        path = Path.home() / ".local" / "share" / "TaskRunner"
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_path(filename: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / filename


def setup_browser_path() -> None:
    if getattr(sys, "frozen", False):
        alongside = Path(sys.executable).resolve().parent / "browser-binaries"
        # A frozen build must use its shipped browsers, never silently fall back
        # to the builder machine's user cache (which masks packaging failures).
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(alongside)
