"""Crash-resistant local file operations for Task Runner workflows.

Complete replacement output is written beside the target and atomically renamed.
The destination is not removed before a new copy has completed.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_text(destination: Path, text: str) -> None:
    """Replace a UTF-8 text file only once the complete new content is durable."""
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=destination.parent,
                                         prefix=f".{destination.name}.", suffix=".tmp", delete=False) as file:
            staged = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(staged, destination)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def atomic_copy_file(source: Path, destination: Path, *, overwrite: bool = False) -> None:
    """Stage a file copy, then replace the destination only after the copy succeeds."""
    source, destination = Path(source).expanduser(), Path(destination).expanduser()
    if not source.is_file():
        raise ValueError(f"Copy file requires a regular file: {source}")
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination cannot be the same path")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Destination exists (overwrite disabled): {destination}")
    if destination.is_dir():
        raise IsADirectoryError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    staged = Path(name)
    try:
        shutil.copy2(source, staged)
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Destination exists (overwrite disabled): {destination}")
        os.replace(staged, destination)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
