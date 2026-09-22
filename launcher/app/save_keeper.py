"""Keeps saves shared and backed up without being asked.

* Every prefix joins the shared store by default: before a game starts,
  and again when it exits, since a fresh prefix only exists after its
  first run.
* The store is snapshotted before anything moves files around in it,
  and after playing, at most once per interval.
* Links Proton replaced are put back before a game starts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from launcher.app.context import AppContext
from launcher.domain import prefixes
from launcher.domain.backup_policy import Exclusions, Retention
from launcher.domain.models import Game
from launcher.services.backups import BackupError, Snapshot
from launcher.services.save_store import AdoptResult
from launcher.services.tasks import Task, TaskSignals, pool

_BACKUP_KEYS = (
    "backup_keep_recent",
    "backup_keep_daily",
    "backup_keep_weekly",
    "backup_exclude",
)


class SaveKeeper(QObject):
    """Automatic sharing and backups for the shared save store."""

    status = Signal(str)
    error = Signal(str, str)
    #: A snapshot was taken or removed.
    backups_changed = Signal()

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._tasks: dict[int, TaskSignals] = {}
        self._next_token = 0
        self.apply_settings()
        context.settings.changed.connect(self._on_setting_changed)
        context.processes.game_finished.connect(self._after_game)

    # -- settings ------------------------------------------------------

    def apply_settings(self) -> None:
        settings = self._ctx.settings
        backups = self._ctx.backups
        backups.retention = Retention(
            recent=settings.get_int("backup_keep_recent"),
            daily=settings.get_int("backup_keep_daily"),
            weekly=settings.get_int("backup_keep_weekly"),
        )
        backups.exclusions = Exclusions.with_extra(settings.get_str("backup_exclude"))

    def _on_setting_changed(self, key: str, _value: object) -> None:
        if key in _BACKUP_KEYS:
            self.apply_settings()

    @property
    def _share_by_default(self) -> bool:
        return self._ctx.settings.get_bool("share_saves_by_default")

    # -- prefixes ------------------------------------------------------

    def prefix_of(self, game: Game) -> Path:
        return prefixes.resolve(game.prefix, self._ctx.paths)

    def _busy_prefixes(self) -> set[Path]:
        """Prefixes a running game is using; never rearranged under it."""
        busy = set()
        for name in self._ctx.processes.running_games:
            game = self._ctx.games.get(name)
            if game is not None:
                busy.add(self.prefix_of(game))
        return busy

    def all_prefixes(self) -> list[Path]:
        """Every prefix in use: the managed ones and any custom paths."""
        found = list(self._ctx.save_store.known_prefixes())
        for game in self._ctx.games.list_games():
            prefix = self.prefix_of(game)
            if prefix not in found:
                found.append(prefix)
        return found

    def needs_sharing(self, prefix: Path) -> bool:
        return self._ctx.save_store.plan_adopt(prefix).can_run

    # -- sharing -------------------------------------------------------

    def share(self, prefix: Path, *, backup: bool = True) -> AdoptResult | None:
        """Adopt one prefix into the store, backing the store up first.

        Returns None when there was nothing to do or it was not safe.
        """
        store = self._ctx.save_store
        if prefix in self._busy_prefixes() or not self.needs_sharing(prefix):
            return None
        if backup and not self.safety_backup(f"before sharing {prefix.name}"):
            return None
        result = store.adopt(prefix)
        if result.errors:
            self.error.emit(
                "Shared Saves",
                f"{prefix.name} was only partly shared:\n"
                + "\n".join(result.errors[:5]),
            )
        elif result.linked:
            conflicts = (
                f", {result.conflict_count} conflict(s) kept aside"
                if result.conflict_count
                else ""
            )
            self.status.emit(
                f"{prefix.name} now shares its saves "
                f"({result.moved_files} file(s) moved{conflicts})."
            )
        return result

    def share_everything(self) -> list[tuple[Path, AdoptResult]]:
        """Adopt every prefix that is not shared yet, after one backup."""
        busy = self._busy_prefixes()
        pending = [
            p for p in self.all_prefixes() if p not in busy and self.needs_sharing(p)
        ]
        if not pending or not self.safety_backup("before sharing all prefixes"):
            return []
        done = []
        for prefix in pending:
            result = self.share(prefix, backup=False)
            if result is not None:
                done.append((prefix, result))
        return done

    # -- launching -----------------------------------------------------

    def before_launch(self, game: Game) -> None:
        """Repair links and share the prefix before a game runs."""
        prefix = self.prefix_of(game)
        if prefix in self._busy_prefixes():
            # Another game is running in it; leave it exactly as it is.
            return
        self._repair_links(prefix)
        if self._share_by_default:
            self.share(prefix)

    def _repair_links(self, prefix: Path) -> None:
        """Put back links Proton replaced, before the game runs.

        wineboot recreates missing user folders on a Proton update and
        replaces the symlinks with real directories, which quietly
        splits saves in two. Anything written into the replacement is
        merged back into the store first, so nothing is lost.
        """
        store = self._ctx.save_store
        try:
            if not store.verify(prefix):
                return
            self.safety_backup(f"before repairing {prefix.name}")
            result = store.repair(prefix)
        except OSError as e:
            self.error.emit("Shared Saves", f"Could not check the save links:\n{e}")
            return

        if result.errors:
            self.error.emit(
                "Shared Saves",
                "Some shared save folders could not be restored:\n"
                + "\n".join(result.errors[:5]),
            )
        elif result.did_work:
            recovered = (
                f", {result.recovered_files} new file(s) kept"
                if result.recovered_files
                else ""
            )
            self.status.emit(
                f"Restored {len(result.repaired)} shared save link(s){recovered}."
            )

    def _after_game(self, name: str, _exit_code: int) -> None:
        game = self._ctx.games.get(name)
        if game is not None and self._share_by_default:
            # A first run creates the prefix, and the game has just
            # written its saves into real folders: bring them in now.
            self.share(self.prefix_of(game))
        self.backup_if_due(f"after playing {name}")

    # -- backups -------------------------------------------------------

    def backup_due(self, now: datetime | None = None) -> bool:
        if not self._ctx.settings.get_bool("backup_auto"):
            return False
        latest = self._ctx.backups.latest()
        if latest is None:
            return True
        interval = timedelta(minutes=max(0, self._ctx.settings.get_int(
            "backup_interval_minutes"
        )))
        return (now or datetime.now()) - latest.created >= interval

    def backup_if_due(self, reason: str) -> None:
        if self._ctx.save_store.exists and self.backup_due():
            self.backup_in_background(reason)

    def safety_backup(self, reason: str) -> bool:
        """Snapshot now, before something rearranges the store.

        Returns False, having told the user, when the snapshot failed and
        the caller should not go ahead.
        """
        if not self._ctx.save_store.exists:
            return True  # Nothing to protect yet.
        try:
            self._ctx.backups.create(reason)
        except BackupError as e:
            self.error.emit(
                "Backup Failed",
                f"Did not continue, because the saves could not be backed "
                f"up first:\n{e}",
            )
            return False
        except OSError as e:
            self.error.emit("Backup Failed", str(e))
            return False
        self.backups_changed.emit()
        return True

    def backup_in_background(self, reason: str, *, pinned: bool = False) -> None:
        """Snapshot on a worker thread, reporting through status."""
        if self._ctx.backups.busy:
            return
        self._next_token += 1
        token = self._next_token
        signals = TaskSignals()
        signals.finished.connect(self._backup_done)
        signals.failed.connect(self._backup_failed)
        self._tasks[token] = signals
        self.status.emit("Backing up saves…")
        pool().start(
            Task(
                token,
                lambda: self._ctx.backups.create(reason, pinned=pinned),
                signals=signals,
            )
        )

    def _backup_done(self, token: int, snapshot: object) -> None:
        self._tasks.pop(token, None)
        if isinstance(snapshot, Snapshot):
            self.status.emit(
                f"Saves backed up: {snapshot.files} file(s), "
                f"{_human(snapshot.new_bytes)} changed."
            )
        self.backups_changed.emit()

    def _backup_failed(self, token: int, message: str) -> None:
        self._tasks.pop(token, None)
        self.error.emit("Backup Failed", message)


def _human(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
