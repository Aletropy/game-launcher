"""Process manager for launching games via QProcess."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

_BASE_DIR = Path(__file__).resolve().parent.parent
_LAUNCHER_SCRIPT = _BASE_DIR / "game-launcher.sh"
_SHELL = "bash"


class ProcessManager(QObject):
    """Manages game process lifecycle via QProcess."""

    game_started = Signal(str)
    game_finished = Signal(str, int)
    game_output = Signal(str, str)
    game_error = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._processes: dict[str, QProcess] = {}

    @property
    def running_games(self) -> list[str]:
        return list(self._processes.keys())

    def is_running(self, game_name: str) -> bool:
        return game_name in self._processes

    def launch(self, game_name: str) -> bool:
        """Launch a game by name using game-launcher.sh. Returns True on success."""
        if self.is_running(game_name):
            return False

        if not _LAUNCHER_SCRIPT.is_file():
            self.game_error.emit(game_name, f"Launcher script not found: {_LAUNCHER_SCRIPT}")
            return False

        process = QProcess(self)
        process.setWorkingDirectory(str(_BASE_DIR))
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

        self._processes[game_name] = process
        process.start(_SHELL, [str(_LAUNCHER_SCRIPT), game_name])
        if game_name not in self._processes:
            # errorOccurred already fired synchronously; the entry was cleaned
            # up by _on_process_error and no finished signal will follow.
            return False
        self.game_started.emit(game_name)
        return True

    def stop(self, game_name: str) -> bool:
        """Terminate a running game. Returns True if process was found."""
        proc = self._processes.get(game_name)
        if proc is None:
            return False
        proc.terminate()
        return True

    def _on_output(self, game_name: str) -> None:
        proc = self._processes.get(game_name)
        if proc is None:
            return
        raw = bytes(proc.readAllStandardOutput().data())
        text = raw.decode("utf-8", errors="replace")
        if text:
            self.game_output.emit(game_name, text)

    def _on_process_error(self, game_name: str, error: QProcess.ProcessError) -> None:
        proc = self._processes.get(game_name)
        if proc is None:
            return
        if error == QProcess.ProcessError.FailedToStart:
            # No finished signal follows a failed start, so release the slot
            # here or the game stays "running" for the rest of the session.
            self._processes.pop(game_name, None)
            self.game_error.emit(
                game_name, f"Failed to start game-launcher.sh: {proc.errorString()}"
            )
            self.game_finished.emit(game_name, -1)
        else:
            self.game_error.emit(game_name, proc.errorString())

    def _on_finished(self, game_name: str, exit_code: int) -> None:
        self._processes.pop(game_name, None)
        self.game_finished.emit(game_name, exit_code)
