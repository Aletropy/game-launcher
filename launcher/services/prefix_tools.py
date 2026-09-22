"""Acting on a game's Wine prefix: open it, or run a Wine tool against it.

The prefixes here are built by Proton, not by system Wine, and the two
are not interchangeable: pointing the distribution's `wine` at a Proton
prefix fails with "could not load kernel32.dll". So a Proton runtime is
preferred whenever one can be found on the host, and the system wine is
only a fallback.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices

from launcher.data.paths import Paths
from launcher.domain import prefixes

#: Where Proton builds are usually unpacked.
_PROTON_ROOTS = (
    Path.home() / ".local/share/Steam/compatibilitytools.d",
    Path.home() / ".steam/steam/compatibilitytools.d",
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d",
    Path.home() / ".local/share/Steam/steamapps/common",
    Path.home() / ".steam/steam/steamapps/common",
)

#: Relative locations of the wine binary inside a Proton build.
_PROTON_WINE = ("files/bin/wine", "dist/bin/wine")


@dataclass(frozen=True)
class PrefixTool:
    """Something the user can run against a prefix."""

    key: str
    label: str
    #: Wine's own name for the tool, run as `wine <verb>`. Empty for
    #: tools that are separate programs.
    verb: str = ""
    #: Where the tool lives inside the prefix, relative to drive_c.
    #: Running this through Proton is the only way to open a Proton
    #: prefix whose Proton is not installed on the host.
    windows_exe: tuple[str, ...] = ()


TOOLS: tuple[PrefixTool, ...] = (
    PrefixTool(
        "winecfg",
        "Wine configuration",
        verb="winecfg",
        windows_exe=("windows/system32/winecfg.exe", "windows/syswow64/winecfg.exe"),
    ),
    PrefixTool("winetricks", "Winetricks"),
    PrefixTool(
        "explorer",
        "Wine file browser",
        verb="explorer",
        windows_exe=("windows/explorer.exe", "windows/system32/explorer.exe"),
    ),
)

TOOLS_BY_KEY = {tool.key: tool for tool in TOOLS}


def find_proton_wine() -> Path | None:
    """The newest Proton wine binary on the host, if there is one."""
    candidates: list[tuple[float, Path]] = []
    for root in _PROTON_ROOTS:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            for relative in _PROTON_WINE:
                binary = entry / relative
                if binary.is_file():
                    with contextlib.suppress(OSError):
                        candidates.append((binary.stat().st_mtime, binary))
                    break
    if not candidates:
        return None
    return max(candidates)[1]


def is_proton_prefix(path: Path) -> bool:
    """Whether this prefix was built by Proton rather than plain Wine."""
    return (path / "pfx").is_dir() or (path / "version").is_file()


def wine_prefix_dir(path: Path) -> Path:
    """The directory to hand Wine as WINEPREFIX.

    Proton nests the real prefix one level down, in pfx/.
    """
    return path / "pfx" if (path / "pfx").is_dir() else path


def steam_flatpak_running() -> bool:
    """Whether the Steam Flatpak the launcher enters is running."""
    try:
        flatpak = shutil.which("flatpak")
        if flatpak is None:
            return False
        output = subprocess.run(  # noqa: S603 - resolved path, fixed argv
            [flatpak, "ps"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    return "steam" in output.lower()


class PrefixToolsService(QObject):
    """Opens prefixes and runs Wine tools against them."""

    #: tool label, message
    tool_failed = Signal(str, str)
    tool_started = Signal(str)

    def __init__(self, paths: Paths, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paths = paths

    def resolve(self, raw_prefix: str) -> Path:
        return prefixes.resolve(raw_prefix, self._paths)

    def open_folder(self, raw_prefix: str) -> bool:
        """Open the prefix in the desktop file manager."""
        path = self.resolve(raw_prefix)
        target = wine_prefix_dir(path) / "drive_c"
        if not target.is_dir():
            target = path
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

    def wine_for(self, path: Path) -> Path | None:
        """The wine binary to use for a prefix.

        A Proton prefix needs Proton's own wine; the distribution's build
        cannot open one. Plain prefixes are happy with either.
        """
        if is_proton_prefix(path):
            proton = find_proton_wine()
            if proton is not None:
                return proton
        system = shutil.which("wine")
        return Path(system) if system else None

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

        # A Proton prefix can only be opened by the Proton that built it,
        # and that Proton lives inside the Steam Flatpak. Route the tool
        # through the same script the games use, rather than pointing the
        # host's wine at a prefix it cannot load.
        via_proton = self._proton_command(tool, path)
        if via_proton is not None:
            command, args = via_proton
            wine = None
        else:
            wine = self.wine_for(path)
            resolved = self._command_for(tool, wine)
            if resolved is None:
                return False
            command, args = resolved

        process = QProcess()
        process.setProgram(command)
        process.setArguments(args)
        process.setWorkingDirectory(str(self._paths.base))
        process.setProcessEnvironment(self._environment(path, wine))

        # Detached on purpose. These are interactive tools the user drives
        # themselves: winetricks can run for minutes, and closing the
        # launcher must not kill it part way through changing a prefix.
        if not process.startDetached():
            self.tool_failed.emit(
                tool.label, f"Could not start {command}: {process.errorString()}"
            )
            return False

        self.tool_started.emit(tool.label)
        return True

    @staticmethod
    def _environment(path: Path, wine: Path | None) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        # milso-launcher.sh wants the directory that contains pfx/, and
        # derives STEAM_COMPAT_DATA_PATH from it; the host wine wants the
        # pfx directory itself.
        env.insert(
            "WINEPREFIX", str(path if wine is None else wine_prefix_dir(path))
        )
        if wine is not None:
            # winetricks picks its wine from $WINE.
            env.insert("WINE", str(wine))
            # Deliberately no LD_LIBRARY_PATH: a Proton wine finds its own
            # runtime relative to the binary, and forcing its lib/ onto
            # the path shadows the system loader and breaks startup with
            # "could not load kernel32.dll".
        return env

    def _proton_command(
        self, tool: PrefixTool, path: Path
    ) -> tuple[str, list[str]] | None:
        """Run the tool through Proton, or None if that is not possible."""
        if not tool.windows_exe or not is_proton_prefix(path):
            return None
        script = self._paths.launcher_script
        if not script.is_file():
            return None

        drive_c = wine_prefix_dir(path) / "drive_c"
        # is_file() is not enough: Proton links these to its own runtime
        # inside the Flatpak, so on the host they are dangling symlinks
        # that only resolve once the script has entered the container.
        executable = next(
            (
                drive_c / rel
                for rel in tool.windows_exe
                if (drive_c / rel).is_file() or (drive_c / rel).is_symlink()
            ),
            None,
        )
        if executable is None:
            return None

        if not steam_flatpak_running():
            self.tool_failed.emit(
                tool.label,
                "Steam is not running.\n\nThis prefix was built by Proton, "
                "which lives inside the Steam Flatpak, so Steam has to be "
                "running to open it.",
            )
            # Refusing here is deliberate: without Steam the script exits
            # immediately and the tool would simply never appear.
            return None

        return "bash", [str(script), "-exec", str(executable)]

    def _command_for(
        self, tool: PrefixTool, wine: Path | None
    ) -> tuple[str, list[str]] | None:
        """Work out what to execute, or report why it cannot be."""
        if tool.key == "winetricks":
            command = shutil.which("winetricks")
            if command:
                return command, []
            bundled = self.bundled_winetricks()
            if bundled is not None:
                return "bash", [str(bundled)]
            self.tool_failed.emit(
                tool.label,
                "winetricks was not found on PATH and none is bundled.",
            )
            return None

        if wine is None:
            self.tool_failed.emit(
                tool.label,
                "No Wine was found. Install wine, or a Proton build under "
                "Steam's compatibilitytools.d.",
            )
            return None
        # Proton builds ship `wine` but no separate winecfg binary, so
        # every tool runs as a verb: `wine winecfg`, `wine explorer`.
        return str(wine), [tool.verb]


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
