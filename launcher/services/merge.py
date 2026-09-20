"""Merging one directory tree into another without losing anything.

The rule is newest wins, and the loser is quarantined rather than
deleted. Nothing this module does is destructive: every file either ends
up at its destination or under the conflicts directory.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Conflict:
    """One file that existed on both sides with different content."""

    relative: str
    kept: Path
    quarantined: Path
    kept_mtime: float
    loser_mtime: float

    @property
    def kept_from_source(self) -> bool:
        return self.kept_mtime >= self.loser_mtime


@dataclass
class MergePlan:
    """What a merge would do. Produced without touching anything."""

    source: Path
    destination: Path
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    identical: list[Path] = field(default_factory=list)
    conflicts: list[tuple[Path, Path]] = field(default_factory=list)
    unreadable: list[Path] = field(default_factory=list)

    @property
    def move_bytes(self) -> int:
        return sum(_size(src) for src, _ in self.moves)

    @property
    def conflict_bytes(self) -> int:
        return sum(_size(src) for src, _ in self.conflicts)

    @property
    def total_files(self) -> int:
        return len(self.moves) + len(self.identical) + len(self.conflicts)

    @property
    def is_empty(self) -> bool:
        return self.total_files == 0


@dataclass
class MergeResult:
    """What a merge actually did."""

    moved: int = 0
    identical_removed: int = 0
    conflicts: list[Conflict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bytes_moved: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def same_file(a: Path, b: Path) -> bool:
    """Whether two files can be treated as the same copy.

    Size and modification time, not a hash: these trees run to gigabytes
    and the cost of hashing them is not worth the extra certainty when
    the loser is quarantined rather than deleted anyway.
    """
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)


def _iter_files(root: Path):
    """Every regular file under root, as (path, relative)."""
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            yield path, path.relative_to(root)
        except ValueError:
            continue


def plan_merge(source: Path, destination: Path) -> MergePlan:
    """Work out what merging source into destination would do."""
    plan = MergePlan(source=source, destination=destination)
    if not source.is_dir():
        return plan

    for path, relative in _iter_files(source):
        target = destination / relative
        try:
            exists = target.exists()
        except OSError:
            plan.unreadable.append(path)
            continue

        if not exists:
            plan.moves.append((path, target))
        elif same_file(path, target):
            plan.identical.append(path)
        else:
            plan.conflicts.append((path, target))
    return plan


def _move(source: Path, target: Path) -> None:
    """Move a file, falling back to a copy across filesystems."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.rename(target)
    except OSError:
        # Different filesystem, or a rename the kernel refuses.
        shutil.move(str(source), str(target))


def apply_merge(
    source: Path,
    destination: Path,
    conflicts_root: Path,
    *,
    prefer_newest: bool = True,
) -> MergeResult:
    """Merge source into destination. Quarantines every loser.

    With ``prefer_newest`` the newer file wins; otherwise the
    destination always wins. Either way the other copy is moved under
    ``conflicts_root``, never removed.
    """
    result = MergeResult()
    if not source.is_dir():
        return result

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    quarantine = conflicts_root / stamp

    for path, relative in _iter_files(source):
        target = destination / relative
        try:
            if not target.exists():
                size = _size(path)
                _move(path, target)
                result.moved += 1
                result.bytes_moved += size
                continue

            if same_file(path, target):
                # The same copy on both sides; drop the duplicate.
                path.unlink()
                result.identical_removed += 1
                continue

            source_mtime = path.stat().st_mtime
            target_mtime = target.stat().st_mtime
            source_wins = prefer_newest and source_mtime > target_mtime

            held = quarantine / relative
            if source_wins:
                _move(target, held)
                _move(path, target)
                kept, kept_mtime, loser_mtime = target, source_mtime, target_mtime
            else:
                _move(path, held)
                kept, kept_mtime, loser_mtime = target, target_mtime, source_mtime

            result.conflicts.append(
                Conflict(
                    relative=str(relative),
                    kept=kept,
                    quarantined=held,
                    kept_mtime=kept_mtime,
                    loser_mtime=loser_mtime,
                )
            )
        except OSError as e:
            result.errors.append(f"{relative}: {e}")

    prune_empty(source)
    return result


def prune_empty(root: Path, *, keep_root: bool = True) -> int:
    """Remove directories left empty by a merge. Never removes files."""
    if not root.is_dir():
        return 0
    removed = 0
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            path.rmdir()
        except OSError:
            continue  # not empty, which is fine
        removed += 1
    if not keep_root:
        try:
            root.rmdir()
            removed += 1
        except OSError:
            pass
    return removed


def directory_size(path: Path) -> int:
    """Bytes held by a directory tree, ignoring symlinks."""
    total = 0
    if not path.is_dir():
        return 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += _size(item)
    return total
