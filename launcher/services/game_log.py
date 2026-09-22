"""Game output, kept on disk.

Logs used to live only in memory: quitting the launcher (or clearing the
buffer) destroyed the one thing that explains a crash. Every game's
output is now appended to ``data/logs/<game>.log`` with rotation, so the
failure card and bug reports can show what actually happened.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from PySide6.QtCore import QObject

from launcher.data.paths import Paths
from launcher.services.process import ProcessService

#: Rotate when a log passes this size; keep one older generation.
MAX_BYTES = 512 * 1024
#: The failure card and dialogs never read more than this from the tail.
TAIL_CHARS = 20_000


def slug(name: str) -> str:
    """A filename-safe stem for a game name."""
    keep = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
    return keep.strip("_")[:80] or "game"


class GameLogStore(QObject):
    """Appends process output to per-game log files."""

    def __init__(
        self, paths: Paths, processes: ProcessService, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        processes.game_started.connect(self._on_started)
        processes.game_output.connect(self._on_output)
        processes.game_error.connect(self._on_output)
        processes.game_finished.connect(self._on_finished)

    @property
    def directory(self) -> Path:
        return self._paths.data / "logs"

    def path_for(self, name: str) -> Path:
        return self.directory / f"{slug(name)}.log"

    # -- writes ----------------------------------------------------------

    def _on_started(self, name: str) -> None:
        self._rotate(name)
        self._append_line(name, "── session started ──")

    def _on_output(self, name: str, text: str) -> None:
        self._append(name, text)

    def _on_finished(self, name: str, exit_code: int) -> None:
        self._append_line(name, f"── session ended (exit {exit_code}) ──")

    def _append(self, name: str, text: str) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(name)
            with path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(text)
                if not text.endswith("\n"):
                    handle.write("\n")
            if path.stat().st_size > MAX_BYTES * 2:
                self._rotate(name)
        except OSError:
            pass

    def _append_line(self, name: str, line: str) -> None:
        self._append(name, line + "\n")

    def _rotate(self, name: str) -> None:
        path = self.path_for(name)
        try:
            if not path.is_file() or path.stat().st_size <= MAX_BYTES:
                return
        except OSError:
            return
        with contextlib.suppress(OSError):
            backup = path.with_suffix(".log.1")
            backup.unlink(missing_ok=True)
            os.replace(path, backup)

    # -- reads -----------------------------------------------------------

    def recent(self, name: str, max_chars: int = TAIL_CHARS) -> str:
        """The tail of a game's log, for dialogs and the failure card."""
        try:
            data = self.path_for(name).read_bytes()
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        return text[-max_chars:] if len(text) > max_chars else text

    def size(self, name: str) -> int:
        try:
            return self.path_for(name).stat().st_size
        except OSError:
            return 0

    def clear(self, name: str) -> None:
        """Delete one game's logs, including the rotated generation."""
        for suffix in (".log", ".log.1"):
            with contextlib.suppress(OSError):
                (self.directory / f"{slug(name)}{suffix}").unlink(missing_ok=True)

    def clear_all(self) -> int:
        """Delete every game log. Returns files removed."""
        removed = 0
        try:
            for path in self.directory.glob("*.log*"):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        except OSError:
            pass
        return removed
