"""Acting on a game's Wine prefix: open it, or run a Wine tool against it."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from launcher.data.paths import Paths
from launcher.domain import prefixes


@dataclass(frozen=True)
class PrefixTool:
    """A program that can be run against a prefix."""

    key: str
    label: str
    command: str
    #: Arguments after the command name.
    args: tuple[str, ...] = ()

    def is_available(self) -> bool:
        return shutil.which(self.command) is not None


TOOLS: tuple[PrefixTool, ...] = (
    PrefixTool("winecfg", "Wine configuration", "winecfg"),
    PrefixTool("winetricks", "Winetricks", "winetricks"),
    PrefixTool("explorer", "Wine file browser", "wine", ("explorer",)),
)

TOOLS_BY_KEY = {tool.key: tool for tool in TOOLS}


class PrefixToolsService(QObject):
    """Opens prefixes and runs Wine tools against them."""

    #: tool label, message
    tool_failed = Signal(str, str)
    tool_started = Signal(str)

    def __init__(self, paths: Paths, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paths = paths
        self._running: list[QProcess] = []

    def resolve(self, raw_prefix: str) -> Path:
        return prefixes.resolve(raw_prefix, self._paths)

    def open_folder(self, raw_prefix: str) -> bool:
        """Open the prefix in the desktop file manager."""
        path = self.resolve(raw_prefix)
        target = path / "pfx" / "drive_c" if (path / "pfx").is_dir() else path
        if not target.is_dir():
            self.tool_failed.emit(
                "Open folder", f"The prefix does not exist yet:\n{path}"
            )
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def bundled_winetricks(self) -> Path | None:
        """The winetricks shipped alongside the launcher, if present."""
        bundled = self._paths.base / "winetricks"
        return bundled if bundled.is_file() else None

    def run(self, tool_key: str, raw_prefix: str) -> bool:
        """Run a Wine tool against a prefix, without blocking the UI."""
        tool = TOOLS_BY_KEY.get(tool_key)
        if tool is None:
            return False

        path = self.resolve(raw_prefix)
        if not path.is_dir():
            self.tool_failed.emit(
                tool.label, f"The prefix does not exist yet:\n{path}"
            )
            return False

        command = tool.command
        args = list(tool.args)
        if tool.key == "winetricks" and not tool.is_available():
            bundled = self.bundled_winetricks()
            if bundled is None:
                self.tool_failed.emit(
                    tool.label,
                    "winetricks was not found on PATH and none is bundled.",
                )
                return False
            command = "bash"
            args = [str(bundled)]
        elif not tool.is_available():
            self.tool_failed.emit(
                tool.label, f"{tool.command} was not found on PATH."
            )
            return False

        process = QProcess(self)
        env = process.processEnvironment()
        # Proton keeps the real Wine prefix in a pfx/ subdirectory.
        wineprefix = path / "pfx" if (path / "pfx").is_dir() else path
        env.insert("WINEPREFIX", str(wineprefix))
        process.setProcessEnvironment(env)
        process.finished.connect(lambda *_: self._forget(process))
        process.errorOccurred.connect(
            lambda *_: self.tool_failed.emit(tool.label, process.errorString())
        )

        self._running.append(process)
        process.start(command, args)
        self.tool_started.emit(tool.label)
        return True

    def _forget(self, process: QProcess) -> None:
        if process in self._running:
            self._running.remove(process)

    def kill_all(self) -> None:
        for process in list(self._running):
            process.terminate()


def open_path(path: Path) -> bool:
    """Open any directory in the file manager."""
    if not path.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def disk_usage(path: Path) -> int:
    """Total size of a directory in bytes, or 0 if it does not exist."""
    if not path.is_dir():
        return 0
    try:
        output = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["/usr/bin/du", "-sb", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        return int(output.split("\t", 1)[0])
    except (subprocess.SubprocessError, ValueError, OSError):
        return 0
