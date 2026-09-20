"""Artwork storage and the display pixmap cache."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap

from launcher.data.paths import Paths
from launcher.services.artwork.specs import (
    EXTENSIONS,
    GRID,
    SPECS,
    encode,
    load_image,
    slug,
)

#: Scaled pixmaps are cheap to hold and expensive to rebuild.
_CACHE_LIMIT = 256


class ArtworkService:
    """Stores artwork at display size and serves scaled pixmaps.

    Artwork is kept once per game per art type. Sources from SteamGridDB
    are typically 600x900 PNGs of around 800 KB shown in a 200x280 card,
    so storing them verbatim wastes roughly an order of magnitude of disk.
    """

    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        #: (key, art, width, height) -> (pixmap, source mtime)
        self._cache: OrderedDict[
            tuple[str, str, int, int], tuple[QPixmap, int]
        ] = OrderedDict()

    # -- locations -----------------------------------------------------

    @property
    def root(self) -> Path:
        return self._paths.artwork_dir

    @property
    def legacy_dir(self) -> Path:
        return self._paths.legacy_heroes_dir

    def art_dir(self, art: str) -> Path:
        return self.root / art

    def path_for(self, key: str, art: str = GRID.name) -> Path | None:
        """Return the stored artwork for a game, or None.

        Falls back to the pre-revamp flat ``heroes/`` directory so existing
        artwork keeps displaying until the cleanup migrates it.
        """
        stem = slug(key)
        directory = self.art_dir(art)
        for ext in EXTENSIONS:
            candidate = directory / f"{stem}{ext}"
            if candidate.is_file():
                return candidate

        if art == GRID.name:
            for ext in EXTENSIONS:
                legacy = self.legacy_dir / f"{key}{ext}"
                if legacy.is_file():
                    return legacy
        return None

    # -- writes --------------------------------------------------------

    def store(self, key: str, art: str, source: Path | bytes | QImage) -> Path:
        """Scale, encode and save artwork, replacing any previous file."""
        spec = SPECS[art]
        data, ext = encode(load_image(source), spec)

        directory = self.art_dir(art)
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / f"{slug(key)}{ext}"

        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)

        # Drop any previous file for this game stored under another
        # extension; otherwise the lookup order decides which one wins.
        for other in EXTENSIONS:
            stale = directory / f"{slug(key)}{other}"
            if stale != dest and stale.is_file():
                stale.unlink(missing_ok=True)

        self.invalidate(key)
        return dest

    def remove(self, key: str, art: str | None = None) -> int:
        """Delete stored artwork. Returns the number of files removed.

        Called when a game is removed, so artwork does not outlive its
        game forever.
        """
        arts = [art] if art else list(SPECS)
        removed = 0
        for one in arts:
            for ext in EXTENSIONS:
                candidate = self.art_dir(one) / f"{slug(key)}{ext}"
                if candidate.is_file():
                    candidate.unlink(missing_ok=True)
                    removed += 1
        if art is None:
            for ext in EXTENSIONS:
                legacy = self.legacy_dir / f"{key}{ext}"
                if legacy.is_file():
                    legacy.unlink(missing_ok=True)
                    removed += 1
        self.invalidate(key)
        return removed

    def rename(self, old_key: str, new_key: str) -> None:
        """Move a game's artwork to a new key."""
        for art in SPECS:
            source = self.path_for(old_key, art)
            if source is None:
                continue
            directory = self.art_dir(art)
            directory.mkdir(parents=True, exist_ok=True)
            source.replace(directory / f"{slug(new_key)}{source.suffix}")
        self.invalidate(old_key)
        self.invalidate(new_key)

    # -- display -------------------------------------------------------

    def invalidate(self, key: str | None = None) -> None:
        """Drop cached pixmaps, for one game or all of them."""
        if key is None:
            self._cache.clear()
            return
        for cached in [k for k in self._cache if k[0] == key]:
            del self._cache[cached]

    def pixmap(
        self, key: str, art: str, size: QSize, *, expand: bool = False
    ) -> QPixmap | None:
        """Return artwork scaled to a size, or None if there is none.

        GUI thread only, since it builds QPixmaps. Results are cached by
        source mtime, so rebuilding the library does not re-decode every
        file.
        """
        source = self.path_for(key, art)
        if source is None:
            return None

        try:
            mtime = source.stat().st_mtime_ns
        except OSError:
            return None

        cache_key = (key, art, size.width(), size.height())
        hit = self._cache.get(cache_key)
        if hit is not None and hit[1] == mtime:
            self._cache.move_to_end(cache_key)
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

        self._cache[cache_key] = (scaled, mtime)
        self._cache.move_to_end(cache_key)
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        return scaled
