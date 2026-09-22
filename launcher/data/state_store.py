"""Per-game state: favourites, playtime, last played, added date.

Backed by SQLite so the library can be ordered by any of it without
rewriting a whole JSON file on every change.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from launcher.domain.journal import Session
from launcher.domain.models import GameStats

_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_state (
    name              TEXT PRIMARY KEY,
    favorite          INTEGER NOT NULL DEFAULT 0,
    playtime_seconds  INTEGER NOT NULL DEFAULT 0,
    last_played       TEXT,
    added             TEXT,
    launch_count      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_last_played ON game_state(last_played);

CREATE TABLE IF NOT EXISTS sessions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    started   TEXT NOT NULL,
    seconds   INTEGER NOT NULL,
    -- 1 for history reconstructed from totals, whose date is approximate.
    imported  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started);
CREATE INDEX IF NOT EXISTS idx_sessions_name ON sessions(name);
"""

#: Bumped when the schema changes; see _migrate.
_USER_VERSION = 2


def _to_iso(when: datetime | None) -> str | None:
    return None if when is None else when.isoformat(timespec="seconds")


def _from_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class StateStore:
    """Reads and writes per-game state."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 2:
            self._backfill_sessions()
        if version < _USER_VERSION:
            self._conn.execute(f"PRAGMA user_version = {_USER_VERSION}")

    def _backfill_sessions(self) -> None:
        """Give playtime recorded before sessions existed a history.

        Only totals were kept, so each game gets one session of its whole
        playtime on the day it was last played. It is marked imported, so
        the journal can say its date is approximate rather than pretend.
        """
        existing = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        if existing:
            return
        rows = self._conn.execute(
            "SELECT name, playtime_seconds, last_played FROM game_state"
            " WHERE playtime_seconds > 0 AND last_played IS NOT NULL"
        ).fetchall()
        self._conn.executemany(
            "INSERT INTO sessions (name, started, seconds, imported)"
            " VALUES (?, ?, ?, 1)",
            [(r["name"], r["last_played"], r["playtime_seconds"]) for r in rows],
        )

    def close(self) -> None:
        self._conn.close()

    # -- reads ---------------------------------------------------------

    def get(self, name: str) -> GameStats:
        row = self._conn.execute(
            "SELECT * FROM game_state WHERE name = ?", (name,)
        ).fetchone()
        return self._row_to_stats(row) if row else GameStats()

    def all_stats(self) -> dict[str, GameStats]:
        """Every stored row, keyed by game name."""
        rows = self._conn.execute("SELECT * FROM game_state").fetchall()
        return {row["name"]: self._row_to_stats(row) for row in rows}

    @staticmethod
    def _row_to_stats(row: sqlite3.Row) -> GameStats:
        return GameStats(
            favorite=bool(row["favorite"]),
            playtime_seconds=int(row["playtime_seconds"]),
            last_played=_from_iso(row["last_played"]),
            added=_from_iso(row["added"]),
            launch_count=int(row["launch_count"]),
        )

    # -- writes --------------------------------------------------------

    def _ensure_row(self, name: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO game_state (name, added) VALUES (?, ?)",
            (name, _to_iso(datetime.now())),
        )

    def set_favorite(self, name: str, favorite: bool) -> None:
        self._ensure_row(name)
        self._conn.execute(
            "UPDATE game_state SET favorite = ? WHERE name = ?",
            (1 if favorite else 0, name),
        )
        self._conn.commit()

    def toggle_favorite(self, name: str) -> bool:
        """Flip the favourite flag and return the new value."""
        new_value = not self.get(name).favorite
        self.set_favorite(name, new_value)
        return new_value

    def record_launch(self, name: str, when: datetime | None = None) -> None:
        """Note that a game was started."""
        self._ensure_row(name)
        self._conn.execute(
            "UPDATE game_state SET last_played = ?, launch_count = launch_count + 1"
            " WHERE name = ?",
            (_to_iso(when or datetime.now()), name),
        )
        self._conn.commit()

    def add_playtime(self, name: str, seconds: int) -> None:
        """Add a finished session's duration."""
        if seconds <= 0:
            return
        self._ensure_row(name)
        self._conn.execute(
            "UPDATE game_state SET playtime_seconds = playtime_seconds + ?"
            " WHERE name = ?",
            (int(seconds), name),
        )
        self._conn.commit()

    def mark_added(self, name: str, when: datetime | None = None) -> None:
        self._ensure_row(name)
        self._conn.execute(
            "UPDATE game_state SET added = COALESCE(added, ?) WHERE name = ?",
            (_to_iso(when or datetime.now()), name),
        )
        self._conn.commit()

    def rename(self, old_name: str, new_name: str) -> None:
        """Carry a game's state and history across a rename."""
        self._conn.execute(
            "UPDATE OR REPLACE game_state SET name = ? WHERE name = ?",
            (new_name, old_name),
        )
        self._conn.execute(
            "UPDATE sessions SET name = ? WHERE name = ?", (new_name, old_name)
        )
        self._conn.commit()

    def remove(self, name: str) -> None:
        self._conn.execute("DELETE FROM game_state WHERE name = ?", (name,))
        self._conn.execute("DELETE FROM sessions WHERE name = ?", (name,))
        self._conn.commit()

    # -- sessions --------------------------------------------------------

    def record_session(self, name: str, started: datetime, seconds: int) -> None:
        """Note one finished play session."""
        if seconds <= 0:
            return
        self._conn.execute(
            "INSERT INTO sessions (name, started, seconds) VALUES (?, ?, ?)",
            (name, _to_iso(started), int(seconds)),
        )
        self._conn.commit()

    def sessions(self, since: datetime | None = None) -> list[Session]:
        """Play sessions, oldest first, optionally from a date on."""
        query = "SELECT name, started, seconds, imported FROM sessions"
        params: tuple = ()
        if since is not None:
            query += " WHERE started >= ?"
            params = (_to_iso(since),)
        rows = self._conn.execute(query + " ORDER BY started", params).fetchall()
        sessions: list[Session] = []
        for row in rows:
            started = _from_iso(row["started"])
            if started is None:
                continue
            sessions.append(
                Session(
                    name=row["name"],
                    started=started,
                    seconds=int(row["seconds"]),
                    imported=bool(row["imported"]),
                )
            )
        return sessions

    def prune(self, known: set[str]) -> int:
        """Drop rows for games that no longer exist. Returns how many."""
        rows = self._conn.execute("SELECT name FROM game_state").fetchall()
        stale = [row["name"] for row in rows if row["name"] not in known]
        if stale:
            self._conn.executemany(
                "DELETE FROM game_state WHERE name = ?", [(n,) for n in stale]
            )
            self._conn.commit()
        return len(stale)

    # -- migration -----------------------------------------------------

    def import_legacy_favorites(self, favorites_file: Path) -> int:
        """Take favourites from the pre-database JSON file.

        Runs once: the file is left in place but only read while no
        favourite has been recorded yet, so re-running cannot resurrect
        a favourite the user has since removed.
        """
        if not favorites_file.is_file():
            return 0
        already = self._conn.execute(
            "SELECT COUNT(*) FROM game_state WHERE favorite = 1"
        ).fetchone()[0]
        if already:
            return 0
        try:
            names = json.loads(favorites_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        if not isinstance(names, list):
            return 0
        for name in names:
            if isinstance(name, str):
                self.set_favorite(name, True)
        return len(names)
