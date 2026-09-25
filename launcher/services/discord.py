"""Discord Rich Presence: show the running game in Discord, opt-in.

Off by default. When enabled and a Discord Application ID is set, the
service connects to the local Discord client (via ``pypresence``, which
talks to the Discord IPC socket on Linux and the named pipe on
Windows) and sets/clears the activity as games start and stop.

Cover art: Discord only renders asset *keys* uploaded in the Developer
Portal (or https:// URLs). Local cover files cannot be pushed as bytes,
so the default ``large_image`` is the slugified game name (e.g.
``elden_ring``) with fallback to ``milso-logo``. Upload covers under
those keys once and each game shows its own art.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from launcher.data.settings_store import SettingsStore
from launcher.services.process import ProcessService

#: Asset keys must be lowercase alphanumeric/underscore/dash.
_KEY_RE = re.compile(r"[^a-z0-9_-]+")

#: Template variables available in every configurable text field.
TEMPLATE_VARS = ("{game}", "{game_key}", "{elapsed}", "{total}", "{platform}")

#: Large image source modes.
LARGE_MODES = ("game-key", "static", "url-template")


def game_key(name: str) -> str:
    """Slugify a game name into a Discord asset key."""
    slug = _KEY_RE.sub("_", name.strip().lower().replace(" ", "_"))
    slug = re.sub(r"_+", "_", slug).strip("_-")
    return (slug or "game")[:32]


def format_elapsed(seconds: int) -> str:
    """Human elapsed time: '45s', '12m', '1h 05m'."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, _rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"


def format_template(
    template: str,
    *,
    game: str = "",
    key: str = "",
    elapsed: int = 0,
    total: int = 0,
    platform: str = "",
) -> str:
    """Render a user template. Unknown placeholders are left untouched."""
    return (
        template.replace("{game}", game)
        .replace("{game_key}", key or game_key(game))
        .replace("{elapsed}", format_elapsed(elapsed))
        .replace("{total}", format_elapsed(total))
        .replace("{platform}", platform)
    )


def game_dir(executable: str) -> str:
    """The folder containing a game's executable, or '' when unknown."""
    from pathlib import Path

    exe = (executable or "").strip().strip('"')
    if not exe:
        return ""
    try:
        return str(Path(exe).expanduser().parent)
    except (OSError, ValueError):
        return ""


