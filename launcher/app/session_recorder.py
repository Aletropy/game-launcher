"""Playtime recording, extracted from the library controller.

The controller owns games, filters and mutations; this owns what happens
when games run: launch counts, finished sessions with their exit codes
and crash assessments, and the transient status line. It emits
``launch_failed`` when a session looks like a crash so the window can
offer the failure card.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Signal

from launcher.app.context import AppContext
from launcher.domain.crash_signatures import CrashAssessment, assess


class SessionRecorder(QObject):
    """Records launches and finished sessions into the state store."""

    #: A transient status message.
    status = Signal(str)
    #: A finished session looks like a crash; carries the game name.
    launch_failed = Signal(str)

    def __init__(
        self,
        context: AppContext,
        *,
        refresh_game: Callable[[str], None],
        filter_shows_running: Callable[[], bool],
        emit_library_changed: Callable[[], None],
        last_log_tail: Callable[[str], str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._refresh_game = refresh_game
        self._filter_shows_running = filter_shows_running
        self._emit_library_changed = emit_library_changed
        self._last_log_tail = last_log_tail or (lambda _name: "")
        #: The latest crash assessment per game, for the failure card.
        self.last_crash: dict[str, CrashAssessment] = {}
        #: Launches whose playtime was already recorded this run.
        self._counted: set[str] = set()

        processes = context.processes
        processes.session_recorded.connect(self._on_session_recorded)
        processes.game_started.connect(self._on_game_started)
        processes.game_finished.connect(self._on_game_finished)

    # -- process signals -----------------------------------------------

    def _on_game_started(self, name: str) -> None:
        self._counted.discard(name)
        self._ctx.state.record_launch(name)
        self._refresh_game(name)
        if self._filter_shows_running():
            self._emit_library_changed()

    def _on_game_finished(self, name: str, exit_code: int) -> None:
        if self._filter_shows_running():
            self._emit_library_changed()
        if name in self._counted:
            return
        # Too short to count as playtime — but still worth diagnosing.
        seconds = self._ctx.processes.last_session_seconds(name) or 0
        assessment = assess(self._last_log_tail(name), exit_code, seconds)
        if assessment.crashed:
            self.last_crash[name] = assessment
            summary = assessment.summary or f"exited with code {exit_code}"
            self.status.emit(f"{name} failed to start ({summary}).")
            self.launch_failed.emit(name)

    def _on_session_recorded(self, name: str, seconds: int) -> None:
        self._counted.add(name)
        exit_code = self._ctx.processes.last_exit_code(name)
        if exit_code is None:
            exit_code = 0
        assessment = assess(self._last_log_tail(name), exit_code, seconds)
        self._ctx.state.add_playtime(name, seconds)
        self._ctx.state.record_session(
            name,
            datetime.now() - timedelta(seconds=seconds),
            seconds,
            exit_code=exit_code,
            crashed=assessment.crashed,
        )
        self._refresh_game(name)
        minutes = max(1, seconds // 60)
        if assessment.crashed:
            summary = assessment.summary or f"exited with code {exit_code}"
            self.last_crash[name] = assessment
            self.status.emit(f"{name} may have crashed ({summary}).")
            self.launch_failed.emit(name)
        else:
            self.status.emit(f"Recorded {minutes} min of playtime for {name}.")
