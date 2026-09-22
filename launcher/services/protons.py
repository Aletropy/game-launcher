"""Find the Proton builds installed on this machine.

The game editor used to take a free-text Proton path, so a typo or an
uninstalled build only surfaced as a failed launch. Discovery scans the
usual compatibility-tool folders for builds (a folder with a ``proton``
script in it) so the editor can offer them by name.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from launcher.services.prefix_tools import _PROTON_ROOTS


@dataclass(frozen=True)
class ProtonBuild:
    """One installed Proton build."""

    #: Folder name, e.g. "Proton-GE-Proton10-4".
    name: str
    #: The build directory; the game stores this path.
    path: Path
    #: One-line version, from the build's version file when present.
    version: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.version})" if self.version else self.name


def _version_of(build_dir: Path) -> str:
    for candidate in ("version", "VERSION"):
        try:
            text = (build_dir / candidate).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        line = text.strip().splitlines()
        if line and line[0].strip():
            return line[0].strip()[:60]
    return ""


def list_installed(roots: tuple[Path, ...] | list[Path] | None = None) -> list[ProtonBuild]:
    """Installed Proton builds, newest first. Never raises."""
    found: list[tuple[float, ProtonBuild]] = []
    for root in _PROTON_ROOTS if roots is None else roots:
        try:
            if not root.is_dir():
                continue
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if not entry.is_dir() or not (entry / "proton").is_file():
                    continue
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            found.append(
                (mtime, ProtonBuild(entry.name, entry, _version_of(entry)))
            )
    found.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    builds: list[ProtonBuild] = []
    for _, build in found:
        key = build.name
        with suppress(OSError):
            key = str(build.path.resolve())
        if key in seen:
            continue
        seen.add(key)
        builds.append(build)
    return builds


def describe(path_str: str) -> str:
    """One line about a configured custom path, for display."""
    if not (path_str or "").strip():
        return ""
    path = Path(path_str.strip())
    if (path / "proton").is_file():
        return f"Proton build ({path.name})"
    if path.is_dir():
        return "Folder, but no Proton build inside"
    return "Path does not exist"
