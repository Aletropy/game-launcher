"""Finding and reclaiming wasted artwork.

A scan never writes. Applying a cleanup does only what it is asked, so
declining every action leaves the directory untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from launcher.services.artwork.specs import (
    EXTENSIONS,
    GRID,
    SPECS,
    encode,
    load_image,
    slug,
)
from launcher.services.artwork.store import ArtworkService


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

    files: list[ArtFile] = field(default_factory=list)
    orphans: list[ArtFile] = field(default_factory=list)
    duplicates: list[ArtFile] = field(default_factory=list)
    shrinkable: list[ArtFile] = field(default_factory=list)
    legacy: list[ArtFile] = field(default_factory=list)

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


@dataclass
class CleanupResult:
    """What a cleanup actually did."""

    migrated: int = 0
    reencoded: int = 0
    deduped: int = 0
    orphans_removed: int = 0
    freed: int = 0
    errors: list[str] = field(default_factory=list)


class ArtworkCleaner:
    """Scans stored artwork and applies the actions the user confirms."""

    def __init__(self, artwork: ArtworkService) -> None:
        self._artwork = artwork

    # -- scanning ------------------------------------------------------

    def _scan_dir(self, directory: Path, art: str, *, legacy: bool) -> list[ArtFile]:
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
            found.append(
                ArtFile(path=path, key=path.stem, art=art, size=size, legacy=legacy)
            )
        return found

    def scan(self, known_keys: set[str], *, measure: bool = True) -> CleanupReport:
        """Inspect stored artwork against the games that still exist.

        With ``measure``, each keeper is re-encoded into memory so the
        report states exact savings rather than an estimate.
        """
        files: list[ArtFile] = []
        for art in SPECS:
            files.extend(self._scan_dir(self._artwork.art_dir(art), art, legacy=False))
        files.extend(
            self._scan_dir(self._artwork.legacy_dir, GRID.name, legacy=True)
        )

        known_slugs = {slug(k) for k in known_keys}
        orphans: list[ArtFile] = []
        live: list[ArtFile] = []
        for f in files:
            known = f.key in known_keys if f.legacy else f.key in known_slugs
            (live if known else orphans).append(f)

        duplicates, keepers = self._split_duplicates(live)
        legacy = [f for f in keepers if f.legacy]
        shrinkable = self._measure(keepers) if measure else []

        return CleanupReport(
            files=files,
            orphans=orphans,
            duplicates=duplicates,
            shrinkable=shrinkable,
            legacy=legacy,
        )

    @staticmethod
    def _split_duplicates(
        live: list[ArtFile],
    ) -> tuple[list[ArtFile], list[ArtFile]]:
        """Among live files, keep the newest per game and art type."""
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
        return duplicates, keepers

    @staticmethod
    def _measure(keepers: list[ArtFile]) -> list[ArtFile]:
        """Re-encode each keeper in memory to learn its exact new size."""
        shrinkable: list[ArtFile] = []
        for f in keepers:
            try:
                data, _ = encode(load_image(f.path), SPECS[f.art])
            except OSError:
                continue
            if len(data) < f.size:
                f.reencoded = data
                shrinkable.append(f)
        return shrinkable

    # -- applying ------------------------------------------------------

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def apply(
        self,
        report: CleanupReport,
        *,
        reencode: bool = True,
        dedupe: bool = True,
        delete_orphans: bool = True,
        migrate: bool = True,
    ) -> CleanupResult:
        """Carry out the selected parts of a scan.

        With every flag off this does nothing at all, so a user who unticks
        each action and confirms still keeps every file.
        """
        result = CleanupResult()
        if delete_orphans:
            self._delete(report.orphans, result, "orphans_removed")
        if dedupe:
            self._delete(report.duplicates, result, "deduped")
        self._rewrite(report, result, reencode=reencode, migrate=migrate)
        self._artwork.invalidate()
        return result

    @staticmethod
    def _delete(files: list[ArtFile], result: CleanupResult, counter: str) -> None:
        for f in files:
            try:
                size = f.size
                f.path.unlink()
            except OSError as e:
                result.errors.append(f"{f.path.name}: {e}")
            else:
                setattr(result, counter, getattr(result, counter) + 1)
                result.freed += size

    def _rewrite(
        self,
        report: CleanupReport,
        result: CleanupResult,
        *,
        reencode: bool,
        migrate: bool,
    ) -> None:
        """Migrate legacy files and re-encode keepers, in a single write."""
        for f in report.files:
            # Orphans and duplicates were deleted above or deliberately
            # left alone; either way they are never rewritten in place.
            if f in report.orphans or f in report.duplicates:
                continue

            moving = migrate and f.legacy
            shrinking = reencode and f.reencoded is not None
            if not (moving or shrinking):
                continue

            data = f.reencoded if shrinking else None
            ext = f".{SPECS[f.art].fmt}"
            if moving:
                if data is None:
                    try:
                        data, ext = encode(load_image(f.path), SPECS[f.art])
                    except OSError as e:
                        result.errors.append(f"{f.path.name}: {e}")
                        continue
                directory = self._artwork.art_dir(f.art)
                directory.mkdir(parents=True, exist_ok=True)
                dest = directory / f"{slug(f.key)}{ext}"
            else:
                dest = f.path

            assert data is not None
            try:
                self._write(dest, data)
                if moving and f.path != dest:
                    f.path.unlink(missing_ok=True)
            except OSError as e:
                result.errors.append(f"{f.path.name}: {e}")
                continue

            if moving:
                result.migrated += 1
            if shrinking:
                result.reencoded += 1
            result.freed += max(0, f.size - len(data))
