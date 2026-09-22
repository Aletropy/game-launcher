"""The artwork banner at the top of the detail panel.

Composed rather than stretched. A real banner (a wide hero image) fills
the area and is always scaled down, so it stays sharp. When a game only
has cover art, the cover is never blown up to fill a wide strip -- that
is what made banners blurry and badly cropped. Instead it is drawn at or
below its own resolution on the left, over a deliberately blurred and
darkened backdrop made from the same image, where softness is the point.
A transparent logo, if there is one, replaces the plain title.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from launcher.services.artwork import GRID, HERO, LOGO, ArtworkService
from launcher.ui.theme import DARK

_MARGIN = 20
_COVER_RADIUS = 8.0
#: Below this a hero is too narrow to fill the banner without upscaling
#: badly, so the cover composition is used instead.
_MIN_HERO_FILL = 0.7


@dataclass(frozen=True)
class _Key:
    game: str
    width: int
    height: int
    dpr: float


def _fill(image: QImage, width: int, height: int) -> QImage:
    """Scale to cover the area, then centre-crop to it."""
    scaled = image.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 3)  # favour the upper third
    return scaled.copy(x, y, width, height)


def blurred_backdrop(image: QImage, width: int, height: int) -> QImage:
    """A strong, smooth blur by shrinking hard and scaling back up.

    Two passes of down-then-up with smooth filtering read as a proper
    gaussian at this strength, at a fraction of the cost.
    """
    filled = _fill(image, width, height)
    for divisor in (22, 6):
        small = filled.scaled(
            max(1, width // divisor),
            max(1, height // divisor),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        filled = small.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return filled


def fit_no_upscale(image: QImage, max_w: float, max_h: float) -> tuple[float, float]:
    """Logical size that fits a box without ever enlarging the image."""
    scale = min(max_w / image.width(), max_h / image.height(), 1.0)
    return image.width() * scale, image.height() * scale


class HeroBanner(QWidget):
    """A game's banner artwork, logo or title, and a scrim."""

    def __init__(
        self,
        artwork: ArtworkService,
        parent: QWidget | None = None,
        height: int = 232,
    ) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self._key: str | None = None
        self._title = ""
        self._subtitle = ""
        self._cache_key: _Key | None = None
        self._cache: QPixmap | None = None
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_game(self, key: str | None, title: str = "", subtitle: str = "") -> None:
        self._key = key
        self._title = title or (key or "")
        self._subtitle = subtitle
        self._cache = None
        self.update()

    def refresh(self) -> None:
        """Re-read the artwork, e.g. after a download."""
        self._cache = None
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._cache = None
        super().resizeEvent(event)

    # -- composition ---------------------------------------------------

    def _compose(self, width: int, height: int, dpr: float) -> QPixmap:
        pixel_w, pixel_h = round(width * dpr), round(height * dpr)
        canvas = QPixmap(pixel_w, pixel_h)
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(QColor(DARK.bg))

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        key = self._key
        hero = self._artwork.image(key, HERO.name) if key else None
        cover = self._artwork.image(key, GRID.name) if key else None
        logo = self._artwork.image(key, LOGO.name) if key else None

        text_left = float(_MARGIN + 4)
        if hero is not None and hero.width() >= pixel_w * _MIN_HERO_FILL:
            # Wide enough to fill by scaling down: stays sharp.
            painter.drawImage(
                QRectF(0, 0, width, height), _fill(hero, pixel_w, pixel_h)
            )
        elif cover is not None or hero is not None:
            source = cover if cover is not None else hero
            assert source is not None
            painter.drawImage(
                QRectF(0, 0, width, height),
                blurred_backdrop(source, pixel_w, pixel_h),
            )
            painter.fillRect(0, 0, width, height, QColor(8, 10, 14, 150))
            if cover is not None:
                text_left = self._draw_cover(painter, cover, height, dpr)
        else:
            gradient = QLinearGradient(0, 0, 0, height)
            gradient.setColorAt(0, QColor(DARK.placeholder_top))
            gradient.setColorAt(1, QColor(DARK.placeholder_bottom))
            painter.fillRect(0, 0, width, height, gradient)

        self._draw_scrim(painter, width, height)
        self._draw_heading(painter, logo, text_left, width, height)
        painter.end()
        return canvas

    def _draw_cover(
        self, painter: QPainter, cover: QImage, height: int, dpr: float
    ) -> float:
        """Draw the cover sharp on the left. Returns where text may start."""
        box_h = height - 2 * _MARGIN
        # Never enlarge: a 266x400 cover shown 184px tall is a downscale.
        w, h = fit_no_upscale(cover, box_h * 10, min(box_h, cover.height() / dpr))
        x, y = float(_MARGIN), (height - h) / 2

        # A soft shadow, then the cover clipped to rounded corners.
        for spread, alpha in ((10, 26), (6, 40), (3, 60)):
            shadow = QPainterPath()
            shadow.addRoundedRect(
                QRectF(x - spread / 2, y + spread / 2, w + spread, h + spread / 2),
                _COVER_RADIUS + spread / 2,
                _COVER_RADIUS + spread / 2,
            )
            painter.fillPath(shadow, QColor(0, 0, 0, alpha))

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(x, y, w, h), _COVER_RADIUS, _COVER_RADIUS)
        painter.save()
        painter.setClipPath(clip)
        painter.drawImage(
            QRectF(x, y, w, h),
            cover.scaled(
                round(w * dpr),
                round(h * dpr),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
        )
        painter.restore()
        painter.setPen(QColor(255, 255, 255, 40))
        painter.drawPath(clip)
        return x + w + 28

    @staticmethod
    def _draw_scrim(painter: QPainter, width: int, height: int) -> None:
        """Darken the bottom so the heading reads over any artwork."""
        scrim = QLinearGradient(0, height, 0, height * 0.35)
        scrim.setColorAt(0.0, QColor(0, 0, 0, 200))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, width, height, scrim)

    def _draw_heading(
        self,
        painter: QPainter,
        logo: QImage | None,
        left: float,
        width: int,
        height: int,
    ) -> None:
        """The logo if there is one, otherwise the title and a subtitle."""
        available = max(80.0, width - left - _MARGIN)
        dpr = painter.device().devicePixelRatio() if painter.device() else 1.0

        if logo is not None:
            w, h = fit_no_upscale(logo, min(available, 420), 96)
            w, h = min(w, logo.width() / dpr), min(h, logo.height() / dpr)
            painter.drawImage(QRectF(left, height - _MARGIN - h, w, h), logo)
            return

        if not self._title:
            return

        title_font = QFont(self.font())
        title_font.setPointSizeF(max(title_font.pointSizeF(), 10) * 2.1)
        title_font.setBold(True)
        painter.setFont(title_font)
        metrics = painter.fontMetrics()
        title = metrics.elidedText(
            self._title, Qt.TextElideMode.ElideRight, int(available)
        )

        baseline = height - _MARGIN - (22 if self._subtitle else 0)
        painter.setPen(QColor(0, 0, 0, 150))
        painter.drawText(int(left) + 1, int(baseline) + 2, title)
        painter.setPen(QColor(DARK.fg_bright))
        painter.drawText(int(left), int(baseline), title)

        if self._subtitle:
            sub_font = QFont(self.font())
            sub_font.setPointSizeF(max(sub_font.pointSizeF(), 9) * 1.05)
            painter.setFont(sub_font)
            painter.setPen(QColor(DARK.fg))
            painter.drawText(
                int(left), int(height - _MARGIN), self._subtitle
            )

    # -- painting ------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(800, self.height())

    def paintEvent(self, event: QPaintEvent) -> None:
        dpr = self.devicePixelRatioF()
        key = _Key(self._key or "", self.width(), self.height(), dpr)
        if self._cache is None or self._cache_key != key:
            self._cache = self._compose(self.width(), self.height(), dpr)
            self._cache_key = key
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)