class DiscordService(QObject):
    """Opt-in Rich Presence. Silent unless enabled and configured."""

    #: Human-readable notice for Settings (connected, retrying, error).
    notice = Signal(str)

    def __init__(
        self,
        settings: SettingsStore,
        processes: ProcessService,
        *,
        parent: QObject | None = None,
        presence_factory: Callable[[str], Any] | None = None,
        state: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._processes = processes
        self._state = state
        self._factory = presence_factory
        self._presence: Any | None = None
        self._connected = False
        self._started = False
        #: game name -> epoch when it started (for the elapsed timestamp).
        self._started_at: dict[str, float] = {}

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._connect)

        settings.changed.connect(self._on_setting_changed)
        processes.game_started.connect(self._on_game_started)
        processes.game_finished.connect(self._on_game_finished)

    # -- state -----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._settings.get_bool("discord_enabled")

    @property
    def app_id(self) -> str:
        return self._settings.get_str("discord_app_id").strip()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def current_game(self) -> str | None:
        running = self._processes.running_games
        return running[-1] if running else None

    # -- lifetime --------------------------------------------------------

    def start(self) -> None:
        """Connect if enabled. Called once the window is up."""
        self._started = True
        if self.enabled and self.app_id:
            self._connect()

    def stop(self) -> None:
        """Clear presence and disconnect. Sends nothing when offline."""
        self._retry.stop()
        if self._presence is not None and self._connected:
            with contextlib.suppress(Exception):
                self._presence.clear()
        if self._presence is not None:
            with contextlib.suppress(Exception):
                self._presence.close()
        self._presence = None
        self._connected = False

    def _on_setting_changed(self, key: str, _value: object) -> None:
        if key in ("discord_enabled", "discord_app_id"):
            self.stop()
            if self._started and self.enabled and self.app_id:
                self._connect()
        elif key.startswith("discord_") and self._connected:
            self.refresh()

    # -- game events -----------------------------------------------------

    def _on_game_started(self, name: str) -> None:
        self._started_at[name] = time.time()
        self.refresh()

    def _on_game_finished(self, name: str, _code: int) -> None:
        self._started_at.pop(name, None)
        self.refresh()

    def refresh(self) -> None:
        """Push the current game (or idle/clear) to Discord."""
        if not self._started or not self.enabled or not self.app_id:
            return
        if not self._connected:
            self._connect()
            return
        name = self.current_game
        if name is None:
            self._show_idle()
            return
        self._update(name)

    # -- IPC -------------------------------------------------------------

    def _connect(self) -> None:
        if not self._started or not self.enabled or not self.app_id:
            return
        if self._connected:
            self.refresh()
            return
        try:
            factory = self._factory or self._default_factory
            presence = factory(self.app_id)
            presence.connect()
        except Exception as e:  # noqa: BLE001 - Discord absent, ID bad, etc.
            self._connected = False
            self._presence = None
            self._schedule_retry()
            self.notice.emit(f"Discord: {e}")
            return
        self._presence = presence
        self._connected = True
        self.notice.emit("Discord connected.")
        self.refresh()

    @staticmethod
    def _default_factory(app_id: str) -> Any:
        from pypresence import Presence

        return Presence(app_id)

    def _schedule_retry(self, delay_ms: int = 30000) -> None:
        if not self._retry.isActive():
            self._retry.start(delay_ms)

    def _payload(self, name: str) -> dict[str, Any]:
        from launcher import platform as _platform

        settings = self._settings
        key = game_key(name)
        elapsed = self._processes.elapsed_seconds(name)
        total = 0
        if self._state is not None:
            try:
                total = int(self._state.get(name).playtime_seconds)
            except (AttributeError, ValueError, TypeError):
                total = 0
        platform = _platform.app_platform()
        ctx: dict[str, Any] = {
            "game": name,
            "key": key,
            "elapsed": elapsed,
            "total": total,
            "platform": platform,
        }
        details = format_template(settings.get_str("discord_details") or "Playing {game}", **ctx)
        state = format_template(settings.get_str("discord_state") or "", **ctx)
        large_text = format_template(settings.get_str("discord_large_text") or "{game}", **ctx)
        small_text = format_template(settings.get_str("discord_small_text") or "", **ctx)
        mode = settings.get_str("discord_large_mode") or "game-key"
        if mode not in LARGE_MODES:
            mode = "game-key"
        if mode == "static":
            large_image = settings.get_str("discord_large_static") or "milso-logo"
        elif mode == "url-template":
            template = settings.get_str("discord_large_template") or ""
            large_image = format_template(template, **ctx) if template else key
        else:
            large_image = key
        payload: dict[str, Any] = {
            "details": details[:128] or name[:128],
            "large_image": (large_image or "milso-logo")[:256],
            "large_text": large_text[:128] or None,
        }
        if state:
            payload["state"] = state[:128]
        small_key = settings.get_str("discord_small_key").strip()
        if small_key:
            payload["small_image"] = small_key[:256]
            if small_text:
                payload["small_text"] = small_text[:128]
        elif small_text:
            payload["small_text"] = small_text[:128]
        if settings.get_bool("discord_show_elapsed"):
            started = self._started_at.get(name)
            if started is None:
                started = time.time() - elapsed
                self._started_at[name] = started
            payload["start"] = int(started)
        return payload

    def _update(self, name: str) -> None:
        assert self._presence is not None
        try:
            self._presence.update(**self._payload(name))
        except Exception as e:  # noqa: BLE001 - connection dropped mid-game
            self._connected = False
            with contextlib.suppress(Exception):
                self._presence.close()
            self._presence = None
            self._schedule_retry()
            self.notice.emit(f"Discord: {e}")

    def _show_idle(self) -> None:
        assert self._presence is not None
        if self._settings.get_bool("discord_idle_enabled"):
            text = format_template(
                self._settings.get_str("discord_idle_text") or "Browsing library",
                game="",
                key="",
                elapsed=0,
                total=0,
                platform="",
            )
            try:
                self._presence.update(
                    details=text[:128],
                    large_image="milso-logo",
                )
            except Exception:  # noqa: BLE001 - best effort
                self._connected = False
                self._presence = None
                self._schedule_retry()
        else:
            try:
                self._presence.clear()
            except Exception:  # noqa: BLE001 - best effort
                self._connected = False
                self._presence = None
                self._schedule_retry()
