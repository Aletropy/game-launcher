"""The composition root.

One place builds every service and hands them their dependencies. The UI
receives an AppContext rather than importing module singletons, which is
what lets a test point the whole application at a temporary directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from launcher.data.game_repository import GameRepository
from launcher.data.paths import Paths
from launcher.data.settings_store import SettingsStore
from launcher.data.state_store import StateStore
from launcher.services.artwork import ArtworkCleaner, ArtworkService
from launcher.services.prefix_tools import PrefixToolsService
from launcher.services.process import ProcessService
from launcher.services.save_store import SaveStore
from launcher.services.saves import SaveService
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
    saves: SaveService
    save_store: SaveStore
    prefix_tools: PrefixToolsService
    sgdb: SgdbClient

    @classmethod
    def create(cls, paths: Paths | None = None) -> AppContext:
        """Build the object graph."""
        paths = paths or Paths.default()
        paths.ensure_dirs()

        settings = SettingsStore(paths.settings_file)
        state = StateStore(paths.state_db)
        # Favourites used to live in their own JSON file; move them across
        # once so an upgrade does not lose them.
        state.import_legacy_favorites(paths.legacy_favorites_file)

        artwork = ArtworkService(paths)
        # Earlier versions saved covers into the banner folder; move them
        # to where they belong before anything draws them.
        artwork.reclassify_misfiled()
        return cls(
            paths=paths,
            settings=settings,
            state=state,
            games=GameRepository(paths, state),
            artwork=artwork,
            cleaner=ArtworkCleaner(artwork),
            processes=ProcessService(paths),
            saves=SaveService(paths),
            save_store=SaveStore(paths),
            prefix_tools=PrefixToolsService(paths),
            sgdb=SgdbClient(settings),
        )

    @classmethod
    def for_testing(cls, root: Path) -> AppContext:
        """A context with everything under one temporary directory."""
        return cls.create(Paths.for_testing(root))

    def close(self) -> None:
        """Release resources. Safe to call more than once.

        Wine tools are started detached and deliberately left running:
        closing the launcher should not interrupt a winetricks session
        part way through changing a prefix.
        """
        self.processes.stop_all()
        self.state.close()
