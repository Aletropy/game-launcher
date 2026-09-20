"""Flow layout grid for game cards."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLayout,
    QLayoutItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from launcher.core.games import Game
from launcher.ui.widgets.game_card import GameCard


class GameGrid(QWidget):
    """Scrollable grid of game cards with flow layout."""

    play_requested = Signal(str)
    favorite_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)
    fetch_artwork_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[GameCard] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._flow_layout = FlowLayout(self._container, hspacing=16, vspacing=16)
        self._flow_layout.setContentsMargins(24, 16, 24, 16)
        self._container.setLayout(self._flow_layout)

        self._empty_label = QLabel("No games found. Add a game to get started.")
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)

        self._scroll.setWidget(self._container)
        main_layout.addWidget(self._scroll)
        main_layout.addWidget(self._empty_label)

    def set_games(self, games: list[Game]) -> None:
        self.clear()
        for game in games:
            card = GameCard(game)
            card.play_clicked.connect(self.play_requested)
            card.favorite_clicked.connect(self.favorite_requested)
            card.edit_clicked.connect(self.edit_requested)
            card.remove_clicked.connect(self.remove_requested)
            card.fetch_artwork_clicked.connect(self.fetch_artwork_requested)
            self._flow_layout.add_card(card)
            self._cards.append(card)
        self._update_empty()

    def clear(self) -> None:
        while self._flow_layout.count():
            item = self._flow_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        self._cards.clear()

    def set_running(self, game_name: str, running: bool) -> None:
        for card in self._cards:
            if card.game.name == game_name:
                card.set_running(running)
                break

    def set_favorite(self, game_name: str, is_fav: bool) -> None:
        for card in self._cards:
            if card.game.name == game_name:
                card.update_favorite(is_fav)
                break

    def refresh_favorites(self, fav_names: set[str]) -> None:
        for card in self._cards:
            card.update_favorite(card.game.name in fav_names)

    def _update_empty(self) -> None:
        self._empty_label.setVisible(len(self._cards) == 0)
        self._scroll.setVisible(len(self._cards) > 0)

    def filter_cards(self, text: str, favorites_only: bool = False, fav_names: set[str] | None = None) -> None:
        visible_count = 0
        for card in self._cards:
            matches_text = text.lower() in card.game.name.lower() if text else True
            matches_fav = (not favorites_only) or card.game.name in (fav_names or set())
            visible = matches_text and matches_fav
            card.setVisible(visible)
            if visible:
                visible_count += 1
        self._empty_label.setText(
            "No games match your search." if text or favorites_only
            else "No games found. Add a game to get started."
        )
        self._empty_label.setVisible(visible_count == 0)
        self._scroll.setVisible(visible_count > 0)


class FlowLayout(QLayout):
    """Flow layout that wraps children left-to-right, top-to-bottom."""

    def __init__(self, parent: QWidget | None = None, hspacing: int = 16, vspacing: int = 16) -> None:
        super().__init__(parent)
        self._hspacing = hspacing
        self._vspacing = vspacing
        self._items: list[QLayoutItem] = []

    def add_card(self, widget: QWidget) -> None:
        pw = self.parentWidget()
        if pw is not None:
            widget.setParent(pw)
        self.addItem(QWidgetItem(widget))

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)
        pw = self.parentWidget()
        if pw is not None:
            pw.updateGeometry()

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(width, dry=True)

    def setGeometry(self, rect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect.width(), dry=False)

    def sizeHint(self):
        w = self.parentWidget().width() if self.parentWidget() else 400
        self._do_layout(w, dry=True)
        return self.minimumSize()

    def _do_layout(self, width: int, dry: bool) -> int:
        margins = self.contentsMargins()
        left = margins.left()
        available = max(1, width - left - margins.right())
        x = left
        y = margins.top()
        row_height = 0

        for item in self._items:
            widget = item.widget()
            # isHidden(), not isVisible(): a widget whose ancestor is hidden
            # is "not visible" but must still be laid out, or the grid comes
            # up empty the first time its page is shown.
            if widget is None or widget.isHidden():
                continue
            w = item.sizeHint().width()
            h = item.sizeHint().height()

            if x - left + w > available and x > left:
                x = left
                y += row_height + self._vspacing
                row_height = 0

            if not dry:
                item.setGeometry(QRect(x, y, w, h))

            x += w + self._hspacing
            row_height = max(row_height, h)

        return y + row_height + margins.bottom()
