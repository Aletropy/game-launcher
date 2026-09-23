"""Platform helpers. Linux is the main target; Windows is a sub-app.

Centralises every ``sys.platform`` check so call sites read as
``platform.is_windows()`` instead of scattering string comparisons.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def current() -> str:
    """'windows', 'linux', or the raw ``sys.platform`` elsewhere."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def is_windows() -> bool:
    return current() == "windows"


def is_linux() -> bool:
    return current() == "linux"


def app_platform() -> str:
    """Stable identifier sent to the friends server and update checker."""
    name = current()
    return name if name in ("windows", "linux") else "unknown"


def config_home() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    if override:
        return Path(override)
    if is_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "milso-launcher"
    return Path.home() / ".config"


def data_home() -> Path:
    override = os.environ.get("XDG_DATA_HOME")
    if override:
        return Path(override)
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "milso-launcher"
    return Path.home() / ".local" / "share"


def cache_home() -> Path:
    override = os.environ.get("XDG_CACHE_HOME")
    if override:
        return Path(override)
    if is_windows():
        return data_home() / "cache"
    return Path.home() / ".cache"
