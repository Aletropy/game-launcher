"""A full-area cover grid for picking a game at a glance.

One click chooses a game and returns to the library; double-click plays
it straight away. Items share one size so scrolling stays smooth no
matter how large the library grows, and covers come from the same cache
the rows use.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from launcher.domain.models import Game
from launcher.services.artwork import GRID, ArtworkService
from launcher.ui.widgets.sidebar import letter_tile

#: Portrait cover and room for the label underneath.
_COVER = QSize(200, 300)
_ITEM = QSize(216, 348)


class CoversGrid(QListWidget):
    """Large covers in a fast static grid."""

    #: Single click (or Enter): show this game in the library.
    game_chosen = Signal(str)
    #: Double click: play it straight away.
    game_activated = Signal(str)

    def __init__(self, artwork: ArtworkService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self.setObjectName("coversGrid")
        self.setViewMode(self.ViewMode.IconMode)
        self.setResizeMode(self.ResizeMode.Adjust)
        self.setMovement(self.Movement.Static)
        self.setSpacing(14)
        self.setIconSize(_COVER)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.itemClicked.connect(self._on_clicked)
        self.itemDoubleClicked.connect(self._on_activated)

    def refresh(self, games: list[Game], running: set[str] | frozenset[str] = frozenset()) -> None:
        """Refill the grid. Covers resolve through the shared cache."""
        self.setUpdatesEnabled(False)
        try:
            self.clear()
            for game in games:
                cover = self._cover(game.name)
                marks = "  \u25cf" if game.name in running else ""
                star = "\u2605 " if game.is_favorite else ""
                item = QListWidgetItem(QIcon(cover), f"{star}{game.name}{marks}")
                item.setData(Qt.ItemDataRole.UserRole, game.name)
                item.setSizeHint(_ITEM)
                item.setToolTip(game.name)
                self.addItem(item)
        finally:
            self.setUpdatesEnabled(True)

    def _cover(self, name: str) -> QPixmap:
        dpr = self.devicePixelRatioF()
        return (
            self._artwork.pixmap(name, GRID.name, _COVER, expand=True, dpr=dpr)
            or letter_tile(name, _COVER, dpr)
        )

    def _on_clicked(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(name, str) and name:
            self.game_chosen.emit(name)

    def _on_activated(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(name, str) and name:
            self.game_activated.emit(name)
