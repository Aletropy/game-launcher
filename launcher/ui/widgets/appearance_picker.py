"""Controls for choosing how the launcher looks.

Theme cards are small paintings of the library in that theme, so a
theme can be judged before it is picked.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QMouseEvent, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.ui.dialogs.confirm import Answer, ask, warn
from launcher.ui.dialogs.theme_wizard import ThemeWizard
from launcher.ui.theme import ACCENTS, Appearance, Theme, palette
from launcher.ui.theme.appearance import CORNERS, DENSITIES, TEXT_SCALES
from launcher.ui.theme.custom import CustomThemeStore
from launcher.ui.theme.themes import all_themes, get_theme
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
        if self._theme.custom:
            tag = QRectF(mock.right() - 50, mock.top() + 6, 44, 16)
            path = QPainterPath()
            path.addRoundedRect(tag, 8, 8)
            painter.fillPath(path, QColor(0, 0, 0, 150))
            font.setBold(False)
            font.setPixelSize(10)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(tag, int(Qt.AlignmentFlag.AlignCenter), "Custom")


class NewThemeCard(QWidget):
    """The last card in the gallery: make a theme of your own."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = False
        self.setFixedSize(QSize(148, 112))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Create a theme, starting from the one in use")

    def enterEvent(self, event: object) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        current = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(3.5, 3.5, self.width() - 7, 79)
        pen = painter.pen()
        pen.setColor(QColor(current.accent if self._hover else current.border_hover))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawRoundedRect(box, 7, 7)
        big = painter.font()
        big.setPixelSize(30)
        painter.setFont(big)
        painter.setPen(QColor(current.accent if self._hover else current.fg_muted))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), "+")
        painter.setFont(self.font())
        painter.setPen(QColor(current.fg))
        painter.drawText(
            QRectF(0, 88, self.width(), 22), int(Qt.AlignmentFlag.AlignCenter), "New theme"
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

    def __init__(
        self,
        appearance: Appearance,
        store: CustomThemeStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._appearance = appearance
        self._store = store
        self._setup_ui()
        self.set_appearance(appearance)

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        return card, layout

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        theme_card, theme_layout = self._card("Theme")
        self._grid = QGridLayout()
        self._grid.setSpacing(10)
        self._cards: dict[str, ThemeCard] = {}
        theme_layout.addLayout(self._grid)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._new_btn = QPushButton("New theme…")
        self._new_btn.setToolTip("Start a theme from the one in use")
        self._new_btn.clicked.connect(self._new_theme)
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.clicked.connect(self._edit_theme)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("dangerButton")
        self._delete_btn.clicked.connect(self._delete_theme)
        self._import_btn = QPushButton("Import…")
        self._import_btn.clicked.connect(self._import_theme)
        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self._export_theme)
        for button in (self._new_btn, self._edit_btn, self._delete_btn):
            actions.addWidget(button)
        actions.addStretch()
        for button in (self._import_btn, self._export_btn):
            actions.addWidget(button)
        theme_layout.addLayout(actions)
        self._theme_buttons = (
            self._new_btn, self._edit_btn, self._delete_btn,
            self._import_btn, self._export_btn,
        )
        for button in self._theme_buttons:
            button.setVisible(self._store is not None)
        layout.addWidget(theme_card)
        self._rebuild_cards()

        layout_card, layout_layout = self._card("Layout & text")
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
        layout_layout.addLayout(form)
        layout.addWidget(layout_card)

        hint = QLabel("Changes show straight away. Cancel puts everything back.")
        hint.setObjectName("hintLabel")
        layout.addWidget(hint)

    # -- gallery -------------------------------------------------------

    def _rebuild_cards(self) -> None:
        """Lay out every theme, the user's included, then the New card."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        themes = list(all_themes().values())
        for index, theme in enumerate(themes):
            card = ThemeCard(theme)
            card.clicked.connect(lambda theme_id: self._change(theme=theme_id))
            self._grid.addWidget(card, index // 4, index % 4)
            self._cards[theme.id] = card
        if self._store is not None:
            new_card = NewThemeCard()
            new_card.clicked.connect(self._new_theme)
            self._grid.addWidget(new_card, len(themes) // 4, len(themes) % 4)

    def _update_theme_actions(self) -> None:
        custom = get_theme(self._appearance.theme).custom
        self._edit_btn.setEnabled(custom)
        self._delete_btn.setEnabled(custom)
        self._export_btn.setEnabled(custom)
        tip = "" if custom else "Built-in themes stay as they are; New theme starts from one."
        for button in (self._edit_btn, self._delete_btn):
            button.setToolTip(tip)

    def _use_theme(self, theme_id: str) -> None:
        """Switch to a theme and apply it.

        Always emits, even for the theme already in use: after an edit the
        id is the same but the colours are not.
        """
        self._rebuild_cards()
        updated = self._appearance.with_(theme=theme_id, accent="")
        self.set_appearance(updated)
        self.changed.emit(updated)

    def _new_theme(self) -> None:
        if self._store is None:
            return
        wizard = ThemeWizard(self._store, self, start_from=self._appearance.theme)
        if wizard.exec() and wizard.saved is not None:
            if wizard.use_now:
                self._use_theme(wizard.saved.id)
            else:
                self._rebuild_cards()
                self.set_appearance(self._appearance)

    def _edit_theme(self) -> None:
        theme = get_theme(self._appearance.theme)
        if self._store is None or not theme.custom:
            return
        wizard = ThemeWizard(self._store, self, editing=theme)
        if wizard.exec() and wizard.saved is not None:
            self._use_theme(wizard.saved.id)

    def _delete_theme(self) -> None:
        theme = get_theme(self._appearance.theme)
        if self._store is None or not theme.custom:
            return
        if ask(
            self, "Delete Theme", f"Delete the theme '{theme.label}'?", default=Answer.NO
        ) is not Answer.YES:
            return
        self._store.delete(theme.id)
        self._use_theme("midnight")

    def _import_theme(self) -> None:
        if self._store is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import a theme", "", "Themes (*.json)")
        if not path:
            return
        try:
            theme = self._store.import_file(Path(path))
        except (OSError, ValueError) as e:
            warn(self, "Import Theme", f"That file is not a theme this launcher can read:\n{e}")
            return
        self._use_theme(theme.id)

    def _export_theme(self) -> None:
        theme = get_theme(self._appearance.theme)
        if self._store is None or not theme.custom:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export theme", f"{theme.label}.json", "Themes (*.json)"
        )
        if not path:
            return
        try:
            self._store.export(theme, Path(path))
        except OSError as e:
            warn(self, "Export Theme", f"Could not write the file:\n{e}")

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
        self._theme_swatch.colour = get_theme(appearance.theme).palette.accent
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
        self._update_theme_actions()

    def _change(self, **changes: object) -> None:
        updated = self._appearance.with_(**changes)
        if updated == self._appearance:
            return
        self.set_appearance(updated)
        self.changed.emit(updated)

    def _pick_custom(self) -> None:
        own = get_theme(self._appearance.theme).palette.accent
        start = QColor(self._appearance.accent or own)
        colour = QColorDialog.getColor(start, self, "Accent colour")
        if colour.isValid():
            self._change(accent=colour.name())
        else:
            self.set_appearance(self._appearance)
