"""Making a theme: start somewhere, adjust colours, name it.

A live preview of the launcher follows every change, and a readability
check says whether text will still be legible before the theme is saved.
"""

from __future__ import annotations

import random
from dataclasses import replace

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.ui.dialogs.confirm import warn
from launcher.ui.theme import palette
from launcher.ui.theme.appearance import derive_selection
from launcher.ui.theme.custom import COLOUR_FIELDS, CustomThemeStore, check, generate
from launcher.ui.theme.themes import Theme, all_themes, get_theme
from launcher.ui.theme.tokens import Palette
from launcher.ui.widgets.theme_preview import ThemePreview

#: How the colour editor groups the palette: (group, [(field, label, hint)]).
COLOUR_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("Surfaces", (
        ("bg", "Background", "Behind everything"),
        ("surface", "Panels", "Sidebar, cards, fields"),
        ("raised", "Buttons", "Buttons and selected rows"),
        ("hover", "Hover", "Rows under the pointer"),
        ("pressed", "Pressed", "Buttons while pressed"),
        ("border", "Lines", "Borders and dividers"),
        ("border_hover", "Lines on hover", ""),
    )),
    ("Text", (
        ("fg_bright", "Headings", "Titles and selected text"),
        ("fg", "Text", "Most text"),
        ("fg_muted", "Secondary", "Hints and captions"),
        ("fg_disabled", "Disabled", ""),
    )),
    ("Accent", (
        ("accent", "Accent", "Play, toggles, selection"),
        ("accent_hover", "Accent on hover", ""),
        ("accent_pressed", "Accent pressed", ""),
        ("on_accent", "Text on accent", "Must stay readable"),
        ("link", "Links", ""),
    )),
    ("Details", (
        ("favorite", "Favourite star", ""),
        ("danger", "Danger", "Remove, Clear data"),
        ("placeholder_top", "Empty banner, top", "Games without art"),
        ("placeholder_bottom", "Empty banner, bottom", ""),
    )),
)
_STEPS = ("Start", "Colours", "Name")


class ColourButton(QToolButton):
    """A rounded swatch that opens a colour picker."""

    picked = Signal(str)

    def __init__(self, colour: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colour = colour
        self._title = title
        self.setObjectName("swatch")
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Choose {title.lower()}")
        self.clicked.connect(self._pick)

    def set_colour(self, colour: str) -> None:
        self.colour = colour
        self.update()

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.colour), self, self._title)
        if chosen.isValid():
            self.set_colour(chosen.name())
            self.picked.emit(chosen.name())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 6, 6)
        painter.fillPath(path, QColor(self.colour))
        painter.setPen(QColor(palette().border_hover if self.underMouse() else palette().border))
        painter.drawPath(path)


