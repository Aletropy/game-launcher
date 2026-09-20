"""The library sidebar: search, filter and the game list."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.domain.models import (
    Game,
    SortOrder,
    format_last_played,
    format_playtime,
)
from launcher.services.artwork import GRID, ArtworkService
from launcher.ui.theme import DARK

_ICON_SIZE = QSize(28, 40)


def _running_dot(colour: str) -> QIcon:
    """A small filled circle used as the running indicator."""
    pixmap = QPixmap(10, 10)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(colour))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, 8, 8)
    painter.end()
    return QIcon(pixmap)


class LibrarySidebar(QWidget):
    """Search, favourites filter and the list of games."""

    #: A game was selected. Selecting never launches anything.
    selection_changed = Signal(str)
    launch_requested = Signal(str)
    add_requested = Signal()
    import_requested = Signal()
    filters_changed = Signal()
    #: A SortOrder value.
    sort_changed = Signal(str)

    def __init__(
        self, artwork: ArtworkService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self.setObjectName("sidebar")
        self._games: list[Game] = []
        self._running: set[str] = set()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._search = QLineEdit()
        self._search.setObjectName("searchEdit")
        self._search.setPlaceholderText("Search games…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.filters_changed)
        layout.addWidget(self._search)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self._fav_filter = QCheckBox("Favorites only")
        self._fav_filter.toggled.connect(self.filters_changed)
        filter_row.addWidget(self._fav_filter)
        filter_row.addStretch()

        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("sortCombo")
        for order in SortOrder:
            self._sort_combo.addItem(order.label, order.value)
        self._sort_combo.setToolTip("Sort the library")
        self._sort_combo.currentIndexChanged.connect(
            lambda _: self.sort_changed.emit(self._sort_combo.currentData())
        )
        filter_row.addWidget(self._sort_combo)
        layout.addLayout(filter_row)

        self._list = QListWidget()
        self._list.setObjectName("gameList")
        self._list.setIconSize(_ICON_SIZE)
        self._list.setUniformItemSizes(False)
        self._list.setAlternatingRowColors(False)
        self._list.currentItemChanged.connect(self._on_current_changed)
        # Explicitly double-click, never itemActivated: that signal fires
        # on a SINGLE click when the desktop uses single-click activation
        # (KDE's default), which would launch a game just by selecting it.
        self._list.itemDoubleClicked.connect(self._on_activated)

        # Enter still launches, but only when the list has focus.
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self._list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self._launch_current)
        layout.addWidget(self._list, stretch=1)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self._add_btn = QPushButton("+ Add Game")
        self._add_btn.setFixedHeight(34)
        self._add_btn.clicked.connect(self.add_requested)
        button_row.addWidget(self._add_btn)

        self._import_btn = QPushButton("Import\u2026")
        self._import_btn.setFixedHeight(34)
        self._import_btn.setToolTip("Scan a folder for games")
        self._import_btn.clicked.connect(self.import_requested)
        button_row.addWidget(self._import_btn)
        layout.addLayout(button_row)

    def set_sort_order(self, value: str) -> None:
        """Show the active sort without re-emitting the change."""
        index = self._sort_combo.findData(value)
        if index >= 0 and index != self._sort_combo.currentIndex():
            self._sort_combo.blockSignals(True)
            self._sort_combo.setCurrentIndex(index)
            self._sort_combo.blockSignals(False)

    # -- state ---------------------------------------------------------

    def search_text(self) -> str:
        return self._search.text().strip()

    def focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    def favorites_only(self) -> bool:
        return self._fav_filter.isChecked()

    def set_games(self, games: list[Game], *, select: str | None = None) -> None:
        """Repopulate the list, keeping the selection where possible."""
        previous = select if select is not None else self.selected_game()
        self._games = games

        self._list.blockSignals(True)
        self._list.clear()
        for game in games:
            item = QListWidgetItem(game.name)
            item.setData(Qt.ItemDataRole.UserRole, game.name)
            item.setSizeHint(QSize(0, 46))
            icon = self._artwork.pixmap(game.name, GRID.name, _ICON_SIZE, expand=True)
            if icon is not None:
                item.setIcon(QIcon(icon))
            self._decorate(item, game)
            self._list.addItem(item)
        self._list.blockSignals(False)

        if previous is not None and self.select_game(previous):
            return
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self.selection_changed.emit("")

    def _decorate(self, item: QListWidgetItem, game: Game) -> None:
        marks = []
        if game.is_favorite:
            marks.append("\u2605")
        if game.name in self._running:
            marks.append("\u25cf")
        suffix = ("   " + " ".join(marks)) if marks else ""

        detail = self._subtitle(game)
        item.setText(f"{game.name}{suffix}\n{detail}" if detail else f"{game.name}{suffix}")

        if not game.executable_exists:
            item.setForeground(QColor(DARK.fg_muted))
            item.setToolTip(f"Executable not found:\n{game.executable}")
        else:
            item.setForeground(QColor(DARK.fg))
            item.setToolTip(game.name)

    @staticmethod
    def _subtitle(game: Game) -> str:
        """The second line of a row: playtime and when it was last played."""
        if not game.executable_exists:
            return "executable missing"
        parts = [
            p
            for p in (
                format_playtime(game.playtime_seconds),
                format_last_played(game.last_played),
            )
            if p
        ]
        return "  \u00b7  ".join(parts)

    def set_running(self, game_name: str, running: bool) -> None:
        if running:
            self._running.add(game_name)
        else:
            self._running.discard(game_name)
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != game_name:
                continue
            game = next((g for g in self._games if g.name == game_name), None)
            if game is not None:
                self._decorate(item, game)
            return

    def apply_filter(self, text: str, favorites_only: bool, favorites: set[str]) -> None:
        """Hide rows that do not match, and keep a visible row selected."""
        needle = text.lower()
        current_hidden = False
        for row in range(self._list.count()):
            item = self._list.item(row)
            name = str(item.data(Qt.ItemDataRole.UserRole))
            matches = needle in name.lower()
            if favorites_only and name not in favorites:
                matches = False
            item.setHidden(not matches)
            if not matches and row == self._list.currentRow():
                current_hidden = True

        if current_hidden:
            for row in range(self._list.count()):
                if not self._list.item(row).isHidden():
                    self._list.setCurrentRow(row)
                    return
            self._list.setCurrentRow(-1)
            self.selection_changed.emit("")

    def selected_game(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))

    def select_game(self, game_name: str) -> bool:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == game_name:
                self._list.setCurrentRow(row)
                return True
        return False

    # -- signals -------------------------------------------------------

    def _on_current_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        name = "" if current is None else str(current.data(Qt.ItemDataRole.UserRole))
        self.selection_changed.emit(name)

    def _on_activated(self, item: QListWidgetItem) -> None:
        # Double-click or Enter launches; a plain selection never does.
        self.launch_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def _launch_current(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._on_activated(item)
