"""Session persistence: locking, recovery, import and row management."""

from __future__ import annotations

import tempfile
import threading
from datetime import datetime
from pathlib import Path


def register(*, test, qt_app, sandbox, pump):
    @test
    def concurrent_session_writers_keep_every_game() -> None:
        from launcher.app.context import AppContext

        qt_app()
        with tempfile.TemporaryDirectory() as d:
            ctx = AppContext.for_testing(Path(d))
            try:
                from launcher.services import sessions as _sessions

                def add(i: int) -> None:
                    _sessions.add_active(
                        ctx.paths, f"Game-{i}", datetime.now(), pid=1000 + i
                    )

                threads = [threading.Thread(target=add, args=(i,)) for i in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                assert len(_sessions.load_active(ctx.paths)) == 8
            finally:
                ctx.close()

    @test
    def session_rows_delete_and_update_consistently() -> None:
        with sandbox() as ctx:
            state = ctx.state
            started = datetime(2026, 9, 1, 20, 0)
            first = state.record_session("Alpha", started, 3600)
            second = state.record_session("Alpha", started, 600)
            assert first and second and first != second
            state.add_playtime("Alpha", 4200)

            rows = state.sessions_with_ids("Alpha")
            assert [r[0] for r in rows] == sorted(r[0] for r in rows)
            assert state.delete_session(999999) is None
            assert state.delete_session(first) == ("Alpha", 3600)
            assert state.total_playtime(["Alpha"]) == 600, state.total_playtime(["Alpha"])

            assert state.update_session(second, started, 1200)
            assert state.total_playtime(["Alpha"]) == 1200
            assert not state.update_session(second, started, 0)
            assert not state.update_session(999999, started, 60)

    @test
    def session_schema_v3_migrates_old_databases() -> None:
        import sqlite3

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "CREATE TABLE game_state (name TEXT PRIMARY KEY,"
                " favorite INTEGER NOT NULL DEFAULT 0,"
                " playtime_seconds INTEGER NOT NULL DEFAULT 0,"
                " last_played TEXT, added TEXT,"
                " launch_count INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute(
                "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name TEXT, started TEXT, seconds INTEGER, imported INTEGER)"
            )
            conn.execute(
                "INSERT INTO sessions (name, started, seconds, imported)"
                " VALUES ('X', '2026-09-01T20:00:00', 60, 0)"
            )
            conn.commit()
            conn.close()

            from launcher.data.state_store import StateStore

            store = StateStore(db)
            try:
                rows = store.sessions_with_ids("X")
                assert len(rows) == 1
                assert rows[0][1].exit_code == 0 and not rows[0][1].crashed
                assert store.record_session("X", datetime(2026, 9, 2), 30, exit_code=2) > 0
            finally:
                store.close()
