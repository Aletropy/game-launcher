"""Snapshots of the shared save store.

Each snapshot is a complete, browsable copy of Saves/ under
backups/saves/<timestamp>/data, so restoring never needs this code. They
are cheap anyway:

* A file unchanged since the previous snapshot is a hard link to that
  snapshot's copy, costing nothing.
* A changed file is cloned (reflink) where the filesystem supports it,
  as btrfs and XFS do, which also costs nothing until either side is
  written to; elsewhere it is copied.

Snapshots are never linked to the live files, so a game rewriting a
save in place can never reach back into a backup.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import shutil
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from launcher.data.paths import Paths
from launcher.domain.backup_policy import Exclusions, Retention, SnapshotAge, to_prune
from launcher.domain.save_layout import LINKS, MANIFEST_FILE

#: linux/fs.h: clone a whole file, sharing its extents.
_FICLONE = 0x40049409
_META = "snapshot.json"
_DATA = "data"
_PARTIAL = ".partial"
#: Headroom kept free on the disk after a snapshot, so a backup can never
#: be what fills it.
SPACE_MARGIN = 512 * 1024 * 1024


@dataclass(frozen=True)
class _Entry:
    """One file a snapshot will hold."""

    relative: str
    path: Path
    stat: os.stat_result
    #: The previous snapshot's copy, when the file has not changed.
    reuse: Path | None


class BackupError(OSError):
    """A backup or restore that could not be carried out."""


@dataclass
class Snapshot:
    """One stored snapshot."""

    path: Path
    created: datetime
    reason: str = ""
    pinned: bool = False
    files: int = 0
    total_bytes: int = 0
    #: Bytes this snapshot had to copy; the rest are shared with the one
    #: before it.
    new_bytes: int = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def data(self) -> Path:
        return self.path / _DATA

    @property
    def label(self) -> str:
        return self.created.strftime("%a %d %b %Y, %H:%M")

    def to_json(self) -> dict:
        return {
            "created": self.created.isoformat(timespec="seconds"),
            "reason": self.reason,
            "pinned": self.pinned,
            "files": self.files,
            "total_bytes": self.total_bytes,
            "new_bytes": self.new_bytes,
        }

    @classmethod
    def load(cls, path: Path) -> Snapshot | None:
        try:
            raw = json.loads((path / _META).read_text(encoding="utf-8"))
            created = datetime.fromisoformat(raw["created"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return cls(
            path=path,
            created=created,
            reason=str(raw.get("reason", "")),
            pinned=bool(raw.get("pinned", False)),
            files=int(raw.get("files", 0)),
            total_bytes=int(raw.get("total_bytes", 0)),
            new_bytes=int(raw.get("new_bytes", 0)),
        )


@dataclass
class FolderSize:
    """One folder inside a snapshot, for choosing what to restore."""

    relative: str
    files: int
    size: int


@dataclass
class RestoreResult:
    restored: int = 0
    removed: int = 0
    unchanged: int = 0
    safety: Snapshot | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class VerifyReport:
    """The structural health of one snapshot."""

    snapshot: Snapshot
    files: int = 0
    total_bytes: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


# --------------------------------------------------------------------------
# file helpers
# --------------------------------------------------------------------------


def clone_or_copy(source: Path, dest: Path) -> bool:
    """Copy a file, sharing its data blocks when the filesystem can.

    Returns True when it was a clone. Metadata (times, mode) is copied
    either way, which is what lets the next snapshot recognise the file
    as unchanged.
    """
    cloned = False
    with open(source, "rb") as src, open(dest, "wb") as dst:
        try:
            fcntl.ioctl(dst.fileno(), _FICLONE, src.fileno())
            cloned = True
        except OSError as e:
            if e.errno not in (
                errno.EOPNOTSUPP,
                errno.EXDEV,
                errno.EINVAL,
                errno.ENOTTY,
                errno.EBADF,
                errno.EPERM,
            ):
                raise
            shutil.copyfileobj(src, dst, 1024 * 1024)
    shutil.copystat(source, dest, follow_symlinks=False)
    return cloned


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


def _walk(
    root: Path,
    skip: Callable[[str], bool] | None = None,
    base: Path | None = None,
) -> Iterator[tuple[str, Path]]:
    """(posix relative path, absolute path) of every file and symlink.

    Paths are relative to `base` (default: root). Directories `skip`
    rejects are not descended into. Symlinks are reported as themselves
    and never followed.
    """
    base = base or root
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(base).as_posix()
            if skip is not None and skip(relative):
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
            else:
                yield relative, path


class BackupService:
    """Takes, prunes and restores snapshots of the shared save store."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        self._lock = threading.Lock()
        self.exclusions = Exclusions()
        self.retention = Retention()

    # -- locations -----------------------------------------------------

    @property
    def root(self) -> Path:
        return self._paths.backups_dir / "saves"

    @property
    def store(self) -> Path:
        return self._paths.saves_dir

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def _skipped(self, relative: str) -> bool:
        """Never backed up, never touched by a restore."""
        return relative == MANIFEST_FILE or self.exclusions.excludes(relative)

    # -- listing -------------------------------------------------------

    def snapshots(self) -> list[Snapshot]:
        """Finished snapshots, newest first."""
        if not self.root.is_dir():
            return []
        found = []
        for entry in self.root.iterdir():
            if not entry.is_dir() or entry.name.endswith(_PARTIAL):
                continue
            snapshot = Snapshot.load(entry)
            if snapshot is not None:
                found.append(snapshot)
        return sorted(found, key=lambda s: s.created, reverse=True)

    def latest(self) -> Snapshot | None:
        snapshots = self.snapshots()
        return snapshots[0] if snapshots else None

    def verify(self, snapshot: Snapshot) -> VerifyReport:
        """Check a snapshot is complete and readable.

        Compares the files on disk with the snapshot's own manifest and
        reports anything missing, unreadable, or a size mismatch, without
        changing anything.
        """
        report = VerifyReport(snapshot=snapshot)
        if Snapshot.load(snapshot.path) is None:
            report.problems.append("The snapshot manifest is missing or corrupt.")
            return report
        if not snapshot.data.is_dir():
            report.problems.append("The snapshot data folder is missing.")
            return report
        for relative, path in _walk(snapshot.data, base=snapshot.data):
            try:
                st = path.lstat()
            except OSError as e:
                report.problems.append(f"{relative}: cannot read ({e})")
                continue
            report.files += 1
            report.total_bytes += st.st_size
        if snapshot.files and report.files != snapshot.files:
            report.problems.append(
                f" Holds {report.files} file(s) but the manifest says {snapshot.files}."
            )
        if snapshot.total_bytes and report.total_bytes != snapshot.total_bytes:
            report.problems.append("Sizes do not match the manifest; files changed.")
        return report

    def disk_usage(self) -> int:
        """Real bytes used by all snapshots, counting shared files once."""
        seen: set[tuple[int, int]] = set()
        total = 0
        if not self.root.is_dir():
            return 0
        for _, path in _walk(self.root):
            try:
                st = path.lstat()
            except OSError:
                continue
            key = (st.st_dev, st.st_ino)
            if key not in seen:
                seen.add(key)
                total += st.st_size
        return total

    def folders(self, snapshot: Snapshot, depth: int = 3) -> list[FolderSize]:
        """Folders in a snapshot down to a depth, for picking a restore.

        Depth 3 reaches a game's own folder: AppData/Roaming/<Game>.
        """
        sizes: dict[str, FolderSize] = {}
        for relative, path in _walk(snapshot.data):
            parts = relative.split("/")
            try:
                size = path.lstat().st_size
            except OSError:
                size = 0
            for level in range(1, min(depth, len(parts) - 1) + 1):
                key = "/".join(parts[:level])
                entry = sizes.setdefault(key, FolderSize(key, 0, 0))
                entry.files += 1
                entry.size += size
        return sorted(sizes.values(), key=lambda f: f.relative.casefold())

    # -- taking --------------------------------------------------------

    def create(
        self, reason: str = "", *, pinned: bool = False, prune: bool = True
    ) -> Snapshot:
        """Snapshot the store. Raises BackupError if it cannot."""
        if not self.store.is_dir():
            raise BackupError("There are no shared saves to back up yet.")
        if not self._lock.acquire(blocking=False):
            raise BackupError("A backup is already running.")
        try:
            snapshot = self._create_locked(reason, pinned)
        finally:
            self._lock.release()
        if prune:
            self.prune()
        return snapshot

    def _create_locked(self, reason: str, pinned: bool) -> Snapshot:
        self.root.mkdir(parents=True, exist_ok=True)
        self._clear_partials()
        previous = self.latest()

        created = datetime.now()
        name = created.strftime("%Y-%m-%d_%H%M%S")
        final = self.root / name
        suffix = 1
        while final.exists():
            suffix += 1
            final = self.root / f"{name}-{suffix}"
        work = final.with_name(final.name + _PARTIAL)
        data = work / _DATA

        # Decide what is new before writing anything, so running out of
        # space is refused up front rather than discovered half way.
        plan = self._plan(previous)
        self._check_space(plan)

        snapshot = Snapshot(
            path=final, created=created, reason=reason, pinned=pinned
        )
        try:
            data.mkdir(parents=True)
            for entry in plan:
                dest = data / entry.relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if entry.path.is_symlink():
                        dest.symlink_to(os.readlink(entry.path))
                    elif entry.reuse is not None:
                        try:
                            os.link(entry.reuse, dest)
                        except OSError:
                            clone_or_copy(entry.reuse, dest)
                    else:
                        clone_or_copy(entry.path, dest)
                        snapshot.new_bytes += entry.stat.st_size
                except FileNotFoundError:
                    # Deleted while we were working: a game still writing.
                    continue
                snapshot.files += 1
                snapshot.total_bytes += entry.stat.st_size
            self._write_meta(work, snapshot)
            work.rename(final)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        return snapshot

    def _plan(self, previous: Snapshot | None) -> list[_Entry]:
        """Every file to back up, with a previous copy to reuse if unchanged."""
        plan: list[_Entry] = []
        for relative, path in _walk(self.store, self._skipped):
            try:
                st = path.lstat()
            except OSError:
                continue
            reuse = None
            if previous is not None and not path.is_symlink():
                candidate = previous.data / relative
                with contextlib.suppress(OSError):
                    if _same(st, candidate.lstat()):
                        reuse = candidate
            plan.append(_Entry(relative, path, st, reuse))
        return plan

    def _check_space(self, plan: list[_Entry]) -> None:
        fresh = [e for e in plan if e.reuse is None and not e.path.is_symlink()]
        needed = sum(e.stat.st_size for e in fresh)
        free = shutil.disk_usage(self.root).free
        if free >= needed + SPACE_MARGIN:
            return
        # Clones need no space; find out whether they are available here.
        if fresh and free >= SPACE_MARGIN and self._can_clone(fresh[0].path):
            return
        raise BackupError(
            f"Not enough free disk space for a backup: it needs about "
            f"{needed // (1024 * 1024)} MB and only "
            f"{free // (1024 * 1024)} MB is free."
        )

    def _check_restore_space(self, source: Path) -> None:
        """Refuse a restore that would leave the disk too full."""
        needed = 0
        for _, path in _walk(source, base=source):
            try:
                if not path.is_symlink():
                    needed += path.lstat().st_size
            except OSError:
                continue
        try:
            free = shutil.disk_usage(self.store).free
        except OSError:
            return
        if free - needed < SPACE_MARGIN:
            raise BackupError(
                "Not enough free disk space to restore: it needs about "
                f"{needed // (1024 * 1024)} MB and only "
                f"{free // (1024 * 1024)} MB is free."
            )

    def _can_clone(self, sample: Path) -> bool:
        probe = self.root / ".clone-probe"
        try:
            if sample.stat().st_size > 64 << 20:
                return False
            return clone_or_copy(sample, probe)
        except OSError:
            return False
        finally:
            probe.unlink(missing_ok=True)

    def _clear_partials(self) -> None:
        """Remove snapshots a crash or power cut left unfinished."""
        for entry in self.root.iterdir():
            if entry.name.endswith(_PARTIAL):
                shutil.rmtree(entry, ignore_errors=True)

    @staticmethod
    def _write_meta(directory: Path, snapshot: Snapshot) -> None:
        tmp = directory / (_META + ".tmp")
        tmp.write_text(json.dumps(snapshot.to_json(), indent=2), encoding="utf-8")
        tmp.replace(directory / _META)

    # -- managing ------------------------------------------------------

    def set_pinned(self, snapshot: Snapshot, pinned: bool) -> None:
        snapshot.pinned = pinned
        self._write_meta(snapshot.path, snapshot)

    def delete(self, snapshot: Snapshot) -> None:
        # Only this snapshot's names go; files it shares with others are
        # hard links and survive through them.
        shutil.rmtree(snapshot.path)

    def prune(self, today: datetime | None = None) -> list[str]:
        """Delete snapshots the retention policy no longer keeps."""
        snapshots = {s.name: s for s in self.snapshots()}
        doomed = to_prune(
            [SnapshotAge(s.name, s.created, s.pinned) for s in snapshots.values()],
            self.retention,
            today.date() if today else None,
        )
        for name in doomed:
            shutil.rmtree(snapshots[name].path, ignore_errors=True)
        return doomed

    # -- restoring -----------------------------------------------------

    def restore(
        self,
        snapshot: Snapshot,
        folder: str = "",
        *,
        safety_snapshot: bool = True,
    ) -> RestoreResult:
        """Put the store (or one folder of it) back as the snapshot had it.

        Files the snapshot has are written back; files created since are
        removed, so the folder really is as it was. Excluded paths such
        as caches are left alone. A snapshot of the current state is
        taken first, so a restore can itself be undone.
        """
        folder = folder.strip("/")
        source = snapshot.data / folder if folder else snapshot.data
        if not source.is_dir():
            raise BackupError(f"The backup has no folder '{folder}'.")

        self._check_restore_space(source)
        result = RestoreResult()
        if safety_snapshot and self.store.is_dir():
            result.safety = self.create(f"before restoring {snapshot.label}")

        if not self._lock.acquire(blocking=False):
            raise BackupError("A backup is running; try again in a moment.")
        try:
            self._restore_locked(snapshot, folder, result)
        finally:
            self._lock.release()
        return result

    def _restore_locked(
        self, snapshot: Snapshot, folder: str, result: RestoreResult
    ) -> None:
        wanted: set[str] = set()
        source_root = snapshot.data / folder if folder else snapshot.data
        for full, path in _walk(source_root, base=snapshot.data):
            wanted.add(full)
            dest = self.store / full
            try:
                if (
                    dest.exists()
                    and not dest.is_symlink()
                    and not path.is_symlink()
                    and _same(path.lstat(), dest.lstat())
                ):
                    result.unchanged += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".restoring")
                tmp.unlink(missing_ok=True)
                if path.is_symlink():
                    tmp.symlink_to(os.readlink(path))
                else:
                    clone_or_copy(path, tmp)
                tmp.replace(dest)
                result.restored += 1
            except OSError as e:
                result.errors.append(f"{full}: {e}")

        # Remove what was created since, inside the chosen folder.
        live_root = self.store / folder if folder else self.store
        if live_root.is_dir():
            for full, path in list(_walk(live_root, self._skipped, self.store)):
                if full in wanted:
                    continue
                try:
                    path.unlink()
                    result.removed += 1
                except OSError as e:
                    result.errors.append(f"{full}: {e}")
            self._prune_dirs(live_root, snapshot, folder)

    def _prune_dirs(self, live_root: Path, snapshot: Snapshot, folder: str) -> None:
        """Drop empty folders the snapshot does not have.

        The folders prefixes link into are kept even when empty: a link
        to a missing folder would be a broken link.
        """
        protected = {self.store / spec.in_store for spec in LINKS}
        for directory in sorted(
            (Path(d) for d, _, _ in os.walk(live_root)),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            if directory in protected or directory == live_root:
                continue
            relative = directory.relative_to(self.store).as_posix()
            if (snapshot.data / relative).is_dir() or self._skipped(relative):
                continue
            with contextlib.suppress(OSError):
                directory.rmdir()
