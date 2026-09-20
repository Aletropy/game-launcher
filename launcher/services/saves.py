"""Backing up and restoring a game's saved data.

Mirrors what repair-prefix.sh copies, so a backup taken here is the same
shape as one taken by the script.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from launcher.data.paths import Paths
from launcher.domain import prefixes

#: Directories under the prefix that hold save data, relative to the
#: Wine user directory unless marked otherwise.
_USER_DIRS = (
    "AppData/Local",
    "AppData/LocalLow",
    "AppData/Roaming",
    "Documents",
    "Saved Games",
)
#: Copied from drive_c directly rather than from the user directory.
_DRIVE_DIRS = ("ProgramData",)


@dataclass(frozen=True)
class Backup:
    """One stored backup."""

    path: Path
    game: str
    created: datetime
    size: int

    @property
    def label(self) -> str:
        return self.created.strftime("%Y-%m-%d %H:%M")


def _drive_c(prefix: Path) -> Path | None:
    """Locate drive_c inside a prefix, which Proton nests under pfx/."""
    for candidate in (prefix / "pfx" / "drive_c", prefix / "drive_c"):
        if candidate.is_dir():
            return candidate
    return None


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


class SaveService:
    """Copies save data out of a prefix and back into it."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def backup_root(self, game: str) -> Path:
        return self._paths.backups_dir / _safe(game)

    def list_backups(self, game: str) -> list[Backup]:
        """Backups for a game, newest first."""
        root = self.backup_root(game)
        if not root.is_dir():
            return []
        backups: list[Backup] = []
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                created = datetime.fromtimestamp(entry.stat().st_mtime)  # noqa: DTZ006
            except OSError:
                continue
            backups.append(
                Backup(
                    path=entry,
                    game=game,
                    created=created,
                    size=_dir_size(entry),
                )
            )
        return sorted(backups, key=lambda b: b.created, reverse=True)

    def has_save_data(self, raw_prefix: str) -> bool:
        prefix = prefixes.resolve(raw_prefix, self._paths)
        return _drive_c(prefix) is not None

    def create_backup(self, game: str, raw_prefix: str) -> Backup:
        """Copy a game's save directories into backups/<game>/<timestamp>."""
        prefix = prefixes.resolve(raw_prefix, self._paths)
        drive_c = _drive_c(prefix)
        if drive_c is None:
            raise FileNotFoundError(
                f"No Wine drive found in {prefix}. The game may never have run."
            )

        stamp = datetime.now()
        dest = self.backup_root(game) / stamp.strftime("%Y-%m-%d_%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)

        user_dir = drive_c / "users" / "steamuser"
        copied = 0
        for relative in _USER_DIRS:
            source = user_dir / relative
            if source.is_dir():
                target = dest / "users" / "steamuser" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
                copied += 1
        for relative in _DRIVE_DIRS:
            source = drive_c / relative
            if source.is_dir():
                shutil.copytree(
                    source, dest / relative, dirs_exist_ok=True, symlinks=True
                )
                copied += 1

        if copied == 0:
            # Leave nothing behind rather than an empty directory that
            # looks like a usable backup.
            shutil.rmtree(dest, ignore_errors=True)
            raise FileNotFoundError(f"No save directories found in {prefix}.")

        return Backup(path=dest, game=game, created=stamp, size=_dir_size(dest))

    def restore(self, backup: Backup, raw_prefix: str) -> int:
        """Copy a backup back into a prefix. Returns files restored.

        Existing files are overwritten; anything in the prefix that the
        backup does not contain is left alone.
        """
        prefix = prefixes.resolve(raw_prefix, self._paths)
        drive_c = _drive_c(prefix)
        if drive_c is None:
            raise FileNotFoundError(
                f"No Wine drive found in {prefix}. Run the game once first."
            )
        if not backup.path.is_dir():
            raise FileNotFoundError(backup.path)

        restored = 0
        for source in backup.path.rglob("*"):
            if not source.is_file():
                continue
            target = drive_c / source.relative_to(backup.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored += 1
        return restored

    def delete_backup(self, backup: Backup) -> None:
        shutil.rmtree(backup.path, ignore_errors=True)


def _safe(name: str) -> str:
    """A directory name that is safe on any filesystem."""
    cleaned = "".join(c if c.isalnum() or c in " ._-" else "_" for c in name)
    return cleaned.strip() or "game"
