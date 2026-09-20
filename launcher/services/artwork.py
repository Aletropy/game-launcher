"""Artwork storage, re-encoding and caching.

Artwork is stored once per game per art type, scaled to the size it is
actually displayed at. Source images from SteamGridDB are typically
600x900 PNGs of around 800 KB shown in a 200x280 card, so storing them
verbatim wastes roughly an order of magnitude of disk.

Everything here uses Qt's own image classes; there is no Pillow
dependency.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageWriter, QPixmap

from launcher.core.paths import ARTWORK_DIR, LEGACY_HEROES_DIR

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


#: Card art is portrait; the card is 200x280, so 400x600 covers 2x displays.
GRID: Final = ArtSpec("grid", 400, 600)
#: The detail panel banner, roughly 2x a 640px wide panel.
HERO: Final = ArtSpec("hero", 1280, 400)
#: Small square art for list rows.
ICON: Final = ArtSpec("icon", 128, 128, fmt="png", quality=-1)

SPECS: Final[dict[str, ArtSpec]] = {s.name: s for s in (GRID, HERO, ICON)}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


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


def _digest(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]


def art_dir(art: str) -> Path:
    """The directory holding one art type."""
    return ARTWORK_DIR / art


def path_for(key: str, art: str = GRID.name) -> Path | None:
    """Return the stored artwork for a game, or None.

    Falls back to the pre-revamp flat ``heroes/`` directory so existing
    artwork keeps displaying until the cleanup migrates it.
    """
    directory = art_dir(art)
    stem = slug(key)
    for ext in EXTENSIONS:
        candidate = directory / f"{stem}{ext}"
        if candidate.is_file():
            return candidate

    if art == GRID.name:
        for ext in EXTENSIONS:
            legacy = LEGACY_HEROES_DIR / f"{key}{ext}"
            if legacy.is_file():
                return legacy
    return None


def _has_real_alpha(image: QImage) -> bool:
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


def _prepare(image: QImage, spec: ArtSpec) -> tuple[QImage, str, int]:
    """Scale an image to a spec, returning it with its target format."""
    if image.width() > spec.max_width or image.height() > spec.max_height:
        image = image.scaled(
            spec.max_width,
            spec.max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if _has_real_alpha(image):
        return image, "png", -1
    return image, spec.fmt, spec.quality


def encode(image: QImage, spec: ArtSpec) -> tuple[bytes, str]:
    """Encode an image per a spec. Returns the bytes and the extension."""
    prepared, fmt, quality = _prepare(image, spec)
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


def _load(source: Path | bytes | QImage) -> QImage:
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


def store(key: str, art: str, source: Path | bytes | QImage) -> Path:
    """Scale, encode and save artwork, replacing any previous file."""
    spec = SPECS[art]
    data, ext = encode(_load(source), spec)

    directory = art_dir(art)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{slug(key)}{ext}"

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)

    # Drop any previous file for this game stored under another extension;
    # otherwise the lookup order decides which one wins.
    for other in EXTENSIONS:
        stale = directory / f"{slug(key)}{other}"
        if stale != dest and stale.is_file():
            stale.unlink(missing_ok=True)

    invalidate(key)
    return dest


def remove(key: str, art: str | None = None) -> int:
    """Delete stored artwork for a game. Returns the number of files removed.

    Called when a game is removed, so deleting a game no longer leaves its
    artwork behind forever.
    """
    arts = [art] if art else list(SPECS)
    removed = 0
    for one in arts:
        for ext in EXTENSIONS:
            candidate = art_dir(one) / f"{slug(key)}{ext}"
            if candidate.is_file():
                candidate.unlink(missing_ok=True)
                removed += 1
    if art is None:
        for ext in EXTENSIONS:
            legacy = LEGACY_HEROES_DIR / f"{key}{ext}"
            if legacy.is_file():
                legacy.unlink(missing_ok=True)
                removed += 1
    invalidate(key)
    return removed


def rename(old_key: str, new_key: str) -> None:
    """Move a game's artwork to a new key."""
    for art in SPECS:
        source = path_for(old_key, art)
        if source is None:
            continue
        directory = art_dir(art)
        directory.mkdir(parents=True, exist_ok=True)
        source.replace(directory / f"{slug(new_key)}{source.suffix}")
    invalidate(old_key)
    invalidate(new_key)


