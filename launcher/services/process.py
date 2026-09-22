"""Running games, and timing how long they run for."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, QProcess, Signal

from launcher.data.paths import Paths

_SHELL = "bash"

#: A session shorter than this is treated as a failed launch and does not
#: count towards playtime; Proton failing to start takes about a second.
MIN_SESSION_SECONDS = 20


@dataclass
class _Session:
    process: QProcess | None
    started_at: float
    started_wall: datetime = field(default_factory=datetime.now)
    pid: int | None = None
    watcher_pid: int | None = None


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
        #: Exit code of the most recently finished launch, per game.
        #: Read synchronously by the session recorder while handling
        #: session_recorded, which is always emitted before game_finished.
        self._last_exit: dict[str, int] = {}
        #: How long the most recently finished launch ran, per game.
        self._last_seconds: dict[str, int] = {}

    @property
    def running_games(self) -> list[str]:
        return list(self._sessions)

    def is_running(self, game_name: str) -> bool:
        return game_name in self._sessions

    def last_exit_code(self, game_name: str) -> int | None:
        """Exit code of the latest finished launch, if any."""
        return self._last_exit.get(game_name)

    def last_session_seconds(self, game_name: str) -> int | None:
        """How long the latest finished launch ran, if known."""
        return self._last_seconds.get(game_name)

    def elapsed_seconds(self, game_name: str) -> int:
        """How long a running game has been playing, or 0."""
        session = self._sessions.get(game_name)
        if session is None:
            return 0
        return max(0, int(time.monotonic() - session.started_at))

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

        started_wall = datetime.now()
        self._last_exit.pop(game_name, None)
        self._last_seconds.pop(game_name, None)
        self._sessions[game_name] = _Session(process, time.monotonic(), started_wall)
        process.start(_SHELL, [str(script), game_name])
        if game_name not in self._sessions:
            # errorOccurred already fired synchronously; the entry was
            # cleaned up and no finished signal will follow.
            return False
        session = self._sessions[game_name]
        try:
            pid = int(process.processId())
        except (RuntimeError, TypeError, ValueError):
            pid = 0
        session.pid = pid or None
        self._persist_and_watch(game_name, session)
        self.game_started.emit(game_name)
        return True

    def _persist_and_watch(self, game_name: str, session: _Session) -> None:
        """Remember the launch on disk and cover it with a watcher."""
        try:
            from launcher.services import sessions as _sessions

            _sessions.add_active(
                self._paths, game_name, session.started_wall, session.pid
            )
            if session.pid:
                from launcher.services.session_watcher import spawn_watcher

                watcher = spawn_watcher(
                    self._paths,
                    game_name,
                    session.started_wall.isoformat(timespec="seconds"),
                    session.pid,
                )
                if watcher:
                    session.watcher_pid = watcher
                    _sessions.update_active(
                        self._paths, game_name, watcher_pid=watcher
                    )
        except (OSError, ValueError):
            pass

    def stop(self, game_name: str) -> bool:
        """Terminate a running game. Returns True if it was running."""
        session = self._sessions.get(game_name)
        if session is None:
            return False
        if session.process is None:
            self._on_finished(game_name, -1)
            return True
        session.process.terminate()
        return True

    def stop_all(self) -> None:
        for name in list(self._sessions):
            self.stop(name)

    def detach_all(self) -> None:
        """Leave running games alive for a real quit.

        Called from the app's shutdown path instead of stop_all(): the
        game processes keep running (they become orphans) and each one's
        watcher writes the full playtime when it exits.
        """
        try:
            from launcher.services import sessions as _sessions
            from launcher.services.session_watcher import spawn_watcher
        except ImportError:
            return
        for name, session in self._sessions.items():
            try:
                active = _sessions.load_active(self._paths).get(name)
                if active is None:
                    _sessions.add_active(
                        self._paths, name, session.started_wall, session.pid
                    )
                    active = _sessions.load_active(self._paths).get(name)
                watcher_pid = (active or {}).get("watcher_pid")
                if session.pid and not _sessions.pid_alive(watcher_pid):
                    watcher = spawn_watcher(
                        self._paths,
                        name,
                        session.started_wall.isoformat(timespec="seconds"),
                        session.pid,
                    )
                    if watcher:
                        session.watcher_pid = watcher
                        _sessions.update_active(
                            self._paths, name, watcher_pid=watcher
                        )
            except (OSError, ValueError):
                continue

    # -- process signals -----------------------------------------------

    def _on_output(self, game_name: str) -> None:
        session = self._sessions.get(game_name)
        if session is None or session.process is None:
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
            self._last_exit[game_name] = -1
            try:
                from launcher.services import sessions as _sessions

                _sessions.remove_active(self._paths, game_name)
            except (OSError, ValueError):
                pass
            if session.process is not None:
                self.game_error.emit(
                    game_name,
                    f"Failed to start milso-launcher.sh: {session.process.errorString()}",
                )
            self.game_finished.emit(game_name, -1)
        elif session.process is not None:
            self.game_error.emit(game_name, session.process.errorString())

    def _on_finished(self, game_name: str, exit_code: int) -> None:
        session = self._sessions.pop(game_name, None)
        self._last_exit[game_name] = exit_code
        elapsed = (
            int(time.monotonic() - session.started_at) if session is not None else 0
        )
        self._last_seconds[game_name] = elapsed
        if session is not None:
            if elapsed >= MIN_SESSION_SECONDS:
                self.session_recorded.emit(game_name, elapsed)
            try:
                from launcher.services import sessions as _sessions

                _sessions.remove_active(self._paths, game_name)
            except (OSError, ValueError):
                pass
        self.game_finished.emit(game_name, exit_code)
