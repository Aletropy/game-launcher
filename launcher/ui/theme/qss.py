"""The application stylesheet, built from design tokens.

QSS is full of literal braces, so this uses ``string.Template`` with
``$name`` placeholders rather than str.format or an f-string.
"""

from __future__ import annotations

from dataclasses import asdict
from string import Template

from launcher.ui.theme.tokens import DARK, METRICS, Metrics, Palette

_TEMPLATE = Template("""
QMainWindow, QDialog {
    background-color: $bg;
}

QWidget#libraryPage, QWidget#journalBody, QScrollArea#journal {
    background-color: $bg;
}

QTabWidget::pane {
    border: 1px solid $border;
    background-color: $bg;
}

QTabBar::tab {
    background-color: $surface;
    color: $fg_muted;
    padding: 8px 20px;
    border: 1px solid $border;
    border-bottom: none;
    border-top-left-radius: ${radius}px;
    border-top-right-radius: ${radius}px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: $bg;
    color: $fg_bright;
    border-bottom: 2px solid $accent;
}

QTabBar::tab:hover:!selected {
    background-color: $hover;
    color: $fg;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

/* The viewport does not inherit the scroll area's transparency, so without
   this the library shows the platform's default light grey. */
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 10px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background-color: $border;
    border-radius: 3px;
    min-width: 30px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page, QScrollBar::sub-page {
    width: 0;
    background: none;
}

QScrollBar::handle:vertical {
    background-color: $border;
    border-radius: 3px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: $border_hover;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit#input {
    background-color: $surface;
    color: $fg_bright;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: ${button_padding}px 10px;
    selection-background-color: $accent;
    selection-color: $on_accent;
    font-size: ${font_md}px;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: $accent;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: url("$icon_down");
    width: 12px;
    height: 12px;
}

QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 20px;
    border: none;
    background: transparent;
}

QSpinBox::up-button {
    subcontrol-position: top right;
}

QSpinBox::down-button {
    subcontrol-position: bottom right;
}

QSpinBox::up-arrow {
    image: url("$icon_up");
    width: 10px;
    height: 10px;
}

QSpinBox::down-arrow {
    image: url("$icon_down");
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: $surface;
    color: $fg_bright;
    border: 1px solid $border;
    selection-background-color: $accent;
}

QToolTip {
    background-color: $surface;
    color: $fg_bright;
    border: 1px solid $border;
    padding: 5px 8px;
}

QPushButton {
    background-color: $raised;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: ${button_padding}px 14px;
    font-size: ${font_md}px;
}

QPushButton:hover {
    background-color: $border;
    border-color: $border_hover;
}

QPushButton:pressed {
    background-color: $pressed;
}

QPushButton:disabled {
    background-color: $raised;
    color: $fg_disabled;
    border-color: $border;
}

QPushButton#playButton {
    background-color: $accent;
    color: $on_accent;
    border: none;
    border-radius: ${radius}px;
    padding: 8px 20px;
    font-size: ${font_md}px;
    font-weight: bold;
}

QPushButton#playButton:hover {
    background-color: $accent_hover;
}

QPushButton#playButton:pressed {
    background-color: $accent_pressed;
}

QPushButton#playButton:disabled {
    background-color: $raised;
    color: $fg_disabled;
}

QPushButton#dangerButton {
    color: $danger;
    border-color: $danger;
}

QPushButton#dangerButton:hover {
    color: $on_accent;
    background-color: $danger;
}

QPushButton#dangerButton:disabled {
    color: $fg_disabled;
    border-color: $border;
    background-color: $raised;
}

QPushButton#favButton {
    background: transparent;
    border: none;
    color: $fg_muted;
    font-size: 18px;
    padding: 2px;
}

QPushButton#favButton:hover {
    background-color: $hover;
    border-radius: ${radius_sm}px;
}

QPushButton#favButton[favorite="true"] {
    color: $favorite;
}

QLabel {
    color: $fg_bright;
}

QLabel#gameNameLabel {
    font-size: ${font_md}px;
    font-weight: bold;
    color: $fg_bright;
}

QLabel#sectionTitle {
    font-size: ${font_lg}px;
    font-weight: bold;
    color: $fg_bright;
}

QLabel#subtitleLabel, QLabel#hintLabel {
    font-size: ${font_xs}px;
    color: $fg_muted;
}

QLabel#placeholderLabel {
    font-size: ${font_display}px;
    font-weight: bold;
    color: $link;
    border-top-left-radius: ${radius_lg}px;
    border-top-right-radius: ${radius_lg}px;
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $placeholder_top, stop: 1 $placeholder_bottom
    );
}

QLabel#heroLabel {
    background-color: $raised;
    border-top-left-radius: ${radius_lg}px;
    border-top-right-radius: ${radius_lg}px;
}

QLabel#emptyLabel {
    font-size: ${font_lg}px;
    color: $fg_muted;
}

QFrame#topBar {
    background-color: $surface;
    border-bottom: 1px solid $border;
}

QFrame#gameCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
}

QFrame#gameCard:hover {
    border-color: $link;
}

QFrame#thumbTile QLabel {
    background-color: $raised;
    border-radius: ${radius}px;
}

QPlainTextEdit {
    background-color: $bg;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    font-family: 'Monospace', 'Courier New', monospace;
    font-size: ${font_sm}px;
    padding: 6px;
}

QCheckBox {
    color: $fg;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $border;
    border-radius: 3px;
    background-color: $surface;
}

QCheckBox::indicator:hover {
    border-color: $border_hover;
}

QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
    image: url("$icon_check");
}

QCheckBox:disabled, QRadioButton:disabled {
    color: $fg_disabled;
}

QRadioButton {
    color: $fg;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid $border;
    /* Half the 16px border box, or Qt draws a rounded square. */
    border-radius: 8px;
    background-color: $surface;
}

QRadioButton::indicator:hover {
    border-color: $border_hover;
}

QRadioButton::indicator:checked {
    border: 1px solid $accent;
    background-color: qradialgradient(
        cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 $on_accent, stop: 0.32 $on_accent,
        stop: 0.42 $accent, stop: 1 $accent
    );
}

QTreeWidget, QTreeView, QListView {
    background-color: $surface;
    alternate-background-color: $surface;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    outline: none;
}

QTreeWidget::item, QTreeView::item {
    padding: 4px 6px;
    border: none;
}

QTreeWidget::item:hover, QTreeView::item:hover {
    background-color: $hover;
}

QTreeWidget::item:selected, QTreeView::item:selected {
    background-color: $raised;
    color: $fg_bright;
}

QHeaderView::section {
    background-color: $raised;
    color: $fg_muted;
    padding: 5px 8px;
    border: none;
    border-right: 1px solid $border;
    border-bottom: 1px solid $border;
}

QHeaderView::section:last {
    border-right: none;
}

QWidget#sidebar {
    background-color: $surface;
    border-right: 1px solid $border;
}

QListWidget#gameList {
    background-color: transparent;
    border: none;
    outline: none;
}

QListWidget#gameList::item {
    color: $fg;
    border-radius: ${radius}px;
    padding: 4px 8px;
    margin: 1px 0;
}

QListWidget#gameList::item:hover {
    background-color: $hover;
}

QListWidget#gameList::item:selected {
    background-color: $selection;
    color: $fg_bright;
}

QWidget#detailPanel, QWidget#detailBody {
    background-color: $bg;
}

QLabel#detailTitle {
    font-size: ${font_xl}px;
    font-weight: bold;
    color: $fg_bright;
}

QLabel#infoValue {
    color: $fg;
    font-size: ${font_sm}px;
}

QLabel#warningLabel {
    color: $favorite;
    font-size: ${font_sm}px;
}

QPushButton#viewToggle {
    padding: 6px 16px;
}

QPushButton#viewToggle:checked {
    background-color: $accent;
    color: $on_accent;
    border-color: $accent;
}

QLabel#journalSection {
    color: $fg_muted;
    font-size: ${font_xs}px;
    font-weight: bold;
    letter-spacing: 1px;
    padding-top: 4px;
}

QFrame#statTile, QFrame#journalCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
}

QLabel#statCaption {
    color: $fg_muted;
    font-size: ${font_sm}px;
}

QLabel#statValue {
    color: $fg_bright;
    font-size: ${font_stat}px;
    font-weight: bold;
}

QScrollArea#shelf, QScrollArea#shelf > QWidget > QWidget {
    background-color: transparent;
}

QToolButton#filterButton, QToolButton#favFirstButton {
    background-color: $raised;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 5px 10px;
    font-size: ${font_sm}px;
}

QToolButton#filterButton:hover, QToolButton#favFirstButton:hover {
    border-color: $border_hover;
}

QToolButton#filterButton[active="true"], QToolButton#favFirstButton:checked {
    color: $on_accent;
    background-color: $accent;
    border-color: $accent;
}

QToolButton#filterButton::menu-indicator {
    image: none;
    width: 0;
}

QPushButton#segment {
    border-radius: 0;
    padding: 5px 14px;
    margin: 0;
    color: $fg_muted;
}

QPushButton#segment[position="first"] {
    border-top-left-radius: ${radius}px;
    border-bottom-left-radius: ${radius}px;
}

QPushButton#segment[position="last"] {
    border-top-right-radius: ${radius}px;
    border-bottom-right-radius: ${radius}px;
}

QPushButton#segment[position="middle"], QPushButton#segment[position="last"] {
    border-left: none;
}

QPushButton#segment:checked {
    background-color: $selection;
    color: $fg_bright;
    border-color: $accent;
}

QToolButton#swatch {
    background: transparent;
    border: none;
}

QPushButton#stepPill {
    background-color: transparent;
    color: $fg_muted;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 5px 14px;
}

QPushButton#stepPill:hover {
    color: $fg_bright;
    border-color: $border_hover;
}

QPushButton#stepPill:checked {
    background-color: $accent;
    border-color: $accent;
    color: $on_accent;
    font-weight: bold;
}

QFrame#previewPanel {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
}

QListWidget#artGrid {
    background-color: $bg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 6px;
}

QListWidget#artGrid::item {
    color: $fg_muted;
    border: 2px solid transparent;
    border-radius: ${radius}px;
    padding: 4px;
}

QListWidget#artGrid::item:hover {
    background-color: $hover;
}

QListWidget#artGrid::item:selected {
    background-color: $selection;
    border-color: $accent;
    color: $fg_bright;
}

QLabel#reviewThumb {
    background-color: $raised;
    border-radius: ${radius_sm}px;
    color: $fg_muted;
}

QToolButton#moreButton {
    background-color: $raised;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 0 10px;
    font-size: ${font_lg}px;
}

QToolButton#moreButton:hover {
    background-color: $border;
    border-color: $border_hover;
}

QToolButton#moreButton::menu-indicator {
    image: none;
    width: 0;
}

QMenu {
    background-color: $surface;
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 22px 6px 12px;
    border-radius: ${radius_sm}px;
}

QMenu::item:selected {
    background-color: $raised;
    color: $fg_bright;
}

QMenu::separator {
    height: 1px;
    background: $border;
    margin: 4px 6px;
}

QToolButton#sectionToggle {
    background: transparent;
    border: none;
    color: $fg_bright;
    font-size: ${font_lg}px;
    font-weight: bold;
    padding: 4px 0;
}

QToolButton#sectionToggle:hover {
    color: $link;
}

QSplitter::handle {
    background-color: $border;
}

QGroupBox {
    color: $fg;
    border: 1px solid $border;
    border-radius: ${radius}px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
""")


def build_stylesheet(
    palette: Palette = DARK,
    metrics: Metrics = METRICS,
    *,
    icons: dict[str, str] | None = None,
    button_padding: int = 6,
) -> str:
    """Render the stylesheet for the given tokens.

    Without icons (e.g. in a test) the indicator images point nowhere,
    which Qt ignores.
    """
    values = {**asdict(palette), **asdict(metrics)}
    if not values["selection"]:
        values["selection"] = palette.raised
    values.update(
        icons or {"icon_check": "", "icon_down": "", "icon_up": ""},
        button_padding=button_padding,
    )
    return _TEMPLATE.substitute(values)
