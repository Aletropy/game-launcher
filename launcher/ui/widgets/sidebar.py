"""The library sidebar: search, filter and the game list."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.domain.library_filter import (
    Availability,
    LibraryFilter,
    PlayState,
    PrefixKind,
)
from launcher.domain.models import (
    Game,
    SortOrder,
    format_last_played,
    format_playtime,
)
from launcher.services.artwork import GRID, ICON, ArtworkService
from launcher.ui.theme import metrics, palette

#: Rows shorter than this show the name only.
_TWO_LINE_HEIGHT = 42


def _icon_size() -> QSize:
    size = metrics().icon_size
    return QSize(size, size)


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


def letter_tile(
    name: str, size: QSize, dpr: float = 1.0, *, light: bool | None = None
) -> QPixmap:
    """A rounded tile with a game's initial, for games without art.

    The hue comes from the name, so a game keeps its colour.
    """
    pixmap = QPixmap(round(size.width() * dpr), round(size.height() * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    hue = sum(map(ord, name)) * 37 % 360
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    if light is None:
        light = palette().is_light
    painter.setBrush(QColor.fromHsl(hue, 110 if light else 90, 215 if light else 70))
    painter.drawRoundedRect(0, 0, size.width(), size.height(), 6, 6)
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(round(size.height() * 0.46))
    painter.setFont(font)
    painter.setPen(QColor.fromHsl(hue, 150, 90 if light else 210))
    initial = next((c for c in name if c.isalnum()), "?").upper()
    painter.drawText(
        0, 0, size.width(), size.height(), Qt.AlignmentFlag.AlignCenter, initial
    )
    painter.end()
    return pixmap


class LibrarySidebar(QWidget):
    """Search, favourites filter and the list of games."""

    #: A game was selected. Selecting never launches anything.
    selection_changed = Signal(str)
    launch_requested = Signal(str)
    add_requested = Signal()
    import_requested = Signal()
    #: The LibraryFilter the user asked for.
    filter_changed = Signal(object)
    #: A SortOrder value.
    sort_changed = Signal(str)
    favorites_first_changed = Signal(bool)

    def __init__(
        self, artwork: ArtworkService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self.setObjectName("sidebar")
        self._games: list[Game] = []
        self._running: set[str] = set()
        self._filter = LibraryFilter()
        #: Tags seen in the listed games, for the filter menu.
        self._known_tags: list[str] = []
        #: List rows or a cover grid.
        self._covers = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self._search = QLineEdit()
        self._search.setObjectName("searchEdit")
        self._search.setPlaceholderText("Search games\u2026")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(
            lambda text: self._emit_filter(self._filter.with_(text=text.strip()))
        )
        search_row.addWidget(self._search, stretch=1)

        self._filter_btn = QToolButton()
        self._filter_btn.setObjectName("filterButton")
        self._filter_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._filter_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._filter_menu = QMenu(self._filter_btn)
        self._filter_menu.aboutToShow.connect(self._build_filter_menu)
        self._filter_btn.setMenu(self._filter_menu)
        search_row.addWidget(self._filter_btn)
        layout.addLayout(search_row)

        sort_row = QHBoxLayout()
        sort_row.setSpacing(6)
        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("sortCombo")
        for order in SortOrder:
            self._sort_combo.addItem(order.label, order.value)
        self._sort_combo.setToolTip("Sort the library")
        self._sort_combo.currentIndexChanged.connect(
            lambda _: self.sort_changed.emit(self._sort_combo.currentData())
        )
        sort_row.addWidget(self._sort_combo, stretch=1)

        self._fav_first = QToolButton()
        self._fav_first.setObjectName("favFirstButton")
        self._fav_first.setText("\u2605 first")
        self._fav_first.setCheckable(True)
        self._fav_first.setToolTip("Keep favourites at the top")
        self._fav_first.toggled.connect(self.favorites_first_changed)
        sort_row.addWidget(self._fav_first)

        self._covers_btn = QToolButton()
        self._covers_btn.setObjectName("coversButton")
        self._covers_btn.setText("Covers")
        self._covers_btn.setCheckable(True)
        self._covers_btn.setToolTip("Show covers instead of rows")
        self._covers_btn.toggled.connect(self.set_covers)
        sort_row.addWidget(self._covers_btn)
        layout.addLayout(sort_row)

        self._list = QListWidget()
        self._list.setObjectName("gameList")
        self._list.setIconSize(_icon_size())
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

        self._count_label = QLabel()
        self._count_label.setObjectName("hintLabel")
        self._count_label.setTextFormat(Qt.TextFormat.RichText)
        self._count_label.linkActivated.connect(
            lambda _: self._emit_filter(self._filter.cleared())
        )
        layout.addWidget(self._count_label)

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

    def set_favorites_first(self, enabled: bool) -> None:
        self._fav_first.blockSignals(True)
        self._fav_first.setChecked(enabled)
        self._fav_first.blockSignals(False)

    # -- filters -------------------------------------------------------

    def set_filter(self, library_filter: LibraryFilter) -> None:
        """Show the active filter without re-emitting it."""
        self._filter = library_filter
        if self._search.text().strip() != library_filter.text:
            self._search.blockSignals(True)
            self._search.setText(library_filter.text)
            self._search.blockSignals(False)
        count = library_filter.active_count
        self._filter_btn.setText(f"Filters \u00b7 {count}" if count else "Filters")
        self._filter_btn.setProperty("active", "true" if count else "false")
        style = self._filter_btn.style()
        style.unpolish(self._filter_btn)
        style.polish(self._filter_btn)

    def set_counts(self, shown: int, total: int) -> None:
        """'12 of 40 games', with a way out when filters hide some."""
        if self._filter.is_default or shown == total:
            self._count_label.setText(f"{total} game{'s' if total != 1 else ''}")
            return
        self._count_label.setText(
            f"{shown} of {total} games shown \u00b7 <a href='clear'>Clear filters</a>"
        )

    def _emit_filter(self, library_filter: LibraryFilter) -> None:
        if library_filter != self._filter:
            self._filter = library_filter
            self.filter_changed.emit(library_filter)

    def _build_filter_menu(self) -> None:
        """Rebuilt on every open, so it always reflects the filter."""
        menu = self._filter_menu
        menu.clear()
        current = self._filter

        def toggle(label: str, field: str) -> None:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(bool(getattr(current, field)))
            action.toggled.connect(
                lambda on: self._emit_filter(self._filter.with_(**{field: on}))
            )
            menu.addAction(action)

        def choice(title: str, field: str, values: type[Enum]) -> None:
            menu.addSection(title)
            group = QActionGroup(menu)
            group.setExclusive(True)
            for value in values:
                action = QAction(value.label, menu)  # type: ignore[attr-defined]
                action.setCheckable(True)
                action.setChecked(getattr(current, field) is value)
                action.triggered.connect(
                    lambda _=False, v=value: self._emit_filter(
                        self._filter.with_(**{field: v})
                    )
                )
                group.addAction(action)
                menu.addAction(action)

        menu.addSection("Show only")
        toggle("\u2605  Favourites", "favorites")
        toggle("\u25cf  Running now", "running")
        toggle("Missing a cover", "missing_art")
        toggle("Show hidden games", "show_hidden")
        if self._known_tags:
            menu.addSection("Tags")
            for tag in self._known_tags:
                action = QAction(tag, menu)
                action.setCheckable(True)
                action.setChecked(tag in current.tags)
                action.toggled.connect(
                    lambda on, t=tag: self._emit_filter(self._with_tag(t, on))
                )
                menu.addAction(action)
        choice("Installed", "availability", Availability)
        choice("History", "played", PlayState)
        choice("Wine prefix", "prefix", PrefixKind)
        menu.addSeparator()
        clear = menu.addAction("Clear filters")
        clear.setEnabled(current.active_count > 0)
        clear.triggered.connect(lambda: self._emit_filter(self._filter.cleared()))

    def _with_tag(self, tag: str, on: bool) -> LibraryFilter:
        """The filter with one tag added or removed."""
        tags = [t for t in self._filter.tags if t != tag]
        if on:
            tags.append(tag)
        return self._filter.with_(tags=tuple(sorted(tags)))

    # -- state ---------------------------------------------------------

    def search_text(self) -> str:
        return self._search.text().strip()

    def clear_filters(self) -> None:
        """Drop the search text and every filter."""
        self._emit_filter(LibraryFilter())
        self.set_filter(LibraryFilter())

    def focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    def set_known_tags(self, tags: list[str]) -> None:
        """Tags offered in the filter menu. Fed from the whole library."""
        self._known_tags = list(tags)

    @property
    def covers(self) -> bool:
        """Whether the list shows covers instead of rows."""
        return self._covers

    def set_covers(self, enabled: bool) -> None:
        """Switch between rows and a cover grid, keeping the selection."""
        if enabled == self._covers:
            return
        self._covers = enabled
        if self._covers_btn.isChecked() != enabled:
            self._covers_btn.setChecked(enabled)
        self.set_games(self._games, select=self.selected_game())

    def set_games(self, games: list[Game], *, select: str | None = None) -> None:
        """Repopulate the list, keeping the selection where possible."""
        previous = select if select is not None else self.selected_game()
        self._games = games
        # Density and theme can change between calls.
        self._list.setIconSize(_icon_size())
        if self._covers:
            self._list.setViewMode(self._list.ViewMode.IconMode)
            self._list.setResizeMode(self._list.ResizeMode.Adjust)
            self._list.setMovement(self._list.Movement.Static)
            self._list.setSpacing(8)
            self._list.setIconSize(QSize(120, 180))
            self._list.setUniformItemSizes(False)
        else:
            self._list.setViewMode(self._list.ViewMode.ListMode)
            self._list.setSpacing(0)
            self._list.setIconSize(_icon_size())
            self._list.setUniformItemSizes(False)

        self._list.blockSignals(True)
        self._list.clear()
        for game in games:
            item = QListWidgetItem(game.name)
            item.setData(Qt.ItemDataRole.UserRole, game.name)
            if self._covers:
                item.setIcon(QIcon(self._cover_icon(game.name)))
                item.setSizeHint(QSize(132, 216))
                item.setText(game.name)
            else:
                item.setSizeHint(QSize(0, metrics().row_height))
                item.setIcon(QIcon(self._row_icon(game.name)))
            self._decorate(item, game)
            if self._covers:
                # The grid shows covers; rows carry the details.
                marks = "  \u2605" if game.is_favorite else ""
                item.setText(f"{game.name}{marks}")
            self._list.addItem(item)
        self._list.blockSignals(False)

        if previous is not None and self.select_game(previous):
            return
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self.selection_changed.emit("")

    def _cover_icon(self, name: str) -> QPixmap:
        """A portrait cover for the grid, falling back to the row icon."""
        size = QSize(120, 180)
        dpr = self.devicePixelRatioF()
        return (
            self._artwork.pixmap(name, GRID.name, size, expand=True, dpr=dpr)
            or self._row_icon(name)
        )

    def _row_icon(self, name: str) -> QPixmap:
        """The game's icon, a square crop of its cover, or its initial."""
        dpr = self.devicePixelRatioF()
        size = _icon_size()
        return (
            self._artwork.pixmap(name, ICON.name, size, dpr=dpr)
            or self._artwork.pixmap(name, GRID.name, size, expand=True, dpr=dpr)
            or letter_tile(name, size, dpr)
        )

    def _decorate(self, item: QListWidgetItem, game: Game) -> None:
        marks = []
        if game.is_favorite:
            marks.append("\u2605")
        if game.name in self._running:
            marks.append("\u25cf")
        suffix = ("   " + " ".join(marks)) if marks else ""

        detail = self._subtitle(game)
        # Compact rows have room for one line; the details move to the tooltip.
        two_lines = bool(detail) and metrics().row_height >= _TWO_LINE_HEIGHT
        item.setText(f"{game.name}{suffix}\n{detail}" if two_lines else f"{game.name}{suffix}")

        if not game.executable_exists:
            item.setForeground(QColor(palette().fg_muted))
            item.setToolTip(f"Executable not found:\n{game.executable}")
        else:
            item.setForeground(QColor(palette().fg))
            item.setToolTip(f"{game.name}\n{detail}" if detail else game.name)

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
