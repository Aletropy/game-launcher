"""Durable profiles: upgrade keeps logins, loss is recoverable."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time


def register(*, test, qt_app, sandbox, pump):
    @test
    def legacy_database_migrates_without_losing_logins() -> None:
        import tempfile
        from pathlib import Path

        from server.db import Store

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "friends.db"
            # A pre-v2 database: no devices table, user_version 1.
            conn = sqlite3.connect(str(db))
            conn.executescript(
                "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " display_name TEXT NOT NULL, friend_code TEXT NOT NULL UNIQUE,"
                " token_hash TEXT NOT NULL UNIQUE, created INTEGER NOT NULL,"
                " last_seen INTEGER NOT NULL);"
            )
            token = "legacy-token-abc"
            digest = hashlib.sha256(token.encode()).hexdigest()
            now = int(time.time())
            conn.execute(
                "INSERT INTO users (display_name, friend_code, token_hash, created, last_seen)"
                " VALUES (?,?,?,?,?)",
                ("Old", "AAAA-BBBB", digest, now, now),
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
            conn.close()

            store = Store(db)
            try:
                assert store.authenticate(token) is not None, "legacy token lost"
                assert len(store.list_devices(1)) >= 1
                assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 2
                backups = list(Path(d).glob("friends.db.pre-devices-*.bak"))
                assert backups, "no pre-migration backup"
                # Idempotent: reopening keeps working.
            finally:
                store.close()
            store = Store(db)
            try:
                assert store.authenticate(token) is not None
            finally:
                store.close()

    @test
    def auth_failure_parks_in_recovery_without_wiping() -> None:
        from launcher.domain.friends import FriendsState
        from launcher.services.friends import Account
        from launcher.services.friends_client import AuthError

        with sandbox() as ctx:
            ctx.settings.set("friends_mode", "online")
            service = ctx.friends
            service._account = Account(
                server="http://x", token="dead", user_id=7, client_id="c1", uploaded_through=42
            )
            service._started = True
            service._handle_error(AuthError("nope"), None)
            assert service.state is FriendsState.RECOVERY, service.state
            assert service.account.token == "dead", "token was wiped"
            assert service.account.uploaded_through == 42, "cursor was reset"
            assert service.account.client_id == "c1"

    @test
    def account_file_falls_back_to_backup() -> None:
        from launcher.data.paths import Paths
        from launcher.services.friends import Account, AccountFile

        with sandbox() as ctx:
            paths: Paths = ctx.paths
            store = AccountFile(paths)
            store.save(Account(server="http://x", token="t", user_id=1, client_id="c1"))
            # A second save banks the first as .bak; then corruption recovers.
            store.save(Account(server="http://x", token="t", user_id=1, client_id="c1"))
            # Corrupt the primary file; the .bak must save the login.
            paths.friends_file.write_text("{broken", encoding="utf-8")
            loaded = AccountFile(paths).load()
            assert loaded.token == "t", loaded
            assert loaded.client_id == "c1"

    @test
    def export_import_round_trips_cursor() -> None:
        import tempfile
        from pathlib import Path

        from launcher.data.paths import Paths
        from launcher.services.friends import Account, AccountFile

        with tempfile.TemporaryDirectory() as d:
            paths = Paths.for_testing(Path(d))
            paths.config.mkdir(parents=True, exist_ok=True)
            store = AccountFile(paths)
            account = Account(
                server="http://s:8765",
                token="tok",
                user_id=3,
                display_name="Ava",
                friend_code="XXXX-YYYY",
                client_id="c9",
                uploaded_through=17,
            )
            dest = Path(d) / "profile.json"
            store.export_profile(account, dest, server_url=account.server, recovery_key="rk")
            assert dest.stat().st_mode & 0o077 == 0, "export is readable"
            raw = json.loads(dest.read_text(encoding="utf-8"))
            assert raw["uploaded_through"] == 17 and raw["client_id"] == "c9"
            assert raw["recovery_key"] == "rk"
            back = AccountFile.read_export(dest)
            assert back["token"] == "tok"

    @test
    def reclaim_keeps_same_user_and_history() -> None:
        import tempfile
        from pathlib import Path

        from server.db import Store

        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "db.sqlite")
            try:
                user, token, recovery = store.register("Ava", "linux")
                store.upsert_sessions(
                    user.id,
                    [
                        __import__(
                            "server.db", fromlist=["SessionIn"]
                        ).SessionIn("c:1", "k", "G", 1, 60)
                    ],
                )
                found = store.reclaim(user.friend_code, recovery, "laptop")
                assert found is not None, "reclaim failed"
                user2, token2 = found
                assert user2.id == user.id, "reclaim minted a new user"
                assert user2.friend_code == user.friend_code
                assert store.authenticate(token) is not None, "old device logged out"
                assert store.authenticate(token2) is not None
                assert len(store.list_devices(user.id)) == 2
            finally:
                store.close()