# ---------------------------------------------------------------------------
# Pixmap cache
# ---------------------------------------------------------------------------

_CACHE_LIMIT = 256
#: (key, art, width, height) -> (pixmap, source mtime)
_cache: OrderedDict[tuple[str, str, int, int], tuple[QPixmap, int]] = OrderedDict()


def invalidate(key: str | None = None) -> None:
    """Drop cached pixmaps, for one game or all of them."""
    if key is None:
        _cache.clear()
        return
    for cached in [k for k in _cache if k[0] == key]:
        del _cache[cached]


def pixmap(key: str, art: str, size: QSize, *, expand: bool = False) -> QPixmap | None:
    """Return artwork scaled to a size, or None if there is none.

    GUI thread only, since it builds QPixmaps. Results are cached by
    source mtime, so rebuilding the library does not re-decode every file.
    """
    source = path_for(key, art)
    if source is None:
        return None

    try:
        mtime = source.stat().st_mtime_ns
    except OSError:
        return None

    cache_key = (key, art, size.width(), size.height())
    hit = _cache.get(cache_key)
    if hit is not None and hit[1] == mtime:
        _cache.move_to_end(cache_key)
        return hit[0]

    raw = QPixmap(str(source))
    if raw.isNull():
        return None
    mode = (
        Qt.AspectRatioMode.KeepAspectRatioByExpanding
        if expand
        else Qt.AspectRatioMode.KeepAspectRatio
    )
    scaled = raw.scaled(size, mode, Qt.TransformationMode.SmoothTransformation)

    _cache[cache_key] = (scaled, mtime)
    _cache.move_to_end(cache_key)
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return scaled


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@dataclass
class ArtFile:
    """One artwork file found on disk."""

    path: Path
    key: str
    art: str
    size: int
    legacy: bool = False
    #: Bytes the file would occupy after re-encoding, once computed.
    reencoded: bytes | None = None

    @property
    def savings(self) -> int:
        if self.reencoded is None:
            return 0
        return max(0, self.size - len(self.reencoded))


@dataclass
class CleanupReport:
    """What a scan found, and what each action would reclaim."""

    files: list[ArtFile]
    orphans: list[ArtFile]
    duplicates: list[ArtFile]
    shrinkable: list[ArtFile]
    legacy: list[ArtFile]

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def orphan_bytes(self) -> int:
        return sum(f.size for f in self.orphans)

    @property
    def duplicate_bytes(self) -> int:
        return sum(f.size for f in self.duplicates)

    @property
    def shrink_bytes(self) -> int:
        return sum(f.savings for f in self.shrinkable)

    def reclaimable(self, *, reencode: bool, dedupe: bool, orphans: bool) -> int:
        """Bytes freed by the selected actions, without double counting."""
        skip: set[int] = set()
        total = 0
        if orphans:
            total += self.orphan_bytes
            skip.update(id(f) for f in self.orphans)
        if dedupe:
            total += sum(f.size for f in self.duplicates if id(f) not in skip)
            skip.update(id(f) for f in self.duplicates)
        if reencode:
            total += sum(f.savings for f in self.shrinkable if id(f) not in skip)
        return total

    @property
    def is_empty(self) -> bool:
        return not (self.orphans or self.duplicates or self.shrinkable or self.legacy)


def _scan_dir(directory: Path, art: str, *, legacy: bool) -> list[ArtFile]:
    if not directory.is_dir():
        return []
    found: list[ArtFile] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        found.append(ArtFile(path=path, key=path.stem, art=art, size=size, legacy=legacy))
    return found


