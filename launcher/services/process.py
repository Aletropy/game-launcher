"""Running games, and timing how long they run for."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, Signal

from launcher.data.paths import Paths

_SHELL = "bash"

#: A session shorter than this is treated as a failed launch and does not
#: count towards playtime; Proton failing to start takes about a second.
MIN_SESSION_SECONDS = 20


@dataclass
class _Session:
    process: QProcess
    started_at: float


class ProcessService(QObject):
    """Launches games through milso-launcher.sh and tracks their lifetime."""

    game_started = Signal(str)
    #: name, exit code
    game_finished = Signal(str, int)
    #: name, text
    game_output = Signal(str, str)
    game_error = Signal(str, str)
    #: name, seconds played — only for sessions long enough to count.
    session_recorded = Signal(str, int)

    def __init__(self, paths: Paths, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paths = paths
        self._sessions: dict[str, _Session] = {}

    @property
    def running_games(self) -> list[str]:
        return list(self._sessions)

    def is_running(self, game_name: str) -> bool:
        return game_name in self._sessions

    def launch(self, game_name: str) -> bool:
        """Launch a game by name. Returns True if it started."""
        if self.is_running(game_name):
            return False

        script = self._paths.launcher_script
        if not script.is_file():
            self.game_error.emit(game_name, f"Launcher script not found: {script}")
            return False

        process = QProcess(self)
        process.setWorkingDirectory(str(self._paths.base))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda gn=game_name: self._on_output(gn)
        )
        process.finished.connect(
            lambda code, status, gn=game_name: self._on_finished(gn, code)
        )
        process.errorOccurred.connect(
            lambda err, gn=game_name: self._on_process_error(gn, err)
        )

        self._sessions[game_name] = _Session(process, time.monotonic())
        process.start(_SHELL, [str(script), game_name])
        if game_name not in self._sessions:
            # errorOccurred already fired synchronously; the entry was
            # cleaned up and no finished signal will follow.
            return False
        self.game_started.emit(game_name)
        return True

    def stop(self, game_name: str) -> bool:
        """Terminate a running game. Returns True if it was running."""
        session = self._sessions.get(game_name)
        if session is None:
            return False
        session.process.terminate()
        return True

    def stop_all(self) -> None:
        for name in list(self._sessions):
            self.stop(name)

    # -- process signals -----------------------------------------------

    def _on_output(self, game_name: str) -> None:
        session = self._sessions.get(game_name)
        if session is None:
            return
        raw = bytes(session.process.readAllStandardOutput().data())
        text = raw.decode("utf-8", errors="replace")
        if text:
            self.game_output.emit(game_name, text)

    def _on_process_error(
        self, game_name: str, error: QProcess.ProcessError
    ) -> None:
        session = self._sessions.get(game_name)
        if session is None:
            return
        if error == QProcess.ProcessError.FailedToStart:
            # No finished signal follows a failed start, so release the
            # slot here or the game stays "running" for the session.
            self._sessions.pop(game_name, None)
            self.game_error.emit(
                game_name,
                f"Failed to start milso-launcher.sh: {session.process.errorString()}",
            )
            self.game_finished.emit(game_name, -1)
        else:
            self.game_error.emit(game_name, session.process.errorString())

    def _on_finished(self, game_name: str, exit_code: int) -> None:
        session = self._sessions.pop(game_name, None)
        if session is not None:
            elapsed = int(time.monotonic() - session.started_at)
            if elapsed >= MIN_SESSION_SECONDS:
                self.session_recorded.emit(game_name, elapsed)
        self.game_finished.emit(game_name, exit_code)