class _ColourRow(QWidget):
    """Label, swatch and hex field for one palette colour."""

    changed = Signal(str, str)

    def __init__(self, field: str, label: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(label)
        text.addWidget(name)
        if hint:
            sub = QLabel(hint)
            sub.setObjectName("hintLabel")
            text.addWidget(sub)
        layout.addLayout(text, stretch=1)
        self.swatch = ColourButton("#000000", label)
        self.swatch.picked.connect(self._picked)
        layout.addWidget(self.swatch)
        self.hex = QLineEdit()
        self.hex.setFixedWidth(92)
        self.hex.setMaxLength(9)
        self.hex.editingFinished.connect(self._typed)
        layout.addWidget(self.hex)

    def set_colour(self, colour: str) -> None:
        self.swatch.set_colour(colour)
        if self.hex.text() != colour:
            self.hex.setText(colour)

    def _picked(self, colour: str) -> None:
        self.hex.setText(colour)
        self.changed.emit(self.field, colour)

    def _typed(self) -> None:
        text = self.hex.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        if QColor.isValidColorName(text):
            colour = QColor(text).name()
            self.set_colour(colour)
            self.changed.emit(self.field, colour)
        else:
            self.hex.setText(self.swatch.colour)


class _Checks(QFrame):
    """Readability of the pairings that matter, as it stands."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        title = QLabel("Readability")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(3)
        self._grid.setColumnMinimumWidth(0, 16)
        self._grid.setColumnStretch(1, 1)
        layout.addLayout(self._grid)
        self._rows: list[tuple[QLabel, QLabel]] = []

    def update_for(self, colours: Palette) -> int:
        """Show the checks; returns how many fail."""
        results = check(colours)
        while len(self._rows) < len(results):
            mark, text = QLabel(), QLabel()
            text.setObjectName("hintLabel")
            row = len(self._rows)
            self._grid.addWidget(mark, row, 0)
            self._grid.addWidget(text, row, 1)
            self._rows.append((mark, text))
        failing = 0
        for (mark, text), (label, ratio, minimum) in zip(self._rows, results, strict=False):
            ok = ratio >= minimum
            failing += not ok
            mark.setText("✓" if ok else "⚠")
            mark.setObjectName("checkOk" if ok else "checkLow")
            mark.style().unpolish(mark)
            mark.style().polish(mark)
            text.setText(f"{label}: {ratio:.1f}:1" + ("" if ok else f" (aim for {minimum:g}:1)"))
        return failing


class ThemeWizard(QDialog):
    """Create a theme, or edit one the user made."""

    def __init__(
        self,
        store: CustomThemeStore,
        parent: QWidget | None = None,
        *,
        start_from: str = "",
        editing: Theme | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._editing = editing
        #: The saved theme, once Save succeeds.
        self.saved: Theme | None = None
        self._colours: Palette = (
            editing.palette if editing else get_theme(start_from or "midnight").palette
        )
        self._rows: dict[str, _ColourRow] = {}

        self.setWindowTitle("Edit Theme" if editing else "Create a Theme")
        self.resize(1160, 720)
        self._setup_ui()
        self._set_colours(self._colours)
        self._go(1 if editing else 0)

    # -- layout --------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(12)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self._step_group = QButtonGroup(self)
        for index, title in enumerate(_STEPS):
            button = QPushButton(f"{index + 1}  {title}")
            button.setObjectName("stepPill")
            button.setCheckable(True)
            self._step_group.addButton(button, index)
            steps.addWidget(button)
        steps.addStretch()
        self._step_group.idClicked.connect(self._go)
        outer.addLayout(steps)

        body = QHBoxLayout()
        body.setSpacing(18)
        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_start())
        self._pages.addWidget(self._build_colours())
        self._pages.addWidget(self._build_name())
        self._pages.setMinimumWidth(460)
        body.addWidget(self._pages, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(10)
        caption = QLabel("PREVIEW")
        caption.setObjectName("journalSection")
        right.addWidget(caption)
        self._preview = ThemePreview(self._colours)
        right.addWidget(self._preview, stretch=1)
        self._checks = _Checks()
        right.addWidget(self._checks)
        body.addLayout(right, stretch=1)
        outer.addLayout(body, stretch=1)

        footer = QHBoxLayout()
        self._status = QLabel()
        self._status.setObjectName("hintLabel")
        footer.addWidget(self._status, stretch=1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self._back = QPushButton("Back")
        self._back.clicked.connect(lambda: self._go(self._pages.currentIndex() - 1))
        footer.addWidget(self._back)
        self._next = QPushButton("Next")
        self._next.clicked.connect(lambda: self._go(self._pages.currentIndex() + 1))
        footer.addWidget(self._next)
        self._save_btn = QPushButton("Save theme")
        self._save_btn.setObjectName("playButton")
        self._save_btn.clicked.connect(self._save)
        footer.addWidget(self._save_btn)
        outer.addLayout(footer)

    @staticmethod
    def _heading(title: str, text: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(4)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        layout.addWidget(label)
        hint = QLabel(text)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return layout

    def _build_start(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(
            self._heading(
                "Where to start",
                "Begin from a theme you like, or give two colours and let the "
                "rest be worked out. Everything can be adjusted next.",
            )
        )

        self._start_group = QButtonGroup(self)
        from_theme = QFrame()
        from_theme.setObjectName("settingsCard")
        box = QVBoxLayout(from_theme)
        box.setContentsMargins(14, 12, 14, 14)
        self._from_theme = QRadioButton("Start from a theme")
        self._start_group.addButton(self._from_theme)
        box.addWidget(self._from_theme)
        self._base_combo = QComboBox()
        for theme in all_themes().values():
            self._base_combo.addItem(theme.label, theme.id)
        index = self._base_combo.findData(palette_theme_id(self._colours))
        self._base_combo.setCurrentIndex(max(0, index))
        self._base_combo.currentIndexChanged.connect(lambda _: self._restart())
        box.addWidget(self._base_combo)
        layout.addWidget(from_theme)

        generated = QFrame()
        generated.setObjectName("settingsCard")
        form = QFormLayout(generated)
        form.setContentsMargins(14, 12, 14, 14)
        form.setSpacing(10)
        self._from_colours = QRadioButton("Generate from two colours")
        self._start_group.addButton(self._from_colours)
        form.addRow(self._from_colours)
        self._bg_button = ColourButton("#15171f", "Background")
        self._bg_button.picked.connect(lambda _c: self._choose_generate())
        form.addRow("Background", self._bg_button)
        self._accent_button = ColourButton("#7c5cff", "Accent")
        self._accent_button.picked.connect(lambda _c: self._choose_generate())
        form.addRow("Accent", self._accent_button)
        surprise = QPushButton("Surprise me")
        surprise.setToolTip("A random pairing that still reads well")
        surprise.clicked.connect(self._surprise)
        form.addRow(surprise)
        layout.addWidget(generated)

        self._from_theme.setChecked(True)
        self._start_group.buttonToggled.connect(self._start_toggled)
        layout.addWidget(self._hint_label("Changing this replaces the colours so far."))
        layout.addStretch()
        return page

    @staticmethod
    def _hint_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        return label

    def _build_colours(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        layout.addLayout(
            self._heading(
                "Colours",
                "Pick a swatch or type a hex value. The preview and the "
                "readability check update as you go.",
            )
        )
        for group, rows in COLOUR_GROUPS:
            card = QFrame()
            card.setObjectName("settingsCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 14)
            card_layout.setSpacing(8)
            title = QLabel(group)
            title.setObjectName("cardTitle")
            card_layout.addWidget(title)
            for field, label, hint in rows:
                row = _ColourRow(field, label, hint)
                row.changed.connect(self._colour_changed)
                card_layout.addWidget(row)
                self._rows[field] = row
            layout.addWidget(card)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_name(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(
            self._heading("Name it", "Themes are saved as small files you can share.")
        )
        card = QFrame()
        card.setObjectName("settingsCard")
        form = QFormLayout(card)
        form.setContentsMargins(14, 12, 14, 14)
        form.setSpacing(10)
        self._name = QLineEdit(self._editing.label if self._editing else "")
        self._name.setPlaceholderText("My theme")
        self._name.textChanged.connect(lambda _t: self._update_footer())
        form.addRow("Name", self._name)
        self._light = QCheckBox("Light theme")
        self._light.setToolTip("Tunes a few details, like placeholder icons, for light backgrounds")
        self._light.toggled.connect(self._light_toggled)
        form.addRow(self._light)
        self._use_now = QCheckBox("Use it now")
        self._use_now.setChecked(True)
        form.addRow(self._use_now)
        layout.addWidget(card)
        layout.addStretch()
        return page

    # -- state ---------------------------------------------------------

    @property
    def colours(self) -> Palette:
        return self._colours

    @property
    def use_now(self) -> bool:
        return self._use_now.isChecked()

    def _set_colours(self, colours: Palette) -> None:
        self._colours = replace(colours, selection="")
        for field, row in self._rows.items():
            row.set_colour(getattr(self._colours, field))
        self._light.blockSignals(True)
        self._light.setChecked(self._colours.is_light)
        self._light.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        shown = derive_selection(self._colours)
        self._preview.set_palette(shown)
        self._failing = self._checks.update_for(shown)
        self._update_footer()

    def _colour_changed(self, field: str, colour: str) -> None:
        values = {name: getattr(self._colours, name) for name in COLOUR_FIELDS}
        values[field] = colour
        self._colours = replace(self._colours, **values)
        self._refresh()

    def _light_toggled(self, light: bool) -> None:
        self._colours = replace(self._colours, is_light=light)
        self._refresh()

    def _start_toggled(self, _button: QRadioButton, checked: bool) -> None:
        if checked:
            self._restart()

    def _restart(self) -> None:
        if self._from_theme.isChecked():
            self._set_colours(get_theme(str(self._base_combo.currentData())).palette)
        else:
            self._set_colours(generate(self._bg_button.colour, self._accent_button.colour))

    def _choose_generate(self) -> None:
        if self._from_colours.isChecked():
            self._restart()
        else:
            self._from_colours.setChecked(True)

    def _surprise(self) -> None:
        hue = random.random()  # noqa: S311 - colours, not secrets
        light = random.random() < 0.25  # noqa: S311
        background = QColor.fromHslF(hue, 0.35, 0.95 if light else 0.1).name()
        accent_hue = (hue + random.choice((0.33, 0.5, 0.58, 0.08))) % 1.0  # noqa: S311
        accent = QColor.fromHslF(accent_hue, 0.75, 0.45 if light else 0.62).name()
        self._bg_button.set_colour(background)
        self._accent_button.set_colour(accent)
        self._choose_generate()

    # -- navigation ----------------------------------------------------

    def _go(self, index: int) -> None:
        index = max(0, min(index, self._pages.count() - 1))
        self._pages.setCurrentIndex(index)
        button = self._step_group.button(index)
        if button is not None:
            button.setChecked(True)
        if index == 2 and not self._name.text().strip():
            self._name.setFocus()
        self._update_footer()

    def _update_footer(self) -> None:
        index = self._pages.currentIndex()
        self._back.setEnabled(index > 0)
        self._next.setVisible(index < self._pages.count() - 1)
        named = bool(self._name.text().strip())
        self._save_btn.setEnabled(named)
        failing = getattr(self, "_failing", 0)
        if failing:
            self._status.setText(f"⚠ {failing} pairing(s) may be hard to read.")
        elif not named:
            self._status.setText("Name the theme to save it.")
        else:
            self._status.setText("Everything reads well.")

    # -- saving --------------------------------------------------------

    def _save(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._go(2)
            return
        theme_id = self._editing.id if self._editing else self._store.new_id(name)
        theme = Theme(theme_id, name, replace(self._colours, selection=""), custom=True)
        try:
            self.saved = self._store.save(theme)
        except OSError as e:
            warn(self, "Save Theme", f"Could not save the theme:\n{e}")
            return
        self.accept()


def palette_theme_id(colours: Palette) -> str:
    """The id of the theme whose palette this is, or the default."""
    for theme in all_themes().values():
        if replace(theme.palette, selection="") == replace(colours, selection=""):
            return theme.id
    return "midnight"
