"""Application settings persistence."""

from __future__ import annotations

import json

from launcher.core.paths import CONFIG_DIR, SETTINGS_PATH


def load_settings() -> dict:
    """Load settings from disk."""
    if SETTINGS_PATH.is_file():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(settings: dict) -> None:
    """Persist settings to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def get_sgdb_api_key() -> str:
    """Return the SteamGridDB API key, or empty string if not set."""
    return load_settings().get("sgdb_api_key", "")


def set_sgdb_api_key(key: str) -> None:
    """Save the SteamGridDB API key."""
    settings = load_settings()
    settings["sgdb_api_key"] = key
    save_settings(settings)


def get_skip_missing_check() -> bool:
    """Return True if the missing-executable dialog should be skipped."""
    return load_settings().get("skip_missing_check", False)


def set_skip_missing_check(value: bool) -> None:
    """Persist the skip-missing-check preference."""
    settings = load_settings()
    settings["skip_missing_check"] = value
    save_settings(settings)


def get_flag(name: str, default: bool = False) -> bool:
    """Return a boolean preference."""
    return bool(load_settings().get(name, default))


def set_flag(name: str, value: bool) -> None:
    """Persist a boolean preference."""
    settings = load_settings()
    settings[name] = value
    save_settings(settings)
