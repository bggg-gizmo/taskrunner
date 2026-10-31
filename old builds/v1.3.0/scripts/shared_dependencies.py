"""Install only unsatisfied Python requirements in the *shared* Windows user site.

No venv, no --target folder, no local dependency duplication. All installations
are tied to the selected normal Windows Python interpreter and visible to other
projects using the same Python major/minor version and Windows account.
"""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import site
import subprocess
import sys
import sysconfig


def check_interpreter() -> None:
    if sys.platform == "win32":
        if not ((3, 11) <= sys.version_info[:2] <= (3, 13)):
            raise RuntimeError("Requires Python 3.11, 3.12, or 3.13.")
        if sys.maxsize <= 2**32:
            raise RuntimeError("Use 64-bit Python.")
    if sys.prefix != sys.base_prefix:
        raise RuntimeError("Virtual environment detected; use an ordinary Python installation.")
    if site.ENABLE_USER_SITE is not True:
        raise RuntimeError(
            "Python user site-packages are disabled. Enable them or use an ordinary "
            "Python installation; Task Runner will not install into a venv."
        )


def ensure_pip() -> None:
    probe = subprocess.run([sys.executable, "-m", "pip", "--version"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if probe.returncode == 0:
        return
    print("pip missing; bootstrapping pip into this Windows user's Python site...", flush=True)
    subprocess.run([sys.executable, "-m", "ensurepip", "--user"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "--version"], check=True)


def load_requirements(file: Path):
    # pip ships packaging; the bootstrap uses no third-party imports beyond pip.
    from pip._vendor.packaging.requirements import Requirement

    parsed = []
    visited = set()

    def visit(path: Path):
        path = path.resolve()
        if path in visited:
            return
        visited.add(path)
        if not path.is_file():
            raise FileNotFoundError(f"Requirements file does not exist: {path}")
        for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.partition(" #")[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r ") or line.startswith("--requirement "):
                visit(path.parent / line.split(maxsplit=1)[1].strip())
                continue
            try:
                requirement = Requirement(line)
            except Exception as exc:
                raise ValueError(f"Unrecognized requirement at {path}:{lineno}: {line}") from exc
            if not requirement.url and (requirement.marker is None or requirement.marker.evaluate()):
                parsed.append(requirement)
            elif requirement.url:
                raise ValueError(f"Direct URL requirements are unsupported by this preflight: {line}")

    visit(file)
    return parsed


def unsatisfied(requirements) -> list[str]:
    problems = []
    for requirement in requirements:
        try:
            version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            problems.append(f"{requirement.name}: not installed")
            continue
        if not requirement.specifier.contains(version, prereleases=True):
            problems.append(f"{requirement.name}: installed {version}, requires {requirement.specifier}")
    return problems


def add_scripts_to_user_path() -> None:
    """Expose shared user-site CLI entrypoints to future Windows terminals.

    Update HKCU only; never call setx (which can truncate long PATH values).
    """
    if sys.platform != "win32":
        return
    import ctypes
    import winreg

    scripts = Path(sysconfig.get_path("scripts", scheme="nt_user")).resolve()
    scripts.mkdir(parents=True, exist_ok=True)

    def norm(component: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.expandvars(component.strip().strip('"'))))

    current_paths = [norm(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if norm(str(scripts)) in current_paths:
        print(f"Shared Python Scripts already on PATH: {scripts}")
        return

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            previous, kind = winreg.QueryValueEx(key, "Path")
            if not isinstance(previous, str):
                raise RuntimeError("Existing Windows user PATH is not a string; leaving it unchanged.")
        except FileNotFoundError:
            previous, kind = "", winreg.REG_EXPAND_SZ
        if norm(str(scripts)) in [norm(p) for p in previous.split(";") if p]:
            print(f"Shared Python Scripts already in user PATH: {scripts}")
            return
        updated = (previous.rstrip(";") + ";" if previous.strip() else "") + str(scripts)
        new_kind = winreg.REG_EXPAND_SZ if "%" in updated else kind
        if new_kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            new_kind = winreg.REG_EXPAND_SZ
        winreg.SetValueEx(key, "Path", 0, new_kind, updated)

    # Existing shells keep their process PATH; newly opened shells inherit the update.
    result = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment",
                                            0x0002, 5000, ctypes.byref(result))
    print(f"Added shared Python Scripts to user PATH: {scripts}")
    print("Open a new Command Prompt to use its command-line tools by name.")


def install_shared_requirements(path: Path) -> None:
    """Recover gracefully from pip cache ACL/lock failures on Windows.

    Initial run retains pip's cache for speed. A permission failure from pip
    retries with the cache disabled, retaining --user/site-packages and the
    user's selected interpreter. We never delete or chmod a shared pip cache.
    """
    command = [sys.executable, "-m", "pip", "install", "--user",
               "--disable-pip-version-check", "-r", str(path.resolve())]
    first = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    if first.stdout:
        print(first.stdout, end="" if first.stdout.endswith("\n") else "\n", flush=True)
    if first.returncode == 0:
        return
    output = (first.stdout or "").lower()
    cache_failure = ("permission denied" in output or "access is denied" in output or
                     "winerror 5" in output or "errno 13" in output or
                     "winerror 32" in output or "file is being used by another process" in output)
    if not cache_failure:
        raise subprocess.CalledProcessError(first.returncode, command)
    print("pip encountered a permissions/locking error; retrying with its download/wheel cache disabled.",flush=True)
    print("Installed packages remain in the shared Python user site; no venv or admin rights are needed.",flush=True)
    second = subprocess.run([*command[:6], "--no-cache-dir", *command[6:]], check=False)
    if second.returncode:
        raise subprocess.CalledProcessError(second.returncode, [*command[:6], "--no-cache-dir", *command[6:]])


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared Python requirement checker and installer")
    parser.add_argument("requirements", type=Path, help="Requirements file to check")
    parser.add_argument("--verify-only", action="store_true", help="Check packages without installation")
    args = parser.parse_args()
    check_interpreter()
    ensure_pip()
    requirements = load_requirements(args.requirements)
    print(f"Checking {len(requirements)} shared Python requirements against {sys.executable}", flush=True)
    missing = unsatisfied(requirements)
    if missing:
        print("Packages needing attention:", flush=True)
        for line in missing:
            print(f"  - {line}", flush=True)
        if args.verify_only:
            return 1
        print("Installing missing/incompatible requirements into reusable user site-packages...", flush=True)
        install_shared_requirements(args.requirements)
        # A new interpreter sees newly created user-site directories and metadata.
        subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        str(args.requirements.resolve()), "--verify-only"], check=True)
    else:
        print("All required packages are already installed at compatible versions.", flush=True)
    if not args.verify_only:
        try:
            add_scripts_to_user_path()
        except OSError as exc:
            # The interpreter works via python -m even when a managed PC blocks PATH writes.
            print(f"WARNING: Could not persist the user PATH entry: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Dependency setup failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
