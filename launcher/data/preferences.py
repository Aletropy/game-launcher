"""Typed access to preferences.

``SettingsStore`` stays a string-keyed JSON bag (unknown keys survive
downgrades), but new code should read through ``Preferences`` so a typo
fails loudly at attribute time instead of silently returning a default.
"""

from __future__ import annotations

from launcher.data.settings_store import SettingsStore
from launcher.domain.models import SortOrder


class Preferences:
    """A typed view over a SettingsStore. Read-only by convention."""

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings

    @property
    def store(self) -> SettingsStore:
        return self._settings

    # -- behaviour --------------------------------------------------------

    @property
    def confirm_remove(self) -> bool:
        return self._settings.get_bool("confirm_remove")

    @property
    def close_to_tray(self) -> bool:
        return self._settings.get_bool("close_to_tray")

    @property
    def close_to_tray_asked(self) -> bool:
        return self._settings.get_bool("close_to_tray_asked")

    @property
    def log_max_lines(self) -> int:
        return self._settings.get_int("log_max_lines")

    @property
    def fetch_artwork_on_add(self) -> bool:
        return self._settings.get_bool("fetch_artwork_on_add")

    # -- library ----------------------------------------------------------

    @property
    def sort_order(self) -> SortOrder:
        try:
            return SortOrder(self._settings.get_str("sort_order"))
        except ValueError:
            return SortOrder.NAME

    @property
    def favorites_first(self) -> bool:
        return self._settings.get_bool("favorites_first")

    # -- saves ------------------------------------------------------------

    @property
    def share_saves_by_default(self) -> bool:
        return self._settings.get_bool("share_saves_by_default")

    @property
    def backup_auto(self) -> bool:
        return self._settings.get_bool("backup_auto")

    @property
    def backup_interval_minutes(self) -> int:
        return self._settings.get_int("backup_interval_minutes")

    # -- friends ----------------------------------------------------------

    @property
    def friends_online(self) -> bool:
        return self._settings.get_str("friends_mode") == "online"

    @property
    def friends_share_presence(self) -> bool:
        return self._settings.get_bool("friends_share_presence")

    # -- updates ----------------------------------------------------------

    @property
    def update_repo(self) -> str:
        return self._settings.get_str("update_repo").strip()

    @property
    def update_auto_check(self) -> bool:
        return self._settings.get_bool("update_auto_check")

    @property
    def update_last_check(self) -> str:
        return self._settings.get_str("update_last_check")

    @property
    def update_skipped_version(self) -> str:
        return self._settings.get_str("update_skipped_version").strip()

    @property
    def update_feed_url(self) -> str:
        """Legacy JSON feed setting. Unused since GitHub Releases took over."""
        return self._settings.get_str("update_feed_url").strip()
