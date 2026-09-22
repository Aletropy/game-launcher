"""Application preferences, as a JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

#: Preference key -> default. Keeping them in one table means the
#: settings dialog and the code that reads them cannot disagree.
DEFAULTS: dict[str, Any] = {
    "sgdb_api_key": "",
    # Prompts the user can silence.
    "skip_missing_check": False,
    "artwork_cleanup_prompted": False,
    # Library.
    "sort_order": "name",
    "view_mode": "list",
    "hide_missing": False,
    "favorites_first": False,
    # A LibraryFilter, as JSON.
    "library_filter": {},
    # Behaviour.
    "confirm_remove": True,
    "close_to_tray": False,
    "close_to_tray_asked": False,
    "library_covers": False,
    "log_max_lines": 5000,
    "fetch_artwork_on_add": True,
    # Appearance.
    "theme": "midnight",
    "accent": "",
    "corners": "rounded",
    "density": "comfortable",
    "text_scale": 100,
    "font": "",
    # Saves.
    "share_saves_by_default": True,
    "backup_auto": True,
    "backup_interval_minutes": 30,
    "backup_keep_recent": 5,
    "backup_keep_daily": 7,
    "backup_keep_weekly": 4,
    # Extra backup exclusions, one pattern per line.
    "backup_exclude": "",
    # Friends. Offline Mode sends and fetches nothing.
    "friends_mode": "offline",
    "friends_server_url": "http://10.0.0.25:8765",
    "friends_share_presence": True,
    # GitHub Releases checked by the startup badge and Settings → About.
    "update_repo": "Aletropy/milso-launcher",
    "update_auto_check": True,
    "update_last_check": "",
    "update_skipped_version": "",
    # Legacy JSON release feed (pre-GitHub). Kept so downgrades do not
    # discard it; nothing reads it any more.
    "update_feed_url": "",
    # Where the Browse button starts when picking a game.
    "last_game_folder": "",
    "last_import_folder": "",
}


class SettingsStore(QObject):
    """Reads and writes preferences, and tells the UI when they change."""

    #: key, new value
    changed = Signal(str, object)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._values: dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(stored, dict):
            # Unknown keys are kept so downgrading does not discard a
            # newer version's preferences.
            self._values.update(stored)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._values, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # -- access --------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, DEFAULTS.get(key, default))

    def get_bool(self, key: str) -> bool:
        return bool(self.get(key))

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (TypeError, ValueError):
            return int(DEFAULTS.get(key, 0))

    def get_str(self, key: str) -> str:
        value = self.get(key)
        return "" if value is None else str(value)

    def set(self, key: str, value: Any) -> None:
        if self._values.get(key) == value:
            return
        self._values[key] = value
        self._save()
        self.changed.emit(key, value)

    def update(self, values: dict[str, Any]) -> None:
        """Apply several preferences, saving once."""
        changed = {k: v for k, v in values.items() if self._values.get(k) != v}
        if not changed:
            return
        self._values.update(changed)
        self._save()
        for key, value in changed.items():
            self.changed.emit(key, value)

    def reset(self, key: str) -> None:
        self.set(key, DEFAULTS.get(key))

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)