def scan(known_keys: set[str], *, measure: bool = True) -> CleanupReport:
    """Inspect stored artwork against the set of games that still exist.

    With ``measure``, each file is re-encoded into memory so the report
    states exact savings rather than an estimate. Nothing is written.
    """
    files: list[ArtFile] = []
    for art in SPECS:
        files.extend(_scan_dir(art_dir(art), art, legacy=False))
    files.extend(_scan_dir(LEGACY_HEROES_DIR, GRID.name, legacy=True))

    known_slugs = {slug(k) for k in known_keys}

    orphans: list[ArtFile] = []
    live: list[ArtFile] = []
    for f in files:
        known = f.key in known_keys if f.legacy else f.key in known_slugs
        (live if known else orphans).append(f)

    # Among live files, the same game and art type may have several
    # extensions; the newest wins and the rest are duplicates.
    by_target: dict[tuple[str, str], list[ArtFile]] = {}
    for f in live:
        target = (slug(f.key) if f.legacy else f.key, f.art)
        by_target.setdefault(target, []).append(f)

    duplicates: list[ArtFile] = []
    keepers: list[ArtFile] = []
    for group in by_target.values():
        if len(group) == 1:
            keepers.append(group[0])
            continue
        group.sort(key=lambda f: f.path.stat().st_mtime, reverse=True)
        keepers.append(group[0])
        duplicates.extend(group[1:])

    legacy = [f for f in keepers if f.legacy]

    shrinkable: list[ArtFile] = []
    if measure:
        for f in keepers:
            try:
                data, _ = encode(_load(f.path), SPECS[f.art])
            except OSError:
                continue
            if len(data) < f.size:
                f.reencoded = data
                shrinkable.append(f)

    return CleanupReport(
        files=files,
        orphans=orphans,
        duplicates=duplicates,
        shrinkable=shrinkable,
        legacy=legacy,
    )


@dataclass
class CleanupResult:
    """What a cleanup actually did."""

    migrated: int = 0
    reencoded: int = 0
    deduped: int = 0
    orphans_removed: int = 0
    freed: int = 0
    errors: list[str] = field(default_factory=list)


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def apply_cleanup(
    report: CleanupReport,
    *,
    reencode: bool = True,
    dedupe: bool = True,
    delete_orphans: bool = True,
    migrate: bool = True,
) -> CleanupResult:
    """Carry out the selected parts of a scan. Only these are destructive.

    With every flag off this does nothing at all, so a user who unticks
    each action and confirms still keeps every file.
    """
    result = CleanupResult()

    if delete_orphans:
        for f in report.orphans:
            try:
                size = f.size
                f.path.unlink()
            except OSError as e:
                result.errors.append(f"{f.path.name}: {e}")
            else:
                result.orphans_removed += 1
                result.freed += size

    if dedupe:
        for f in report.duplicates:
            try:
                size = f.size
                f.path.unlink()
            except OSError as e:
                result.errors.append(f"{f.path.name}: {e}")
            else:
                result.deduped += 1
                result.freed += size

    # Migration and re-encoding both rewrite a keeper, so they run together:
    # a legacy file that also shrinks is written once, into its new home.
    for f in report.files:
        # Orphans and duplicates are either deleted above or deliberately
        # left alone; either way they are never rewritten in place.
        if f in report.orphans or f in report.duplicates:
            continue

        moving = migrate and f.legacy
        shrinking = reencode and f.reencoded is not None
        if not (moving or shrinking):
            continue

        data = f.reencoded if shrinking else None
        if moving:
            if data is None:
                try:
                    data, ext = encode(_load(f.path), SPECS[f.art])
                except OSError as e:
                    result.errors.append(f"{f.path.name}: {e}")
                    continue
            else:
                ext = f".{SPECS[f.art].fmt}"
            directory = art_dir(f.art)
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / f"{slug(f.key)}{ext}"
        else:
            dest = f.path

        assert data is not None
        try:
            before = f.size
            _write(dest, data)
            if moving and f.path != dest:
                f.path.unlink(missing_ok=True)
        except OSError as e:
            result.errors.append(f"{f.path.name}: {e}")
            continue

        if moving:
            result.migrated += 1
        if shrinking:
            result.reencoded += 1
        result.freed += max(0, before - len(data))

    invalidate()
    return result
