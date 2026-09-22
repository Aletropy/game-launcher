"""Controls for choosing how the launcher looks.

Theme cards are small paintings of the library in that theme, so a
theme can be judged before it is picked.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QMouseEvent, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.ui.theme import ACCENTS, THEMES, Appearance, Theme, palette
from launcher.ui.theme.appearance import CORNERS, DENSITIES, TEXT_SCALES
from launcher.ui.theme.tokens import Palette

#: Fonts worth offering first, when installed.
_PREFERRED_FONTS = (
    "Inter",
    "Noto Sans",
    "Roboto",
    "Fira Sans",
    "Open Sans",
    "Cantarell",
    "Ubuntu",
    "IBM Plex Sans",
    "Source Sans 3",
    "DejaVu Sans",
)


def _paint_mock(painter: QPainter, rect: QRectF, colours: Palette, radius: float) -> None:
    """A tiny library: sidebar, rows, banner and a Play button."""
    outer = QPainterPath()
    outer.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(outer)
    painter.fillRect(rect, QColor(colours.bg))

    side = QRectF(rect.left(), rect.top(), rect.width() * 0.34, rect.height())
    painter.fillRect(side, QColor(colours.surface))
    painter.fillRect(
        QRectF(side.right() - 1, side.top(), 1, side.height()), QColor(colours.border)
    )
    row_h = rect.height() / 7
    for i in range(5):
        y = rect.top() + row_h * (i + 0.8)
        row = QRectF(side.left() + 4, y, side.width() - 8, row_h * 0.8)
        if i == 1:
            sel = QPainterPath()
            sel.addRoundedRect(row, 2, 2)
            painter.fillPath(sel, QColor(colours.selection or colours.raised))
        dot = row.height() * 0.4
        painter.fillRect(
            QRectF(row.left() + 3, row.top() + row.height() * 0.3, dot + 1, dot),
            QColor(colours.fg_muted),
        )
        painter.fillRect(
            QRectF(row.left() + row.height() * 0.8, row.top() + row.height() * 0.38,
                   row.width() * (0.6 - 0.07 * i), 2),
            QColor(colours.fg_bright if i == 1 else colours.fg),
        )

    main = QRectF(side.right(), rect.top(), rect.right() - side.right(), rect.height())
    banner = QRectF(main.left(), main.top(), main.width(), main.height() * 0.42)
    painter.fillRect(banner, QColor(colours.placeholder_top))
    button = QRectF(main.left() + 8, banner.bottom() + 8, main.width() * 0.3, row_h * 0.9)
    path = QPainterPath()
    path.addRoundedRect(button, 2, 2)
    painter.fillPath(path, QColor(colours.accent))
    for i in range(3):
        width = main.width() * (0.7 - 0.15 * i)
        painter.fillRect(
            QRectF(main.left() + 8, button.bottom() + 8 + i * 7, width, 2),
            QColor(colours.fg_muted),
        )
    painter.restore()


class ThemeCard(QWidget):
    """A clickable preview of one theme."""

    clicked = Signal(str)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._palette = theme.palette
        self._selected = False
        self._hover = False
        self.setFixedSize(QSize(148, 112))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(theme.label)

    def set_palette(self, colours: Palette) -> None:
        """Show the card with the chosen accent, not just the theme's own."""
        self._palette = colours
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def enterEvent(self, event: object) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._theme.id)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mock = QRectF(3, 3, self.width() - 6, 80)
        _paint_mock(painter, mock, self._palette, 6)

        ring = QPainterPath()
        ring.addRoundedRect(mock.adjusted(-1.5, -1.5, 1.5, 1.5), 7, 7)
        current = palette()
        if self._selected:
            painter.setPen(QColor(current.accent))
            pen = painter.pen()
            pen.setWidthF(2.5)
            painter.setPen(pen)
        else:
            painter.setPen(QColor(current.border_hover if self._hover else current.border))
        painter.drawPath(ring)

        painter.setPen(QColor(current.fg_bright if self._selected else current.fg))
        font = painter.font()
        font.setBold(self._selected)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 88, self.width(), 22),
            int(Qt.AlignmentFlag.AlignCenter),
            ("✓ " if self._selected else "") + self._theme.label,
        )


class Swatch(QToolButton):
    """A round colour button."""

    def __init__(self, colour: str, tip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colour = colour
        self.setCheckable(True)
        self.setFixedSize(28, 28)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("swatch")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.colour))
        painter.drawEllipse(rect)
        if self.isChecked() or self.underMouse():
            pen = painter.pen()
            pen.setStyle(Qt.PenStyle.SolidLine)
            current = palette()
            ring = current.fg_bright if self.isChecked() else current.border_hover
            pen.setColor(QColor(ring))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3))


