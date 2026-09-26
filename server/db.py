"""Storage for the friends server.

One SQLite connection shared by every request thread, behind a lock: the
traffic is a handful of launchers polling every half minute, and one
writer at a time is what SQLite wants anyway.
"""

from __future__ import annotations

import contextlib
import hashlib
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name  TEXT NOT NULL,
    friend_code   TEXT NOT NULL UNIQUE,
    token_hash    TEXT NOT NULL UNIQUE,
    created       INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS friend_requests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created    INTEGER NOT NULL,
    UNIQUE (from_user, to_user)
);

-- One row per pair, smaller id first.
CREATE TABLE IF NOT EXISTS friendships (
    user_a  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    since   INTEGER NOT NULL,
    PRIMARY KEY (user_a, user_b),
    CHECK (user_a < user_b)
);

CREATE TABLE IF NOT EXISTS sessions (
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_session_id  TEXT NOT NULL,
    game_key           TEXT NOT NULL,
    game_name          TEXT NOT NULL,
    started            INTEGER NOT NULL,
    seconds            INTEGER NOT NULL,
    PRIMARY KEY (user_id, client_session_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_started ON sessions(user_id, started);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON sessions(game_key);

CREATE TABLE IF NOT EXISTS presence (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    game_key   TEXT NOT NULL,
    game_name  TEXT NOT NULL,
    since      INTEGER NOT NULL,
    expires    INTEGER NOT NULL
);
"""

_MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN platform TEXT NOT NULL DEFAULT 'linux'",
    "ALTER TABLE presence ADD COLUMN platform TEXT NOT NULL DEFAULT 'linux'",
    "ALTER TABLE sessions ADD COLUMN platform TEXT NOT NULL DEFAULT 'linux'",
)

#: v2 adds devices + recovery_keys. users.token_hash is kept for one
#: release as a fallback so old clients/servers keep working, then dropped.
_USER_VERSION = 2

_DEVICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    device_name  TEXT NOT NULL DEFAULT 'legacy',
    created      INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);

CREATE TABLE IF NOT EXISTS recovery_keys (
    user_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    key_hash  TEXT NOT NULL UNIQUE,
    created   INTEGER NOT NULL
);
"""

#: Presence outlives its last heartbeat by this long; launchers beat
#: every minute, so a crashed launcher drops off within a few.
PRESENCE_TTL = 150
#: No codes that read alike: no 0/O, 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
#: Pending requests one user may have out at once.
MAX_OUTGOING = 50
TOP_GAMES = 5


class NotFoundError(Exception):
    """The thing asked for does not exist, or is not the caller's."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalise_code(raw: str) -> str:
    """'k7qx 29mb' -> 'K7QX-29MB'. Anything else comes back unchanged."""
    letters = "".join(ch for ch in raw.upper() if ch.isalnum())
    if len(letters) != 8:
        return raw.strip().upper()
    return f"{letters[:4]}-{letters[4:]}"


def _new_code() -> str:
    letters = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


@dataclass(frozen=True)
class User:
    id: int
    display_name: str
    friend_code: str
    platform: str = "linux"


@dataclass(frozen=True)
class SessionIn:
    """One uploaded session, already validated."""

    client_session_id: str
    game_key: str
    game_name: str
    started: int
    seconds: int
    platform: str = "linux"


#: Only these platform labels are stored; anything else becomes 'unknown'.
KNOWN_PLATFORMS = {"linux", "windows"}


def normalise_platform(raw: object) -> str:
    text = str(raw or "").strip().lower()
    return text if text in KNOWN_PLATFORMS else "unknown"


class Store:
    """Every read and write the API makes."""

    def __init__(self, path: Path | str) -> None:
        self._lock = threading.Lock()
        self._path = str(path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._conn.execute("PRAGMA user_version = 1")
            version = 1
        if version < 2:
            self._backup_before_devices_migration()
            self._migrate_devices()
            self._conn.execute("PRAGMA user_version = 2")
        self._conn.commit()

    def _migrate(self) -> None:
        """Add platform columns to older databases. Idempotent."""
        for statement in _MIGRATIONS:
            try:
                self._conn.execute(statement)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        self._conn.commit()

    def _backup_before_devices_migration(self) -> None:
        """Copy the DB file aside before the v2 migration, once."""
        import shutil
        import time as _time

        try:
            source = Path(self._path)
        except (TypeError, ValueError):
            return
        # :memory: and non-existent paths have nothing to back up.
        if not source.is_file():
            return
        if source.name == ":memory:":
            return
        stamp = _time.strftime("%Y-%m-%d_%H%M%S")
        target = source.parent / f"{source.name}.pre-devices-{stamp}.bak"
        suffix = 1
        while target.exists():
            suffix += 1
            target = source.parent / f"{source.name}.pre-devices-{stamp}-{suffix}.bak"
        try:
            # Checkpoint first so the copy is consistent even with WAL.
            with self._lock, contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            shutil.copy2(source, target)
        except OSError:
            pass

    def _migrate_devices(self) -> None:
        """Create devices + recovery tables and adopt legacy tokens.

        Idempotent: re-running copies any users.token_hash missing from
        devices, so upgrades never lose a login and never duplicate one.
        users.token_hash is kept for one release as a fallback.
        """
        with self._lock:
            self._conn.executescript(_DEVICE_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO devices"
                " (user_id, token_hash, device_name, created, last_seen)"
                " SELECT id, token_hash, 'legacy', created, last_seen FROM users"
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- accounts --------------------------------------------------------

    def register(
        self, display_name: str, platform: str = "linux", device_name: str = "this PC"
    ) -> tuple[User, str, str]:
        """A new user, its device token, and a once-only recovery key.

        The token and recovery key are not kept; only their hashes are.
        users.token_hash is still written for one release so downgraded
        servers keep working.
        """
        token = secrets.token_urlsafe(32)
        recovery_key = secrets.token_urlsafe(32)
        now = int(time.time())
        platform = normalise_platform(platform)
        with self._lock:
            while True:
                code = _new_code()
                try:
                    cursor = self._conn.execute(
                        "INSERT INTO users"
                        " (display_name, friend_code, token_hash, created, last_seen, platform)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (display_name, code, hash_token(token), now, now, platform),
                    )
                except sqlite3.IntegrityError:
                    continue  # A code collision; draw again.
                break
            assert cursor.lastrowid is not None
            user_id = int(cursor.lastrowid)
            self._conn.execute(
                "INSERT INTO devices"
                " (user_id, token_hash, device_name, created, last_seen)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, hash_token(token), device_name or "this PC", now, now),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO recovery_keys (user_id, key_hash, created)"
                " VALUES (?, ?, ?)",
                (user_id, hash_token(recovery_key), now),
            )
            self._conn.commit()
        return User(user_id, display_name, code, platform), token, recovery_key

    def authenticate(self, token: str) -> User | None:
        now = int(time.time())
        digest = hash_token(token)
        with self._lock:
            row = self._conn.execute(
                "SELECT u.id, u.display_name, u.friend_code,"
                " COALESCE(u.platform, 'linux') AS platform FROM devices d"
                " JOIN users u ON u.id = d.user_id WHERE d.token_hash = ?",
                (digest,),
            ).fetchone()
            if row is None:
                # Fallback for one release: pre-v2 tokens living only in
                # users.token_hash (e.g. DB restored from backup mid-rollout).
                row = self._conn.execute(
                    "SELECT id, display_name, friend_code,"
                    " COALESCE(platform, 'linux') AS platform FROM users"
                    " WHERE token_hash = ?",
                    (digest,),
                ).fetchone()
                if row is None:
                    return None
                # Adopt it so the next login hits devices directly.
                with contextlib.suppress(sqlite3.OperationalError):
                    self._conn.execute(
                        "INSERT OR IGNORE INTO devices"
                        " (user_id, token_hash, device_name, created, last_seen)"
                        " VALUES (?, ?, 'legacy', ?, ?)",
                        (row["id"], digest, now, now),
                    )
            else:
                self._conn.execute(
                    "UPDATE devices SET last_seen = ? WHERE token_hash = ?", (now, digest)
                )
            self._conn.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now, row["id"]))
            self._conn.commit()
        return User(row["id"], row["display_name"], row["friend_code"], row["platform"])

    def rename(self, user_id: int, display_name: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id)
            )
            self._conn.commit()

    def delete_user(self, user_id: int) -> None:
        """Remove a user and, through the cascades, everything of theirs."""
        with self._lock:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self._conn.commit()

    # -- admin: listing ----------------------------------------------------

    def list_users(self, limit: int = 100, order: str = "last_seen") -> list[dict[str, Any]]:
        """All users for the admin CLI. Never includes token hashes."""
        queries = {
            "last_seen": "SELECT id, display_name, friend_code, created, last_seen,"
            " COALESCE(platform, 'linux') AS platform FROM users"
            " ORDER BY last_seen DESC LIMIT ?",
            "created": "SELECT id, display_name, friend_code, created, last_seen,"
            " COALESCE(platform, 'linux') AS platform FROM users"
            " ORDER BY created DESC LIMIT ?",
            "name": "SELECT id, display_name, friend_code, created, last_seen,"
            " COALESCE(platform, 'linux') AS platform FROM users"
            " ORDER BY display_name ASC LIMIT ?",
        }
        query = queries.get(order, queries["last_seen"])
        with self._lock:
            rows = self._conn.execute(
                query,
                (max(1, min(limit, 10000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_users(self, text: str, limit: int = 50) -> list[dict[str, Any]]:
        """Find users by name fragment or exact friend code."""
        code = normalise_code(text)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, display_name, friend_code, created, last_seen,"
                " COALESCE(platform, 'linux') AS platform FROM users"
                " WHERE display_name LIKE ? ESCAPE '\\' OR friend_code = ?"
                " ORDER BY last_seen DESC LIMIT ?",
                (f"%{text.replace('%', '').replace('_', '')}%", code, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user(self, ref: str) -> dict[str, Any] | None:
        """One user by id or friend code, with device/session/friend counts."""
        with self._lock:
            row: sqlite3.Row | None = None
            if ref.isdigit():
                row = self._conn.execute(
                    "SELECT id, display_name, friend_code, created, last_seen,"
                    " COALESCE(platform, 'linux') AS platform FROM users WHERE id = ?",
                    (int(ref),),
                ).fetchone()
            if row is None:
                row = self._conn.execute(
                    "SELECT id, display_name, friend_code, created, last_seen,"
                    " COALESCE(platform, 'linux') AS platform FROM users"
                    " WHERE friend_code = ?",
                    (normalise_code(ref),),
                ).fetchone()
            if row is None:
                return None
            user_id = int(row["id"])
            try:
                devices = int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM devices WHERE user_id = ?", (user_id,)
                    ).fetchone()[0]
                )
            except sqlite3.OperationalError:
                devices = 1
            sessions = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)
                ).fetchone()[0]
            )
            friends = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM friendships WHERE user_a = ? OR user_b = ?",
                    (user_id, user_id),
                ).fetchone()[0]
            )
        return {**dict(row), "devices": devices, "sessions": sessions, "friends": friends}

    # -- devices + recovery ------------------------------------------------

    def list_devices(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT id, device_name, created, last_seen FROM devices"
                    " WHERE user_id = ? ORDER BY last_seen DESC",
                    (user_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                return [{"id": 0, "device_name": "legacy", "created": 0, "last_seen": 0}]
        return [dict(row) for row in rows]

    def _add_device(self, user_id: int, token: str, device_name: str) -> int:
        now = int(time.time())
        cursor = self._conn.execute(
            "INSERT INTO devices (user_id, token_hash, device_name, created, last_seen)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, hash_token(token), device_name or "new device", now, now),
        )
        return int(cursor.lastrowid or 0)

    def revoke_device(self, user_id: int, device_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM devices WHERE id = ? AND user_id = ?", (device_id, user_id)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def issue_recovery(self, user_id: int) -> str:
        """Mint a fresh recovery key, replacing the old one. Returns it once."""
        key = secrets.token_urlsafe(32)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO recovery_keys (user_id, key_hash, created)"
                " VALUES (?, ?, ?)",
                (user_id, hash_token(key), int(time.time())),
            )
            self._conn.commit()
        return key

    def reset_token(self, ref: str, device_name: str = "recovery") -> tuple[User, str] | None:
        """Admin/clinical re-issue: a new device token for the same user.

        Keeps user_id, friend_code, friends and sessions. Returns the user
        and the once-only plaintext token.
        """
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._lock:
            row: sqlite3.Row | None = None
            if ref.isdigit():
                row = self._conn.execute(
                    "SELECT id, display_name, friend_code,"
                    " COALESCE(platform, 'linux') AS platform FROM users WHERE id = ?",
                    (int(ref),),
                ).fetchone()
            if row is None:
                row = self._conn.execute(
                    "SELECT id, display_name, friend_code,"
                    " COALESCE(platform, 'linux') AS platform FROM users"
                    " WHERE friend_code = ?",
                    (normalise_code(ref),),
                ).fetchone()
            if row is None:
                return None
            user_id = int(row["id"])
            self._conn.execute(
                "INSERT INTO devices (user_id, token_hash, device_name, created, last_seen)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, hash_token(token), device_name, now, now),
            )
            # Keep the legacy column working for one release.
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute(
                    "UPDATE users SET token_hash = ?, last_seen = ? WHERE id = ?",
                    (hash_token(token), now, user_id),
                )
            self._conn.commit()
        return User(user_id, row["display_name"], row["friend_code"], row["platform"]), token

    def reclaim(
        self, code: str, recovery_key: str, device_name: str = "new device"
    ) -> tuple[User, str] | None:
        """Self-service restore: friend_code + recovery key -> new device token."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, display_name, friend_code,"
                " COALESCE(platform, 'linux') AS platform FROM users WHERE friend_code = ?",
                (normalise_code(code),),
            ).fetchone()
            if row is None:
                return None
            user_id = int(row["id"])
            try:
                stored = self._conn.execute(
                    "SELECT key_hash FROM recovery_keys WHERE user_id = ?", (user_id,)
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            if stored is None or stored["key_hash"] != hash_token(recovery_key):
                return None
            token = secrets.token_urlsafe(32)
            now = int(time.time())
            self._conn.execute(
                "INSERT INTO devices (user_id, token_hash, device_name, created, last_seen)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, hash_token(token), device_name or "new device", now, now),
            )
            self._conn.commit()
        return User(user_id, row["display_name"], row["friend_code"], row["platform"]), token

    # -- friendships -----------------------------------------------------

    def _are_friends(self, a: int, b: int) -> bool:
        low, high = sorted((a, b))
        row = self._conn.execute(
            "SELECT 1 FROM friendships WHERE user_a = ? AND user_b = ?", (low, high)
        ).fetchone()
        return row is not None

    def _befriend(self, a: int, b: int) -> None:
        low, high = sorted((a, b))
        self._conn.execute(
            "INSERT OR IGNORE INTO friendships (user_a, user_b, since) VALUES (?, ?, ?)",
            (low, high, int(time.time())),
        )
        self._conn.execute(
            "DELETE FROM friend_requests WHERE (from_user = ? AND to_user = ?)"
            " OR (from_user = ? AND to_user = ?)",
            (a, b, b, a),
        )

    def send_request(self, from_user: int, code: str) -> None:
        """Ask someone to be friends. Silent about whether the code exists.

        A request the other way round already waiting counts as their
        answer, so two people adding each other become friends at once.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM users WHERE friend_code = ?", (normalise_code(code),)
            ).fetchone()
            if row is None or row["id"] == from_user:
                return
            to_user = row["id"]
            if self._are_friends(from_user, to_user):
                return
            reverse = self._conn.execute(
                "SELECT 1 FROM friend_requests WHERE from_user = ? AND to_user = ?",
                (to_user, from_user),
            ).fetchone()
            if reverse is not None:
                self._befriend(from_user, to_user)
            else:
                outgoing = self._conn.execute(
                    "SELECT COUNT(*) FROM friend_requests WHERE from_user = ?", (from_user,)
                ).fetchone()[0]
                if outgoing >= MAX_OUTGOING:
                    return
                self._conn.execute(
                    "INSERT OR IGNORE INTO friend_requests (from_user, to_user, created)"
                    " VALUES (?, ?, ?)",
                    (from_user, to_user, int(time.time())),
                )
            self._conn.commit()

    def requests(self, user_id: int) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            incoming = self._conn.execute(
                "SELECT r.id, r.created, u.display_name FROM friend_requests r"
                " JOIN users u ON u.id = r.from_user WHERE r.to_user = ?"
                " ORDER BY r.created",
                (user_id,),
            ).fetchall()
            outgoing = self._conn.execute(
                "SELECT r.id, r.created, u.display_name FROM friend_requests r"
                " JOIN users u ON u.id = r.to_user WHERE r.from_user = ?"
                " ORDER BY r.created",
                (user_id,),
            ).fetchall()
        return {
            "incoming": [dict(row) for row in incoming],
            "outgoing": [dict(row) for row in outgoing],
        }

    def answer_request(self, user_id: int, request_id: int, *, accept: bool) -> None:
        """Accept or decline a request made to this user."""
        with self._lock:
            row = self._conn.execute(
                "SELECT from_user FROM friend_requests WHERE id = ? AND to_user = ?",
                (request_id, user_id),
            ).fetchone()
            if row is None:
                raise NotFoundError
            if accept:
                self._befriend(user_id, row["from_user"])
            else:
                self._conn.execute("DELETE FROM friend_requests WHERE id = ?", (request_id,))
            self._conn.commit()

    def cancel_request(self, user_id: int, request_id: int) -> None:
        """Withdraw a request this user sent."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM friend_requests WHERE id = ? AND from_user = ?",
                (request_id, user_id),
            )
            self._conn.commit()
        if not cursor.rowcount:
            raise NotFoundError

    def unfriend(self, user_id: int, other: int) -> None:
        low, high = sorted((user_id, other))
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM friendships WHERE user_a = ? AND user_b = ?", (low, high)
            )
            self._conn.commit()
        if not cursor.rowcount:
            raise NotFoundError

    def _friend_ids(self, user_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT user_b AS id FROM friendships WHERE user_a = ?"
            " UNION SELECT user_a FROM friendships WHERE user_b = ?",
            (user_id, user_id),
        ).fetchall()
        return [row["id"] for row in rows]

    # -- presence --------------------------------------------------------

    def set_presence(
        self, user_id: int, game_key: str, game_name: str, platform: str = "linux"
    ) -> None:
        """Say a user is playing. Keeps the start time across heartbeats."""
        now = int(time.time())
        platform = normalise_platform(platform)
        with self._lock:
            row = self._conn.execute(
                "SELECT game_key, since, expires FROM presence WHERE user_id = ?", (user_id,)
            ).fetchone()
            same = row is not None and row["game_key"] == game_key and row["expires"] > now
            since = row["since"] if same else now
            self._conn.execute(
                "INSERT OR REPLACE INTO presence"
                " (user_id, game_key, game_name, since, expires, platform)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, game_key, game_name, since, now + PRESENCE_TTL, platform),
            )
            self._conn.commit()

    def clear_presence(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM presence WHERE user_id = ?", (user_id,))
            self._conn.commit()

    # -- sessions --------------------------------------------------------

    def upsert_sessions(self, user_id: int, sessions: Iterable[SessionIn]) -> int:
        rows = [
            (
                user_id,
                s.client_session_id,
                s.game_key,
                s.game_name,
                s.started,
                s.seconds,
                normalise_platform(s.platform),
            )
            for s in sessions
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO sessions"
                " (user_id, client_session_id, game_key, game_name, started,"
                " seconds, platform)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    def delete_sessions(self, user_id: int, game_keys: list[str] | None) -> int:
        """Forget some games' history, or all of it when game_keys is None."""
        with self._lock:
            if game_keys is None:
                cursor = self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            else:
                cursor = self._conn.executemany(
                    "DELETE FROM sessions WHERE user_id = ? AND game_key = ?",
                    [(user_id, key) for key in game_keys],
                )
            self._conn.commit()
        return cursor.rowcount

    # -- what friends see -----------------------------------------------

    def _seconds(self, user_id: int, since: int | None, game_key: str | None = None) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) FROM sessions WHERE user_id = ?1"
            " AND (?2 IS NULL OR started >= ?2) AND (?3 IS NULL OR game_key = ?3)",
            (user_id, since, game_key),
        ).fetchone()
        return int(row[0])

    def _top_games(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT game_key, MAX(game_name) AS game_name, SUM(seconds) AS seconds"
            " FROM sessions WHERE user_id = ? GROUP BY game_key"
            " ORDER BY seconds DESC LIMIT ?",
            (user_id, TOP_GAMES),
        ).fetchall()
        return [dict(row) for row in rows]

    def _presence(self, user_id: int, now: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT game_key, game_name, since,"
            " COALESCE(platform, 'linux') AS platform FROM presence"
            " WHERE user_id = ? AND expires > ?",
            (user_id, now),
        ).fetchone()
        return dict(row) if row else None

    def _profile(self, user_id: int, since: int | None, now: int) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT id, display_name, last_seen,"
            " COALESCE(platform, 'linux') AS platform FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return {
            "user_id": row["id"],
            "display_name": row["display_name"],
            "last_seen": row["last_seen"],
            "platform": row["platform"],
            "presence": self._presence(user_id, now),
            "week_seconds": self._seconds(user_id, since) if since is not None else 0,
            "total_seconds": self._seconds(user_id, None),
            "top_games": self._top_games(user_id),
        }

    def overview(self, user: User, since: int | None) -> dict[str, Any]:
        """The caller and each of their friends, and the games among them."""
        now = int(time.time())
        with self._lock:
            ids = self._friend_ids(user.id)
            friends = [self._profile(i, since, now) for i in ids]
            me = self._profile(user.id, since, now)
            circle = [user.id, *ids]
            marks = ",".join("?" * len(circle))
            games = self._conn.execute(
                "SELECT game_key, MAX(game_name) AS game_name,"  # noqa: S608 - placeholders only
                " COUNT(DISTINCT user_id) AS players FROM sessions"
                f" WHERE user_id IN ({marks}) GROUP BY game_key"
                " ORDER BY players DESC, game_name",
                circle,
            ).fetchall()
        me["friend_code"] = user.friend_code
        friends.sort(key=lambda f: (f["presence"] is None, -f["week_seconds"]))
        return {"me": me, "friends": friends, "games": [dict(row) for row in games]}

    def leaderboard(
        self, user: User, since: int | None, game_key: str | None
    ) -> list[dict[str, Any]]:
        """The caller and their friends, most played first."""
        with self._lock:
            circle = [user.id, *self._friend_ids(user.id)]
            rows = []
            for member in circle:
                name = self._conn.execute(
                    "SELECT display_name FROM users WHERE id = ?", (member,)
                ).fetchone()["display_name"]
                rows.append(
                    {
                        "user_id": member,
                        "display_name": name,
                        "seconds": self._seconds(member, since, game_key),
                        "is_me": member == user.id,
                    }
                )
        if game_key is not None:
            # A game ranking lists who plays it, not everyone at zero.
            rows = [r for r in rows if r["seconds"] > 0]
        rows.sort(key=lambda r: (-r["seconds"], r["display_name"].lower()))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows
