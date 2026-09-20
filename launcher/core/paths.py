"""Canonical filesystem locations.

Every other module imports from here rather than recomputing the project
root, so there is one place to change if the layout moves.
"""

from __future__ import annotations

from pathlib import Path

# launcher/core/paths.py -> launcher/core -> launcher -> <project root>
BASE_DIR = Path(__file__).resolve().parent.parent.parent

GAMES_DIR = BASE_DIR / "games"
LAUNCHER_SCRIPT = BASE_DIR / "game-launcher.sh"
PREFIX_NAME_FILE = BASE_DIR / ".prefix-name"
PREFIXES_DIR = BASE_DIR / "prefixes"
ICON_PATH = BASE_DIR / "icon.png"

PACKAGE_DIR = BASE_DIR / "launcher"
ARTWORK_DIR = PACKAGE_DIR / "artwork"
# Pre-revamp artwork lived in a flat directory keyed by display name. It is
# read as a fallback until the cleanup dialog migrates it.
LEGACY_HEROES_DIR = PACKAGE_DIR / "heroes"

CONFIG_DIR = Path.home() / ".config" / "launcher"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
FAVORITES_PATH = CONFIG_DIR / "favorites.json"