class Segmented(QWidget):
    """Mutually exclusive choices shown as joined buttons."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[object, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._values: list[object] = []
        for index, (value, label) in enumerate(options):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("segment")
            position = "first" if index == 0 else "last" if index == len(options) - 1 else "middle"
            button.setProperty("position", position)
            self._group.addButton(button, index)
            self._values.append(value)
            layout.addWidget(button)
        layout.addStretch()
        self._group.idClicked.connect(lambda i: self.changed.emit(self._values[i]))

    def set_value(self, value: object) -> None:
        if value in self._values:
            button = self._group.button(self._values.index(value))
            if button is not None:
                button.setChecked(True)


class AppearancePanel(QWidget):
    """Everything on the Appearance tab. Emits each change as it happens."""

    changed = Signal(object)

    def __init__(self, appearance: Appearance, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._appearance = appearance
        self._setup_ui()
        self.set_appearance(appearance)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        heading = QLabel("Theme")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        grid = QGridLayout()
        grid.setSpacing(10)
        self._cards: dict[str, ThemeCard] = {}
        for index, theme in enumerate(THEMES.values()):
            card = ThemeCard(theme)
            card.clicked.connect(lambda theme_id: self._change(theme=theme_id))
            grid.addWidget(card, index // 4, index % 4)
            self._cards[theme.id] = card
        layout.addLayout(grid)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        accents = QHBoxLayout()
        accents.setSpacing(2)
        self._accent_group = QButtonGroup(self)
        self._accent_group.setExclusive(True)
        self._theme_swatch = Swatch("#888888", "The theme's own accent")
        self._accent_group.addButton(self._theme_swatch)
        self._theme_swatch.clicked.connect(lambda: self._change(accent=""))
        accents.addWidget(self._theme_swatch)
        self._swatches: dict[str, Swatch] = {}
        for label, colour in ACCENTS.items():
            swatch = Swatch(colour, label)
            self._accent_group.addButton(swatch)
            swatch.clicked.connect(lambda _=False, c=colour: self._change(accent=c))
            accents.addWidget(swatch)
            self._swatches[colour] = swatch
        self._custom_swatch = Swatch("#ffffff", "Custom colour…")
        self._accent_group.addButton(self._custom_swatch)
        self._custom_swatch.clicked.connect(self._pick_custom)
        accents.addWidget(self._custom_swatch)
        custom_label = QLabel("Custom…")
        custom_label.setObjectName("hintLabel")
        accents.addWidget(custom_label)
        accents.addStretch()
        form.addRow("Accent", accents)

        self._corners = Segmented([(key, label) for key, (label, _) in CORNERS.items()])
        self._corners.changed.connect(lambda v: self._change(corners=v))
        form.addRow("Corners", self._corners)

        self._density = Segmented([(key, spec[0]) for key, spec in DENSITIES.items()])
        self._density.changed.connect(lambda v: self._change(density=v))
        form.addRow("Density", self._density)

        self._scale = Segmented([(s, f"{s}%") for s in TEXT_SCALES])
        self._scale.changed.connect(lambda v: self._change(text_scale=v))
        form.addRow("Text size", self._scale)

        self._font = QComboBox()
        self._font.addItem("System default", "")
        families = set(QFontDatabase.families())
        preferred = [f for f in _PREFERRED_FONTS if f in families]
        for family in preferred:
            self._font.addItem(family, family)
        if preferred:
            self._font.insertSeparator(self._font.count())
        for family in sorted(families - set(preferred), key=str.casefold):
            if not QFontDatabase.isPrivateFamily(family):
                self._font.addItem(family, family)
        self._font.currentIndexChanged.connect(
            lambda _: self._change(font=self._font.currentData() or "")
        )
        form.addRow("Font", self._font)
        layout.addLayout(form)

        hint = QLabel("Changes show straight away. Cancel puts everything back.")
        hint.setObjectName("hintLabel")
        layout.addWidget(hint)
        layout.addStretch()

    # -- state ---------------------------------------------------------

    @property
    def appearance(self) -> Appearance:
        return self._appearance

    def set_appearance(self, appearance: Appearance) -> None:
        """Show an appearance without emitting it."""
        self._appearance = appearance
        for theme_id, card in self._cards.items():
            card.set_selected(theme_id == appearance.theme)
            card.set_palette(appearance.with_(theme=theme_id).palette())
        self._theme_swatch.colour = THEMES[appearance.theme].palette.accent
        self._theme_swatch.update()
        accent = appearance.accent.lower()
        if not accent:
            self._theme_swatch.setChecked(True)
        elif accent in self._swatches:
            self._swatches[accent].setChecked(True)
        else:
            self._custom_swatch.colour = accent
            self._custom_swatch.setChecked(True)
            self._custom_swatch.update()
        self._corners.set_value(appearance.corners)
        self._density.set_value(appearance.density)
        self._scale.set_value(appearance.text_scale)
        self._font.blockSignals(True)
        index = self._font.findData(appearance.font)
        self._font.setCurrentIndex(max(0, index))
        self._font.blockSignals(False)

    def _change(self, **changes: object) -> None:
        updated = self._appearance.with_(**changes)
        if updated == self._appearance:
            return
        self.set_appearance(updated)
        self.changed.emit(updated)

    def _pick_custom(self) -> None:
        start = QColor(self._appearance.accent or THEMES[self._appearance.theme].palette.accent)
        colour = QColorDialog.getColor(start, self, "Accent colour")
        if colour.isValid():
            self._change(accent=colour.name())
        else:
            self.set_appearance(self._appearance)
