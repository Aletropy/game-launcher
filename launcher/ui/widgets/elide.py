"""A label that elides its text instead of clipping it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QWidget


class ElidingLabel(QLabel):
    """A QLabel that shortens long text with an ellipsis."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
    ) -> None:
        super().__init__(text, parent)
        self._mode = mode
        self._full_text = text
        self.setMinimumWidth(1)

    def setText(self, text: str) -> None:
        self._full_text = text
        super().setText(text)
        self.setToolTip("")
        self.update()

    def full_text(self) -> str:
        return self._full_text

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        metrics = painter.fontMetrics()
        rect = self.contentsRect()
        elided = metrics.elidedText(self._full_text, self._mode, rect.width())
        # Only offer a tooltip when something was actually hidden.
        self.setToolTip(self._full_text if elided != self._full_text else "")
        painter.drawText(rect, int(self.alignment()), elided)
