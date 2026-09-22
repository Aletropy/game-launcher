"""Shared dialog building blocks.

Settings, the game editor and the smaller dialogs all group fields into
titled cards with hint text and button rows. One implementation keeps
their object names (and therefore the stylesheet) identical.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """A titled group of related settings, with a form to fill."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        outer.addWidget(heading)
        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(self.form)


def hint(text: str) -> QLabel:
    """Small grey explanatory text."""
    label = QLabel(text)
    label.setObjectName("hintLabel")
    label.setWordWrap(True)
    return label


def button_row(*widgets: QWidget) -> QHBoxLayout:
    """Left-aligned buttons with a stretch at the end."""
    row = QHBoxLayout()
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch()
    return row
