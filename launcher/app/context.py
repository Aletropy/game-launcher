"""The composition root.

One place builds every service and hands them their dependencies. The UI
receives an AppContext rather than importing module singletons, which is
what lets a test point the whole application at a temporary directory.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from launcher.app.startup import StartupProfiler
from launcher.data.game_repository import GameRepository
from launcher.data.paths import Paths
from launcher.data.settings_store import SettingsStore
from launcher.data.state_store import StateStore
from launcher.services.artwork import ArtworkCleaner, ArtworkService
from launcher.services.backups import BackupService
from launcher.services.discord import DiscordService
from launcher.services.friends import FriendsService
from launcher.services.game_log import GameLogStore
from launcher.services.prefix_tools import PrefixToolsService
from launcher.services.process import ProcessService
from launcher.services.save_store import SaveStore
from launcher.services.sgdb import SgdbClient


@dataclass
class AppContext:
    """Everything the application needs, wired together."""

    paths: Paths
    settings: SettingsStore
    state: StateStore
    games: GameRepository
    artwork: ArtworkService
    cleaner: ArtworkCleaner
    processes: ProcessService
    logs: GameLogStore
    save_store: SaveStore
    backups: BackupService
    prefix_tools: PrefixToolsService
    sgdb: SgdbClient
    friends: FriendsService
    discord: DiscordService

    @classmethod
    def create(
        cls, paths: Paths | None = None, profiler: StartupProfiler | None = None
    ) -> AppContext:
        """Build the object graph."""
        profiler = profiler or StartupProfiler()
        paths = paths or Paths.default()
        with profiler.stage("ensure-dirs"):
            paths.ensure_dirs()

        with profiler.stage("settings+state"):
            settings = SettingsStore(paths.settings_file)
            state = StateStore(paths.state_db)
            # Favourites used to live in their own JSON file; move them across
            # once so an upgrade does not lose them.
            state.import_legacy_favorites(paths.legacy_favorites_file)

        with profiler.stage("artwork"):
            artwork = ArtworkService(paths)
            # Earlier versions saved covers into the banner folder; move them
            # to where they belong before anything draws them.
            artwork.reclassify_misfiled()
        with profiler.stage("games"):
            games = GameRepository(paths, state)
        with profiler.stage("processes"):
            processes = ProcessService(paths)
            logs = GameLogStore(paths, processes)
        # Finished sessions left by the background watcher (the app quit
        # while games ran) count now; stale launches that already exited
        # are finalized first so nothing stays "running" forever.
        with profiler.stage("sessions-recovery"):
            try:
                from launcher.services import sessions as _sessions
                from launcher.services.process import MIN_SESSION_SECONDS

                _sessions.recover_active(paths, MIN_SESSION_SECONDS)
                _sessions.import_pending(state, paths)
                _ensure_watchers(paths)
            except (OSError, ValueError):
                pass
        # Games still running from a previous run show as playing again,
        # with their real elapsed time; the watcher records their tail.
        with profiler.stage("sessions-reattach"), contextlib.suppress(
            OSError, ValueError, RuntimeError
        ):
            processes.reattach_live()
        return cls(
            paths=paths,
            settings=settings,
            state=state,
            games=games,
            artwork=artwork,
            cleaner=ArtworkCleaner(artwork),
            processes=processes,
            logs=logs,
            save_store=SaveStore(paths),
            backups=BackupService(paths),
            prefix_tools=PrefixToolsService(paths),
            sgdb=SgdbClient(settings),
            # Idle until start(); off until an Application ID is set.
            friends=FriendsService(paths, settings, state, games, processes),
            discord=DiscordService(settings, processes, state=state),
        )

    @classmethod
    def for_testing(cls, root: Path) -> AppContext:
        """A context with everything under one temporary directory."""
        return cls.create(Paths.for_testing(root))

    def close(self) -> None:
        """Release resources. Safe to call more than once.

        Running games are deliberately left alive: each has a detached
        watcher that records its full playtime when it exits. Wine tools
        are started detached and deliberately left running for the same
        reason.
        """
        self.friends.stop()
        with contextlib.suppress(AttributeError, RuntimeError):
            self.discord.stop()
        with contextlib.suppress(AttributeError, RuntimeError):
            self.processes.detach_all()
        try:
            from launcher.services import sessions as _sessions

            _sessions.import_pending(self.state, self.paths)
        except (OSError, ValueError):
            pass
        self.state.close()


def _ensure_watchers(paths: Paths) -> None:
    """Cover live games from a previous run that lost their watcher."""
    from launcher.services import sessions as _sessions
    from launcher.services.session_watcher import spawn_watcher

    for name, entry in _sessions.load_active(paths).items():
        started_iso = entry.get("started_iso")
        pid = entry.get("pid")
        watcher_pid = entry.get("watcher_pid")
        if (
            not isinstance(started_iso, str)
            or not isinstance(pid, int)
            or not _sessions.pid_alive(pid)
        ):
            continue
        if _sessions.pid_alive(watcher_pid):
            continue
        watcher = spawn_watcher(paths, name, started_iso, pid)
        if watcher:
            _sessions.update_active(paths, name, watcher_pid=watcher)
