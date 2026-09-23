"""Per-game desktop entries.

``milso-launcher --play "Name"`` already starts a game (forwarded to the
running instance when there is one), so a ``.desktop`` file pointing at
it gives every game its own menu icon, taskbar pin and file-manager
launch. Entries are named ``milso-<slug>.desktop`` and removed with the
game's own Remove action or from the same menu that made them.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from launcher.services.artwork import ICON


def _applications_dir() -> Path:
    from launcher import platform as _platform

    if _platform.is_windows():
        appdata = os.environ.get("APPDATA") or str(
            Path.home() / "AppData" / "Roaming"
        )
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Milso Launcher"
        )
    override = os.environ.get("XDG_DATA_HOME")
    base = Path(override) if override else Path.home() / ".local" / "share"
    return base / "applications"


def slug(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in name.casefold())
    return "-".join(p for p in keep.split("-") if p)[:60] or "game"


def shortcut_path(name: str, directory: Path | None = None) -> Path:
    from launcher import platform as _platform

    if _platform.is_windows():
        return (directory or _applications_dir()) / f"milso-{slug(name)}.url"
    return (directory or _applications_dir()) / f"milso-{slug(name)}.desktop"


def launcher_command() -> str:
    """How a shortcut starts the launcher: the installed command, if any."""
    from launcher import platform as _platform

    command = shutil.which("milso-launcher")
    if command:
        return command
    if _platform.is_windows():
        return str(Path(__file__).resolve().parents[2] / "run-win.bat")
    return str(Path(__file__).resolve().parents[2] / "run.sh")


def icon_for(artwork: Any, name: str) -> str:
    """Best icon path for a shortcut: its icon art, else the app icon."""
    path: object = None
    if artwork is not None:
        try:
            path = artwork.path_for(name, ICON.name)
        except (AttributeError, TypeError, OSError):
            path = None
    if path is not None:
        return str(path)
    fallback = Path(__file__).resolve().parents[2] / "icon.png"
    return str(fallback) if fallback.is_file() else ""


def _safe_name(name: str) -> str:
    """Single-line game name for shortcut files (blocks ini injection)."""
    return " ".join(str(name).split())[:120] or "game"


def create(
    name: str,
    *,
    artwork: Any | None = None,
    directory: Path | None = None,
) -> Path:
    """Write (or refresh) a game's shortcut. Returns its path."""
    import shlex

    from launcher import platform as _platform

    target = shortcut_path(name, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(name)
    icon = icon_for(artwork, name) if artwork is not None else icon_for(None, name)
    if _platform.is_windows():
        # .url shortcuts need no COM dependency and pin from Explorer.
        lines = [
            "[InternetShortcut]",
            f"URL=file:///{launcher_command()}",
            f"IconFile={icon}" if icon else "IconFile=shell32.dll",
            "IconIndex=0",
            "[Milso Launcher]",
            f"Game={safe}",
            f"Command={launcher_command()} --play {shlex.quote(safe)}",
        ]
        tmp = target.with_suffix(".url.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(target)
        return target
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={safe}",
        f"Comment=Play {safe} with Milso Launcher",
        f"Exec={launcher_command()} --play {shlex.quote(safe)}",
        f"Icon={icon}" if icon else "Icon=applications-games",
        "Categories=Game;",
        "Terminal=false",
        "StartupWMClass=milso-launcher",
    ]
    tmp = target.with_suffix(".desktop.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def remove(name: str, directory: Path | None = None) -> bool:
    """Delete a game's shortcut. True when one existed."""
    target = shortcut_path(name, directory)
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def exists(name: str, directory: Path | None = None) -> bool:
    return shortcut_path(name, directory).is_file()
