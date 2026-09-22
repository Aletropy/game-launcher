"""Active and pending play sessions on disk.

The launcher used to keep running games only in memory: quitting while a
game ran lost the tail of its playtime. Now every launch is written to
``active-sessions.json`` (wall-clock start + pid) and a detached watcher
writes a sidecar into ``sessions-pending/`` when the game exits. The next
start — or the still-running app — imports those sidecars into the state
database, so the full session counts even if the window was closed or the
app quit.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from launcher.data.paths import Paths


def _to_iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _from_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def pid_alive(pid: object) -> bool:
    """True if a process with this pid exists (and we may not signal it)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


def _lock_path(paths: Paths) -> Path:
    return paths.data / ".active-sessions.lock"


@contextlib.contextmanager
def _locked(paths: Paths, exclusive: bool) -> Iterator[None]:
    """Serialize access to the active-sessions file.

    The main app and detached watchers read-modify-write the same file;
    without a lock one writer's update silently discards the other's.
    """
    lock_path = _lock_path(paths)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            )
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Locking is best-effort (e.g. exotic filesystems); the atomic
        # tmp+replace write below still protects against torn files.
        yield


def load_active(paths: Paths) -> dict[str, dict[str, Any]]:
    """The persisted running games, keyed by game name."""
    with _locked(paths, exclusive=False):
        return _load_active_unlocked(paths)


def _load_active_unlocked(paths: Paths) -> dict[str, dict[str, Any]]:
    path = paths.active_sessions_file
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(stored, dict):
        return {}
    active: dict[str, dict[str, Any]] = {}
    for name, entry in stored.items():
        if isinstance(name, str) and isinstance(entry, dict):
            active[name] = dict(entry)
    return active


def _save_active(paths: Paths, active: dict[str, dict[str, Any]]) -> None:
    path = paths.active_sessions_file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(active, indent=2), encoding="utf-8")
    tmp.replace(path)


def add_active(
    paths: Paths,
    name: str,
    started: datetime,
    pid: int | None,
    watcher_pid: int | None = None,
) -> None:
    """Remember a launch. Overwrites any stale entry for the same game."""
    with _locked(paths, exclusive=True):
        active = _load_active_unlocked(paths)
        active[name] = {
            "started_iso": _to_iso(started),
            "pid": pid,
            "watcher_pid": watcher_pid,
        }
        _save_active(paths, active)


def update_active(paths: Paths, name: str, **fields: Any) -> None:
    """Patch fields of one active entry, leaving it if it is gone."""
    with _locked(paths, exclusive=True):
        active = _load_active_unlocked(paths)
        entry = active.get(name)
        if entry is None:
            return
        entry.update(fields)
        _save_active(paths, active)


def remove_active(paths: Paths, name: str, started_iso: str | None = None) -> bool:
    """Forget a game. With started_iso, only removes a matching launch.

    The guard stops a watcher from deleting a newer session that reused
    the game name while the old game was exiting.
    """
    with _locked(paths, exclusive=True):
        active = _load_active_unlocked(paths)
        entry = active.get(name)
        if entry is None:
            return False
        if started_iso is not None and entry.get("started_iso") != started_iso:
            return False
        del active[name]
        _save_active(paths, active)
        return True


def _safe_stem(name: str, started_iso: str) -> str:
    keep = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
    stamp = started_iso.replace(":", "").replace("-", "").replace("T", "_")
    return f"{keep[:60]}-{stamp}"


def write_pending(
    paths: Paths, name: str, started: datetime, seconds: int
) -> Path | None:
    """Record a finished session for later import. Returns the sidecar."""
    if seconds <= 0 or not name:
        return None
    directory = paths.pending_sessions_dir
    directory.mkdir(parents=True, exist_ok=True)
    started_iso = _to_iso(started)
    target = directory / f"{_safe_stem(name, started_iso)}.json"
    suffix = 1
    while target.exists():
        suffix += 1
        target = directory / f"{_safe_stem(name, started_iso)}-{suffix}.json"
    payload = {
        "name": name,
        "started_iso": started_iso,
        "ended_iso": _to_iso(datetime.now()),
        "seconds": int(seconds),
    }
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def read_pending(paths: Paths) -> list[tuple[Path, dict[str, Any]]]:
    """Sidecars waiting to be imported, oldest first."""
    directory = paths.pending_sessions_dir
    if not directory.is_dir():
        return []
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict):
            found.append((path, payload))
    return found


def import_pending(state: Any, paths: Paths) -> list[tuple[str, int]]:
    """Move finished sidecars into the state database.

    Takes any object with ``add_playtime(name, seconds)`` and
    ``record_session(name, started, seconds)`` so tests can pass a fake.
    Corrupt sidecars are deleted; only valid, positive sessions count.
    """
    imported: list[tuple[str, int]] = []
    for path, payload in read_pending(paths):
        try:
            name = payload.get("name")
            seconds = int(payload.get("seconds", 0))
            started = _from_iso(payload.get("started_iso"))
            if not isinstance(name, str) or not name or seconds <= 0 or started is None:
                path.unlink(missing_ok=True)
                continue
            state.add_playtime(name, seconds)
            state.record_session(name, started, seconds)
            imported.append((name, seconds))
            path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
    return imported


def recover_active(paths: Paths, min_seconds: int) -> list[tuple[str, int]]:
    """Finalize launches whose game process is already dead.

    Writes a pending sidecar (if long enough) and drops the active entry,
    so a crash or a kill never leaves a game "running" forever. Returns
    the sessions that were finalized. Live games are left for the watcher.
    """
    finalized: list[tuple[str, int]] = []
    for name, entry in list(load_active(paths).items()):
        started = _from_iso(entry.get("started_iso"))
        if started is None:
            remove_active(paths, name)
            continue
        if pid_alive(entry.get("pid")):
            continue
        seconds = int((datetime.now() - started).total_seconds())
        if seconds >= min_seconds:
            write_pending(paths, name, started, seconds)
            finalized.append((name, seconds))
        remove_active(paths, name, entry.get("started_iso"))
    return finalized
