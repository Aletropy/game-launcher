"""Where painted widgets get artwork from.

Normally the artwork store. The artwork wizard substitutes a PreviewArt,
so the real banner, cover tile and icon draw the images being chosen
before anything is saved.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap

from launcher.services.artwork import ArtworkService


class ArtSource(Protocol):
    def image(self, key: str, art: str) -> QImage | None: ...

    def pixmap(
        self,
        key: str,
        art: str,
        size: QSize,
        *,
        expand: bool = False,
        dpr: float = 1.0,
    ) -> QPixmap | None: ...


def scaled_pixmap(image: QImage, size: QSize, *, expand: bool, dpr: float) -> QPixmap:
    """Scale to a logical size at the screen's pixel ratio, as the store does."""
    dpr = max(1.0, dpr)
    physical = QSize(round(size.width() * dpr), round(size.height() * dpr))
    mode = (
        Qt.AspectRatioMode.KeepAspectRatioByExpanding
        if expand
        else Qt.AspectRatioMode.KeepAspectRatio
    )
    pixmap = QPixmap.fromImage(
        image.scaled(physical, mode, Qt.TransformationMode.SmoothTransformation)
    )
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class PreviewArt:
    """One game's artwork as it will be: chosen images over stored ones.

    An art type set to None previews as removed.
    """

    def __init__(self, base: ArtworkService, key: str) -> None:
        self._base = base
        self.key = key
        self._overrides: dict[str, QImage | None] = {}

    def set(self, art: str, image: QImage | None) -> None:
        self._overrides[art] = image

    def reset(self, art: str) -> None:
        """Back to what is stored."""
        self._overrides.pop(art, None)

    def image(self, key: str, art: str) -> QImage | None:
        if key == self.key and art in self._overrides:
            return self._overrides[art]
        return self._base.image(key, art)

    def pixmap(
        self,
        key: str,
        art: str,
        size: QSize,
        *,
        expand: bool = False,
        dpr: float = 1.0,
    ) -> QPixmap | None:
        if key == self.key and art in self._overrides:
            image = self._overrides[art]
            return None if image is None else scaled_pixmap(
                image, size, expand=expand, dpr=dpr
            )
        return self._base.pixmap(key, art, size, expand=expand, dpr=dpr)
