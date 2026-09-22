"""A miniature launcher drawn in any palette, for designing themes.

Built from real widgets with the real stylesheet, scoped to this frame,
so what it shows is what the theme will look like, not an imitation.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.ui.theme import build_stylesheet, metrics
from launcher.ui.theme.appearance import current, indicator_icons
from launcher.ui.theme.tokens import Palette
from launcher.ui.widgets.sidebar import letter_tile

_GAMES = (
    ("Hollow Knight", "42.1h  ·  today"),
    ("Celeste", "18.4h  ·  last week"),
    ("Hades II", "63.0h  ·  2 days ago"),
    ("Outer Wilds", "never played"),
)


class _Banner(QWidget):
    """The banner as it looks with no artwork: the placeholder colours."""

    def __init__(self, colours: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colours = colours
        self.setFixedHeight(96)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, QColor(self.colours.placeholder_top))
        gradient.setColorAt(1, QColor(self.colours.placeholder_bottom))
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, gradient)
        scrim = QLinearGradient(0, rect.height(), 0, rect.height() * 0.3)
        scrim.setColorAt(0, QColor(0, 0, 0, 170))
        scrim.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillPath(path, scrim)
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(22)
        painter.setFont(font)
        painter.setPen(QColor("#f4f6f8"))
        painter.drawText(QRectF(16, 0, rect.width(), rect.height() - 26),
                         int(Qt.AlignmentFlag.AlignBottom), "Hollow Knight")
        font.setBold(False)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#d5dbe1"))
        painter.drawText(QRectF(16, 0, rect.width(), rect.height() - 10),
                         int(Qt.AlignmentFlag.AlignBottom), "42.1h  ·  today")


class _Heat(QWidget):
    """A strip of the Journal's heatmap, in the accent colour."""

    _LEVELS = (0, 2, 4, 1, 0, 3, 4, 2, 0, 1, 3, 2, 4, 4, 1, 0, 2, 3, 1, 4, 2, 0, 3, 1)

    def __init__(self, colours: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colours = colours
        self.setFixedHeight(16)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        empty, accent = QColor(self.colours.raised), QColor(self.colours.accent_hover)
        x = 0.0
        for level in self._LEVELS:
            if x + 13 > self.width():
                break
            t = 0.0 if level == 0 else 0.28 + 0.18 * level
            colour = QColor(
                round(empty.red() + (accent.red() - empty.red()) * t),
                round(empty.green() + (accent.green() - empty.green()) * t),
                round(empty.blue() + (accent.blue() - empty.blue()) * t),
            )
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, 1, 13, 13), 3, 3)
            painter.fillPath(path, colour)
            x += 16


class ThemePreview(QFrame):
    """The launcher in miniature, in whatever palette it is given."""

    def __init__(self, colours: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("themePreview")
        self.setMinimumSize(QSize(540, 420))
        self._colours = colours
        self._build()
        self.set_palette(colours)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("topBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(10, 8, 10, 8)
        bar_layout.setSpacing(6)
        for label, checked in (("Library", True), ("Journal", False)):
            button = QPushButton(label)
            button.setObjectName("viewToggle")
            button.setCheckable(True)
            button.setChecked(checked)
            bar_layout.addWidget(button)
        bar_layout.addStretch()
        settings = QPushButton("Settings")
        bar_layout.addWidget(settings)
        outer.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(210)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_layout.setSpacing(6)
        search_row = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Search games…")
        search_row.addWidget(search)
        filters = QToolButton()
        filters.setObjectName("filterButton")
        filters.setText("Filters · 1")
        filters.setProperty("active", "true")
        search_row.addWidget(filters)
        side_layout.addLayout(search_row)
        self._list = QListWidget()
        self._list.setObjectName("gameList")
        self._list.setIconSize(QSize(28, 28))
        for name, detail in _GAMES:
            item = QListWidgetItem(f"{name}\n{detail}")
            item.setSizeHint(QSize(0, 50))
            self._list.addItem(item)
        self._list.setCurrentRow(0)
        side_layout.addWidget(self._list, stretch=1)
        body.addWidget(side)

        main = QWidget()
        main.setObjectName("detailPanel")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)
        self._banner = _Banner(self._colours)
        main_layout.addWidget(self._banner)
        buttons = QHBoxLayout()
        play = QPushButton("▶  Play")
        play.setObjectName("playButton")
        buttons.addWidget(play)
        buttons.addWidget(QPushButton("Edit"))
        danger = QPushButton("Remove")
        danger.setObjectName("dangerButton")
        buttons.addStretch()
        buttons.addWidget(danger)
        main_layout.addLayout(buttons)

        info = QHBoxLayout()
        caption = QLabel("Prefix")
        caption.setObjectName("hintLabel")
        value = QLabel("Shared (Prefix)")
        value.setObjectName("infoValue")
        info.addWidget(caption)
        info.addWidget(value)
        info.addStretch()
        main_layout.addLayout(info)

        controls = QHBoxLayout()
        check = QCheckBox("Favourite")
        check.setChecked(True)
        controls.addWidget(check)
        radio = QRadioButton("Own prefix")
        radio.setChecked(True)
        controls.addWidget(radio)
        combo = QComboBox()
        combo.addItems(["Last played", "Most played"])
        controls.addWidget(combo)
        controls.addStretch()
        main_layout.addLayout(controls)

        tile = QFrame()
        tile.setObjectName("statTile")
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(12, 8, 12, 10)
        tile_layout.setSpacing(4)
        tile_caption = QLabel("This week")
        tile_caption.setObjectName("statCaption")
        tile_value = QLabel("6h 40m")
        tile_value.setObjectName("statValue")
        tile_layout.addWidget(tile_caption)
        tile_layout.addWidget(tile_value)
        self._heat = _Heat(self._colours)
        tile_layout.addWidget(self._heat)
        link = QLabel("<a href='#'>Clear filters</a>")
        tile_layout.addWidget(link)
        main_layout.addWidget(tile)
        main_layout.addStretch()
        body.addWidget(main, stretch=1)
        outer.addLayout(body, stretch=1)

    def set_palette(self, colours: Palette) -> None:
        self._colours = colours
        look = current()
        sheet = build_stylesheet(
            colours,
            metrics(),
            icons=indicator_icons(colours),
            button_padding=look.button_padding,
        )
        # Scoped to this frame; the rest of the window keeps its theme.
        sheet += (
            f"QFrame#themePreview {{ background-color: {colours.bg};"
            f" border: 1px solid {colours.border}; border-radius: 10px; }}"
            f" QLabel {{ color: {colours.fg_bright}; background: transparent; }}"
            f" QLabel#hintLabel {{ color: {colours.fg_muted}; }}"
            f" QLabel#infoValue {{ color: {colours.fg}; }}"
            f" QLabel#statCaption {{ color: {colours.fg_muted}; }}"
        )
        self.setStyleSheet(sheet)
        for row in range(self._list.count()):
            item = self._list.item(row)
            name = _GAMES[row][0]
            item.setIcon(QIcon(letter_tile(name, QSize(28, 28), self.devicePixelRatioF(),
                                           light=colours.is_light)))
            item.setForeground(QColor(colours.fg))
        # Links follow the palette, not the stylesheet.
        qp = self.palette()
        qp.setColor(qp.ColorRole.Link, QColor(colours.link))
        self.setPalette(qp)
        for widget in (self._banner, self._heat):
            widget.colours = colours
            widget.update()
