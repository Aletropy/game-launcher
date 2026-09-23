"""Finding games to add by scanning a folder for executables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Executables that ship alongside games but are never the game itself.
_NOISE_PATTERNS = (
    r"unins",
    r"setup",
    r"install",
    r"redist",
    r"vcredist",
    r"directx",
    r"dxsetup",
    r"dotnet",
    r"crashh?andler",
    r"crashreport",
    r"errorreport",
    r"launcher_?helper",
    r"ue4prereq",
    r"ue prereq",
    r"oalinst",
    r"quicksfv",
    r"notification_helper",
    r"nvngx",
    r"zsync",
)
_NOISE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)

#: Directories that only ever hold support binaries.
_SKIP_DIRS = {
    "_commonredist",
    "redist",
    "redistributables",
    "directx",
    "dotnet",
    "vcredist",
    "engine",
    "binaries",
    "__installer",
    "support",
}

#: Windows system directories inside a Wine prefix.
_PREFIX_MARKERS = {"drive_c", "windows", "system32", "syswow64", "pfx"}


@dataclass
class Candidate:
    """A possible game found while scanning."""

    name: str
    executable: Path
    size: int
    #: False for things that look like installers or helpers.
    likely_game: bool = True
    reason: str = ""

    @property
    def folder(self) -> str:
        return self.executable.parent.name


def _looks_like_noise(exe: Path) -> tuple[bool, str]:
    if _NOISE.search(exe.stem):
        return True, "looks like an installer or helper"
    parts = {p.casefold() for p in exe.parts}
    from launcher import platform as _platform

    if not _platform.is_windows() and parts & _PREFIX_MARKERS:
        return True, "inside a Wine prefix"
    if {p.casefold() for p in exe.parent.parts} & _SKIP_DIRS:
        return True, "in a redistributables folder"
    if exe.stat().st_size < 100_000:
        return True, "very small"
    return False, ""


def _clean_name(exe: Path, root: Path) -> str:
    """Guess a display name: the game's folder, or the executable."""
    relative = exe.parent
    base = relative.name if relative != root and relative.name else exe.stem
    # "Game.Name-REPACK" and "Game_Name" both read better spaced out.
    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"\s*[-(\[](repack|gog|proper|v?\d[\d.]*)\b.*$", "", base, flags=re.I)
    return " ".join(base.split()).strip() or exe.stem


def scan_folder(
    root: Path, *, max_depth: int = 4, limit: int = 500
) -> list[Candidate]:
    """Find Windows executables under a folder.

    Returns candidates sorted with the most likely games first. Nothing is
    written; the caller decides what to add.
    """
    if not root.is_dir():
        return []

    candidates: list[Candidate] = []
    root_depth = len(root.parts)

    for exe in root.rglob("*.exe"):
        if len(candidates) >= limit:
            break
        if not exe.is_file():
            continue
        if len(exe.parts) - root_depth > max_depth:
            continue
        try:
            noise, reason = _looks_like_noise(exe)
            size = exe.stat().st_size
        except OSError:
            continue
        candidates.append(
            Candidate(
                name=_clean_name(exe, root),
                executable=exe,
                size=size,
                likely_game=not noise,
                reason=reason,
            )
        )

    return _prefer_one_per_folder(candidates)


def _prefer_one_per_folder(candidates: list[Candidate]) -> list[Candidate]:
    """Keep the largest executable per folder; demote the rest.

    A game folder usually holds one real executable plus helpers, and the
    real one is almost always the biggest.
    """
    best: dict[Path, Candidate] = {}
    extras: list[Candidate] = []
    for candidate in candidates:
        if not candidate.likely_game:
            extras.append(candidate)
            continue
        folder = candidate.executable.parent
        current = best.get(folder)
        if current is None or candidate.size > current.size:
            if current is not None:
                extras.append(current)
            best[folder] = candidate
        else:
            extras.append(candidate)

    for extra in extras:
        if extra.likely_game and not extra.reason:
            extra.reason = "another executable in the same folder is larger"
            extra.likely_game = False

    ordered = sorted(best.values(), key=lambda c: c.name.casefold())
    ordered.extend(sorted(extras, key=lambda c: c.name.casefold()))
    return ordered
