"""Stable paths used by source and packaged builds."""

from __future__ import annotations

import os
from pathlib import Path
import sys


APP_SLUG = "HunterDuel"


def bundled_path(relative: str) -> Path:
    """Return a resource path, including inside a PyInstaller bundle."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def user_data_dir() -> Path:
    """Keep saves and mods outside the EXE so updates never remove them."""
    if not getattr(sys, "frozen", False):
        target = Path(__file__).resolve().parent / ".local_data"
        target.mkdir(parents=True, exist_ok=True)
        return target
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    target = base / APP_SLUG
    target.mkdir(parents=True, exist_ok=True)
    return target


def installation_dir() -> Path:
    """Folder visible to the player: source folder or folder containing EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def mods_dir() -> Path:
    portable = installation_dir() / "mods"
    try:
        portable.mkdir(parents=True, exist_ok=True)
        return portable
    except OSError:
        # Read-only install locations fall back to the persistent user folder.
        target = user_data_dir() / "mods"
        target.mkdir(parents=True, exist_ok=True)
        return target
