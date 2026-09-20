"""Library state and the operations the UI invokes on it.

The window asks this for data and tells it what the user did; it never
touches repositories or services directly. Everything the UI needs to
react to is a signal, so views stay replaceable.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from launcher.app.context import AppContext
from launcher.domain.models import (
    Game,
    GameConfig,
    SortOrder,
    matches_filter,
    sort_games,
)


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

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._games: list[Game] = []
        self._search = ""
        self._favorites_only = False

        settings = context.settings
        self._sort = _sort_from_settings(settings.get_str("sort_order"))
        self._hide_missing = settings.get_bool("hide_missing")

        # Playtime is recorded here rather than in the window, so it is
        # counted whether or not any view is listening.
        context.processes.session_recorded.connect(self._on_session_recorded)
        context.processes.game_started.connect(self._on_game_started)

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
        return [
            g
            for g in self._games
            if matches_filter(g, self._search, self._favorites_only, self._hide_missing)
        ]

    def game(self, name: str) -> Game | None:
        return next((g for g in self._games if g.name == name), None)

    def reload(self) -> None:
        """Re-read the library from disk."""
        self._games = sort_games(self._ctx.games.list_games(), self._sort)
        self.library_changed.emit()

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
    def search_text(self) -> str:
        return self._search

    def set_search(self, text: str) -> None:
        text = text.strip()
        if text != self._search:
            self._search = text
            self.library_changed.emit()

    @property
    def favorites_only(self) -> bool:
        return self._favorites_only

    def set_favorites_only(self, enabled: bool) -> None:
        if enabled != self._favorites_only:
            self._favorites_only = enabled
            self.library_changed.emit()

    @property
    def hide_missing(self) -> bool:
        return self._hide_missing

    def set_hide_missing(self, enabled: bool) -> None:
        if enabled != self._hide_missing:
            self._hide_missing = enabled
            self._ctx.settings.set("hide_missing", enabled)
            self.library_changed.emit()

    @property
    def sort_order(self) -> SortOrder:
        return self._sort

    def set_sort_order(self, order: SortOrder) -> None:
        if order is self._sort:
            return
        self._sort = order
        self._ctx.settings.set("sort_order", order.value)
        self._games = sort_games(self._games, order)
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
        # Favourites can change what the filter admits.
        if self._favorites_only:
            self.library_changed.emit()
        return new_state

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
        if game is not None and not game.executable_exists:
            self.error.emit(
                "Cannot Launch",
                f"The executable for '{name}' was not found:\n{game.executable}",
            )
            return False
        return self._ctx.processes.launch(name)

    def stop(self, name: str) -> bool:
        return self._ctx.processes.stop(name)

    def is_running(self, name: str) -> bool:
        return self._ctx.processes.is_running(name)

    def _on_game_started(self, name: str) -> None:
        self._ctx.state.record_launch(name)
        self.refresh_game(name)

    def _on_session_recorded(self, name: str, seconds: int) -> None:
        self._ctx.state.add_playtime(name, seconds)
        self.refresh_game(name)
        minutes = max(1, seconds // 60)
        self.status.emit(f"Recorded {minutes} min of playtime for {name}.")


def _sort_from_settings(value: str) -> SortOrder:
    try:
        return SortOrder(value)
    except ValueError:
        return SortOrder.NAME
