"""Recovered playtime: reopening shows still-running games as playing."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert proc.pid is not None
    # Reused pids are harmless here: even a live lookalike only feeds
    # pid_alive, and the test asserts on the entry it just wrote.
    return proc.pid


def register(*, test, qt_app, sandbox, pump):
    @test
    def reopening_recovers_live_game_with_elapsed_time() -> None:
        from launcher.app.context import AppContext
        from launcher.app.main import build_window
        from launcher.services import sessions as _sessions

        qt_app()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = AppContext.for_testing(root)
            try:
                _sessions.add_active(
                    first.paths,
                    "Hades",
                    datetime.now() - timedelta(hours=1),
                    os.getpid(),
                )
            finally:
                first.close()

            second = AppContext.for_testing(root)
            try:
                assert "Hades" in second.processes.running_games
                elapsed = second.processes.elapsed_seconds("Hades")
                assert 3500 <= elapsed <= 3700, elapsed
                # No launch recorded for a game that was already running.
                assert second.state.get("Hades").launch_count == 0

                window = build_window(second)
                try:
                    assert window._lib.is_running("Hades")
                    window.announce_recovered_sessions()
                    assert "Hades" in window.statusBar().currentMessage()
                    assert second.processes.reattached_games == []
                finally:
                    # A running game makes close() ask for confirmation;
                    # quit for real like the tray's Quit path does.
                    window._quitting = True
                    window.close()
            finally:
                if second.processes._poll_timer is not None:
                    second.processes._poll_timer.stop()
                second.close()

    @test
    def reattach_ignores_games_that_already_exited() -> None:
        from launcher.services import sessions as _sessions

        with sandbox() as ctx:
            _sessions.add_active(
                ctx.paths, "Gone", datetime.now(), _dead_pid()
            )
            assert ctx.processes.reattach_live() == []
            assert ctx.processes.running_games == []

    @test
    def reattached_finish_leaves_recording_to_the_watcher() -> None:
        from launcher.services import sessions as _sessions
        from launcher.services.process import _Session

        with sandbox() as ctx:
            processes = ctx.processes
            _sessions.add_active(ctx.paths, "Hades", datetime.now(), _dead_pid())
            # A reattached session has no QProcess of its own.
            processes._sessions["Hades"] = _Session(
                None, time.monotonic(), datetime.now(), _dead_pid(), None
            )
            recorded: list[tuple[str, int]] = []
            finished: list[tuple[str, int]] = []
            reattached: list[str] = []
            processes.session_recorded.connect(lambda n, s: recorded.append((n, s)))
            processes.game_finished.connect(lambda n, c: finished.append((n, c)))
            processes.reattached_finished.connect(reattached.append)

            processes._poll_reattached()
            assert "Hades" not in processes.running_games
            assert recorded == [], "the watcher owns this recording"
            assert finished == [("Hades", 0)]
            assert reattached == ["Hades"]
            # The disk entry stays: the watcher finalizes it on exit.
            assert "Hades" in _sessions.load_active(ctx.paths)

    @test
    def stopping_a_recovered_game_signals_but_does_not_record() -> None:
        from launcher.services import sessions as _sessions
        from launcher.services.process import _Session

        with sandbox() as ctx:
            processes = ctx.processes
            dead = _dead_pid()
            _sessions.add_active(ctx.paths, "Hades", datetime.now(), dead)
            processes._sessions["Hades"] = _Session(
                None, time.monotonic(), datetime.now(), dead, None
            )
            recorded: list[tuple[str, int]] = []
            processes.session_recorded.connect(lambda n, s: recorded.append((n, s)))

            assert processes.stop("Hades") is True
            assert recorded == []
            assert "Hades" not in processes.running_games
            assert "Hades" in _sessions.load_active(ctx.paths)

    @test
    def recorder_imports_the_watcher_sidecar_for_reattached() -> None:
        from launcher.app.session_recorder import SessionRecorder
        from launcher.services import sessions as _sessions

        with sandbox() as ctx:
            recorder = SessionRecorder(
                ctx,
                refresh_game=lambda _n: None,
                filter_shows_running=lambda: False,
                emit_library_changed=lambda: None,
            )
            messages: list[str] = []
            recorder.status.connect(messages.append)
            _sessions.write_pending(
                ctx.paths, "Hades", datetime.now() - timedelta(seconds=120), 120
            )
            recorder._on_reattached_finished("Hades")
            assert ctx.state.total_playtime(["Hades"]) == 120
            assert any("Hades" in m for m in messages), messages
