"""Library state and the operations the UI invokes on it.

The window asks this for data and tells it what the user did; it never
touches repositories or services directly. Everything the UI needs to
react to is a signal, so views stay replaceable.
"""

from __future__ import annotations

import contextlib as _contextlib
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from launcher.app.context import AppContext
from launcher.app.launch_checks import check_launch
from launcher.app.save_keeper import SaveKeeper
from launcher.app.session_recorder import SessionRecorder
from launcher.domain.library_filter import Availability, LibraryFilter
from launcher.domain.models import (
    Game,
    GameConfig,
    SortOrder,
    sort_games,
)
from launcher.services.artwork import GRID


class LibraryController(QObject):
    """Owns the list of games, the filters, and what the user does to them."""

    #: The set of games, or their order, changed.
    library_changed = Signal()
    #: A game's data changed in place; carries its name.
    game_changed = Signal(str)
    #: Something worth telling the user about, e.g. a failed rename.
    error = Signal(str, str)
    #: A transient status message.
    status = Signal(str)
    #: A launch was blocked by pre-launch checks; carries the game name.
    launch_blocked = Signal(str)

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._games: list[Game] = []

        settings = context.settings
        self._sort = _sort_from_settings(settings.get_str("sort_order"))
        self._favorites_first = settings.get_bool("favorites_first")
        self._filter = LibraryFilter.from_json(settings.get("library_filter"))
        if settings.get_bool("hide_missing"):
            # The old "hide missing" preference is now a filter.
            self._filter = self._filter.with_(availability=Availability.INSTALLED)
            settings.update({"hide_missing": False, "library_filter": self._filter.to_json()})

        self.saves = SaveKeeper(context, self)
        self.saves.status.connect(self.status)
        self.saves.error.connect(self.error)

        # Playtime is recorded here rather than in the window, so it is
        # counted whether or not any view is listening.
        self.recorder = SessionRecorder(
            context,
            refresh_game=self.refresh_game,
            filter_shows_running=lambda: self._filter.running,
            emit_library_changed=self.library_changed.emit,
            last_log_tail=context.logs.recent,
            parent=self,
        )
        self.recorder.status.connect(self.status)
        #: The latest pre-launch warnings per game, shown if it then fails.
        self.last_warnings: dict[str, list[str]] = {}

    # -- data ----------------------------------------------------------

    @property
    def context(self) -> AppContext:
        return self._ctx

    @property
    def games(self) -> list[Game]:
        """Every known game, in the current sort order."""
        return self._games

    def visible_games(self) -> list[Game]:
        """The games passing the current search and filters."""
        running = set(self._ctx.processes.running_games)
        artwork = self._ctx.artwork
        return [
            g
            for g in self._games
            if self._filter.matches(
                g,
                running=running,
                has_art=lambda name: artwork.path_for(name, GRID.name) is not None,
            )
        ]

    def game(self, name: str) -> Game | None:
        return next((g for g in self._games if g.name == name), None)

    def reload(self) -> None:
        """Re-read the library from disk."""
        self._games = self._sorted(self._ctx.games.list_games())
        self.library_changed.emit()

    def _sorted(self, games: list[Game]) -> list[Game]:
        return sort_games(games, self._sort, favorites_first=self._favorites_first)

    def refresh_game(self, name: str) -> None:
        """Re-read one game, leaving the rest alone."""
        updated = self._ctx.games.get(name)
        if updated is None:
            self.reload()
            return
        for index, existing in enumerate(self._games):
            if existing.name == name:
                self._games[index] = updated
                self.game_changed.emit(name)
                return
        self.reload()

    # -- filters -------------------------------------------------------

    @property
    def filter(self) -> LibraryFilter:
        return self._filter

    def set_filter(self, library_filter: LibraryFilter) -> None:
        if library_filter == self._filter:
            return
        stored = self._filter.to_json()
        self._filter = library_filter
        if library_filter.to_json() != stored:
            self._ctx.settings.set("library_filter", library_filter.to_json())
        self.library_changed.emit()

    def clear_filters(self) -> None:
        self.set_filter(self._filter.cleared())

    @property
    def search_text(self) -> str:
        return self._filter.text

    def set_search(self, text: str) -> None:
        self.set_filter(self._filter.with_(text=text.strip()))

    @property
    def favorites_only(self) -> bool:
        return self._filter.favorites

    def set_favorites_only(self, enabled: bool) -> None:
        self.set_filter(self._filter.with_(favorites=enabled))

    @property
    def favorites_first(self) -> bool:
        return self._favorites_first

    def set_favorites_first(self, enabled: bool) -> None:
        if enabled == self._favorites_first:
            return
        self._favorites_first = enabled
        self._ctx.settings.set("favorites_first", enabled)
        self._games = self._sorted(self._games)
        self.library_changed.emit()

    @property
    def sort_order(self) -> SortOrder:
        return self._sort

    def set_sort_order(self, order: SortOrder) -> None:
        if order is self._sort:
            return
        self._sort = order
        self._ctx.settings.set("sort_order", order.value)
        self._games = self._sorted(self._games)
        self.library_changed.emit()

    # -- mutations -----------------------------------------------------

    def add_game(self, config: GameConfig) -> bool:
        try:
            self._ctx.games.add(config)
        except FileExistsError:
            self.error.emit(
                "Add Game", f"A game named '{config.name}' already exists."
            )
            return False
        except OSError as e:
            self.error.emit("Add Game", str(e))
            return False
        self.reload()
        return True

    def update_game(self, original_name: str, config: GameConfig) -> bool:
        """Save an edited game, renaming it if the name changed.

        Takes the original name rather than the original Game: callers
        naturally build the new config by mutating the old one, and then
        the two would alias and the rename would be missed.
        """
        if config.name != original_name:
            try:
                self._ctx.games.rename(original_name, config.name)
            except FileExistsError:
                self.error.emit(
                    "Rename Failed", f"A game named '{config.name}' already exists."
                )
                return False
            except OSError as e:
                self.error.emit("Rename Failed", str(e))
                return False
            self._ctx.artwork.rename(original_name, config.name)
            from launcher.services import shortcuts

            if shortcuts.exists(original_name):
                shortcuts.remove(original_name)
                with _contextlib.suppress(OSError):
                    shortcuts.create(config.name, artwork=self._ctx.artwork)

        try:
            self._ctx.games.update(config)
        except OSError as e:
            self.error.emit("Save Failed", str(e))
            return False
        self.reload()
        return True

    def remove_game(self, name: str) -> bool:
        """Delete a game's config, artwork and recorded state."""
        removed = self._ctx.games.remove(name)
        if removed:
            self._ctx.artwork.remove(name)
            self.reload()
        return removed

    def toggle_favorite(self, name: str) -> bool:
        new_state = self._ctx.state.toggle_favorite(name)
        self.refresh_game(name)
        # Favourites can change what the filter admits, and the order.
        if self._filter.favorites or self._favorites_first:
            self._games = self._sorted(self._games)
            self.library_changed.emit()
        return new_state

    def all_tags(self) -> list[str]:
        """Every tag in use across the library, sorted."""
        tags: set[str] = set()
        for game in self._games:
            tags.update(game.tags)
        return sorted(tags)

    def set_tags(self, name: str, raw_tags: str | list[str]) -> None:
        """Replace a game's tags. Accepts comma-separated text or a list."""
        from launcher.domain.models import normalize_tags

        self._ctx.state.set_tags(name, normalize_tags(raw_tags))
        self.refresh_game(name)
        if self._filter.tags:
            self.library_changed.emit()

    def set_notes(self, name: str, notes: str) -> None:
        self._ctx.state.set_notes(name, notes)
        self.refresh_game(name)

    def set_hidden(self, name: str, hidden: bool) -> None:
        """Hide a game from the library, or show it again."""
        self._ctx.state.set_hidden(name, hidden)
        self.reload()

    def set_artwork_from_file(self, name: str, source: Path, art: str) -> bool:
        """Use a local image as a game's artwork."""
        try:
            self._ctx.artwork.store(name, art, source)
        except OSError as e:
            self.error.emit("Artwork", f"Could not use that image:\n{e}")
            return False
        self.status.emit(f"Artwork updated for {name}.")
        self.game_changed.emit(name)
        return True

    # -- launching -----------------------------------------------------

    def launch(self, name: str) -> bool:
        game = self.game(name)
        if game is None:
            return self._ctx.processes.launch(name)
        blocks, warnings = check_launch(game, self._ctx.paths)
        self.last_warnings[name] = [w.title for w in warnings]
        if warnings and not blocks:
            self.status.emit("; ".join(w.title for w in warnings) + ".")
        if blocks:
            text = "\n".join(
                f"• {b.title}: {b.detail or b.hint}".rstrip(": ") for b in blocks
            )
            self.error.emit("Cannot Launch", text)
            self.launch_blocked.emit(name)
            return False
        self.saves.before_launch(game)
        return self._ctx.processes.launch(name)

    def stop(self, name: str) -> bool:
        return self._ctx.processes.stop(name)

    def is_running(self, name: str) -> bool:
        return self._ctx.processes.is_running(name)


def _sort_from_settings(value: str) -> SortOrder:
    try:
        return SortOrder(value)
    except ValueError:
        return SortOrder.NAME
