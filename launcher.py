"""PyInstaller's top-level entrypoint; keeps package-relative imports correct."""
from task_runner.__main__ import main
if __name__ == "__main__":
    raise SystemExit(main())
