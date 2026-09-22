"""Find Steam-installed games worth adding.

Steam keeps its libraries in ``libraryfolders.vdf`` with an
``appmanifest_<id>.acf`` per installed game. This parses both (no Steam
API, no network), locates each game's folder, and guesses its .exe with
the same folder scanner the manual import uses, so the import dialog can
offer Steam games pre-scored with their origin.
"""

from __future__ import annotations

import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from launcher.services.importer import Candidate, scan_folder

#: Where Steam keeps its data, in the order worth checking.
_LIBRARY_ROOTS = (
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",
)


@dataclass
class SteamGame:
    """An installed Steam game and its best .exe guess."""

    app_id: str
    name: str
    install_dir: Path
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def best(self) -> Candidate | None:
        likely = [c for c in self.candidates if c.likely_game]
        return likely[0] if likely else (self.candidates[0] if self.candidates else None)


def _library_folders(steam_root: Path) -> list[Path]:
    """Parse libraryfolders.vdf into steamapps folders. Never raises."""
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    folders = [steam_root / "steamapps"]
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        path = Path(match.group(1))
        if path.is_dir():
            folders.append(path / "steamapps")
        else:
            # Windows-style paths in the vdf can never be ours.
            with suppress(OSError):
                expanded = Path(os.path.expandvars(match.group(1)))
                if expanded.is_dir():
                    folders.append(expanded / "steamapps")
    seen: list[Path] = []
    for folder in folders:
        if folder.is_dir() and folder not in seen:
            seen.append(folder)
    return seen


def _manifests(steamapps: Path) -> list[tuple[str, str, str]]:
    """(app_id, name, installdir) from each appmanifest. Never raises."""
    found: list[tuple[str, str, str]] = []
    try:
        files = sorted(steamapps.glob("appmanifest_*.acf"))
    except OSError:
        return found
    for manifest in files:
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        app_id = _field(text, "appid")
        name = _field(text, "name")
        installdir = _field(text, "installdir")
        if app_id and name and installdir:
            found.append((app_id, name, installdir))
    return found


def _field(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
    return match.group(1) if match else ""


def scan_steam_libraries(
    roots: tuple[Path, ...] | list[Path] | None = None,
) -> list[SteamGame]:
    """Installed Steam games with .exe guesses. Empty when Steam is absent."""
    games: list[SteamGame] = []
    for root in _LIBRARY_ROOTS if roots is None else roots:
        for steamapps in _library_folders(root):
            for app_id, name, installdir in _manifests(steamapps):
                folder = steamapps / "common" / installdir
                if not folder.is_dir():
                    continue
                try:
                    candidates = scan_folder(folder)
                except OSError:
                    candidates = []
                games.append(
                    SteamGame(
                        app_id=app_id,
                        name=name,
                        install_dir=folder,
                        candidates=candidates,
                    )
                )
    games.sort(key=lambda g: g.name.casefold())
    return games


def already_known(
    game: SteamGame, known_names: set[str], known_executables: set[str]
) -> bool:
    """Whether the library already holds this game, by name or .exe."""
    names = {n.casefold() for n in known_names}
    if game.name.casefold() in names:
        return True
    return game.best is not None and str(game.best.executable) in known_executables
