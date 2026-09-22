"""Art types, identifiers and image encoding.

Pure image work: nothing here knows where artwork is stored.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QImageWriter

#: Extensions an artwork file may have, in lookup order.
EXTENSIONS: Final = (".webp", ".png", ".jpg", ".jpeg", ".gif")


@dataclass(frozen=True)
class ArtSpec:
    """How one art type is stored."""

    name: str
    max_width: int
    max_height: int
    #: Format used when the image has no meaningful alpha channel.
    fmt: str = "webp"
    quality: int = 82


#: Portrait cover art. SteamGridDB serves these at 600x900, so that is
#: stored as-is: the old 400x600 cap meant any larger display upscaled.
GRID: Final = ArtSpec("grid", 600, 900, quality=88)
#: Wide banner. SteamGridDB heroes are 1920x620; keeping the full width
#: means the detail banner is always drawn by scaling down, never up.
HERO: Final = ArtSpec("hero", 1920, 620, quality=86)
#: Square icon for list rows.
ICON: Final = ArtSpec("icon", 256, 256, fmt="png", quality=-1)
#: Transparent title logo, drawn over the banner.
LOGO: Final = ArtSpec("logo", 960, 400, fmt="png", quality=-1)

SPECS: Final[dict[str, ArtSpec]] = {s.name: s for s in (GRID, HERO, ICON, LOGO)}

#: A banner is at least this much wider than tall (SteamGridDB: 3.1).
_BANNER_MIN_ASPECT = 1.6
#: A cover is at most this wide relative to its height (SteamGridDB: 0.67).
_COVER_MAX_ASPECT = 1.2


def classify(width: int, height: int, requested: str) -> str:
    """The art type an image really is, whatever it was requested as.

    Guards the banner: a portrait cover saved as a hero gets
    centre-cropped into a thin strip and stretched, which is exactly how
    blurry, badly fitting banners happened. Icons and logos are trusted,
    since their shapes vary.
    """
    if requested not in (GRID.name, HERO.name) or not height:
        return requested
    aspect = width / height
    if requested == HERO.name and aspect < _BANNER_MIN_ASPECT:
        return GRID.name
    if requested == GRID.name and aspect > _COVER_MAX_ASPECT * 1.5:
        return HERO.name
    return requested

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]


def slug(key: str) -> str:
    """Return a filesystem-safe identifier for a game key.

    Game names contain spaces, punctuation and accents. Plain names map to
    the obvious readable slug. When flattening would lose information --
    "Warhammer 40,000" and "Warhammer 40 000" both reduce to the same
    string -- a short digest of the original key is appended, so two games
    can never end up sharing one artwork file.
    """
    normalized = unicodedata.normalize("NFKD", key)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _SLUG_STRIP.sub("-", ascii_only.casefold()).strip("-")
    if not cleaned:
        return f"art-{_digest(key)}"
    if cleaned != key.casefold().replace(" ", "-"):
        return f"{cleaned}-{_digest(key)}"
    return cleaned


def load_image(source: Path | bytes | QImage) -> QImage:
    """Decode an image from a path, bytes or an existing QImage."""
    if isinstance(source, QImage):
        return source
    image = QImage()
    if isinstance(source, bytes):
        image.loadFromData(source)
    else:
        image.load(str(source))
    if image.isNull():
        raise OSError("could not decode image")
    return image


def has_real_alpha(image: QImage) -> bool:
    """True if the image actually uses transparency, not merely allows it."""
    if not image.hasAlphaChannel():
        return False
    # Sampling beats a full scan for large images and is accurate enough to
    # decide between PNG and a lossy format.
    step = max(1, min(image.width(), image.height()) // 64)
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            if image.pixelColor(x, y).alpha() < 255:
                return True
    return False


def prepare(image: QImage, spec: ArtSpec) -> tuple[QImage, str, int]:
    """Scale an image to a spec, returning it with its target format."""
    if image.width() > spec.max_width or image.height() > spec.max_height:
        image = image.scaled(
            spec.max_width,
            spec.max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if has_real_alpha(image):
        return image, "png", -1
    return image, spec.fmt, spec.quality


def encode(image: QImage, spec: ArtSpec) -> tuple[bytes, str]:
    """Encode an image per a spec. Returns the bytes and the extension."""
    prepared, fmt, quality = prepare(image, spec)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buffer, fmt.encode())
    if quality >= 0:
        writer.setQuality(quality)
    ok = writer.write(prepared)
    buffer.close()
    if not ok:
        raise OSError(f"could not encode image as {fmt}: {writer.errorString()}")
    return bytes(data.data()), f".{fmt}"
