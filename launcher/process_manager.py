"""Process manager for launching games via QProcess."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

_BASE_DIR = Path(__file__).resolve().parent.parent
_LAUNCHER_SCRIPT = _BASE_DIR / "game-launcher.sh"


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
        process.readyReadStandardError.connect(
            lambda gn=game_name: self._on_error(gn)
        )
        process.finished.connect(
            lambda code, status, gn=game_name: self._on_finished(gn, code)
        )

        self._processes[game_name] = process
        process.start("bash", [str(_LAUNCHER_SCRIPT), game_name])
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

    def _on_error(self, game_name: str) -> None:
        proc = self._processes.get(game_name)
        if proc is None:
            return
        raw = bytes(proc.readAllStandardError().data())
        text = raw.decode("utf-8", errors="replace")
        if text:
            self.game_error.emit(game_name, text)

    def _on_finished(self, game_name: str, exit_code: int) -> None:
        self._processes.pop(game_name, None)
        self.game_finished.emit(game_name, exit_code)
