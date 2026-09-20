"""The large artwork banner at the top of the detail panel."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from launcher.services.artwork import GRID, HERO, ArtworkService
from launcher.ui.theme import DARK


class HeroBanner(QWidget):
    """Shows a game's banner artwork, or its initials when there is none.

    Painted rather than assembled from labels so the artwork can be
    cropped to fill and carry a gradient scrim behind the title.
    """

    def __init__(
        self,
        artwork: ArtworkService,
        parent: QWidget | None = None,
        height: int = 220,
    ) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self._key: str | None = None
        self._title = ""
        self._pixmap: QPixmap | None = None
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_game(self, key: str | None, title: str = "") -> None:
        self._key = key
        self._title = title or (key or "")
        self._pixmap = None
        self.update()

    def _resolve_pixmap(self) -> QPixmap | None:
        """Pick the best artwork available, preferring a wide banner."""
        if self._key is None:
            return None
        size = QSize(max(self.width(), 1), max(self.height(), 1))
        for art in (HERO.name, GRID.name):
            found = self._artwork.pixmap(self._key, art, size, expand=True)
            if found is not None:
                return found
        return None

    def resizeEvent(self, event: object) -> None:
        self._pixmap = None
        super().resizeEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.rect()

        if self._pixmap is None:
            self._pixmap = self._resolve_pixmap()

        if self._pixmap is not None and not self._pixmap.isNull():
            # Centre-crop the scaled artwork to fill the banner.
            source = QRect(0, 0, self._pixmap.width(), self._pixmap.height())
            source.moveCenter(
                QRect(0, 0, self._pixmap.width(), self._pixmap.height()).center()
            )
            x = (self._pixmap.width() - rect.width()) // 2
            y = (self._pixmap.height() - rect.height()) // 2
            painter.drawPixmap(
                rect, self._pixmap, QRect(x, y, rect.width(), rect.height())
            )
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, QColor(DARK.placeholder_top))
            gradient.setColorAt(1, QColor(DARK.placeholder_bottom))
            painter.fillRect(rect, gradient)

            initials = "".join(w[0] for w in self._title.split()[:2]).upper()
            font = QFont(self.font())
            font.setPointSize(42)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(DARK.link))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initials)

        # Scrim, so the title below stays readable over any artwork.
        scrim = QLinearGradient(rect.bottomLeft(), rect.topLeft())
        scrim.setColorAt(0.0, QColor(0, 0, 0, 220))
        scrim.setColorAt(0.5, QColor(0, 0, 0, 60))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, scrim)
