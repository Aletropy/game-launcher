"""Wine prefix resolution.

A game either uses the shared prefix (the historical behaviour) or names
its own. The rules here mirror ``resolve_conf_overrides`` in
game-launcher.sh exactly; if one changes, the other must too.

Nothing here creates a directory. Creation stays in the shell script, so
there is one place that decides when a prefix comes into existence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from launcher.core.paths import BASE_DIR, PREFIX_NAME_FILE, PREFIXES_DIR

#: An empty prefix value means "use the shared prefix".
SHARED = ""

_DEFAULT_PREFIX_NAME = "Prefix"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class PrefixState(Enum):
    """What the configured prefix path currently is."""

    SHARED = auto()
    EXISTS = auto()
    WILL_CREATE = auto()
    NOT_A_DIRECTORY = auto()
    OUTSIDE_SANDBOX = auto()


@dataclass(frozen=True)
class PrefixInfo:
    """A resolved prefix and what the UI should say about it."""

    raw: str
    path: Path
    state: PrefixState
    message: str = ""

    @property
    def is_shared(self) -> bool:
        return self.state is PrefixState.SHARED

    @property
    def is_problem(self) -> bool:
        return self.state is PrefixState.NOT_A_DIRECTORY

    @property
    def initialized(self) -> bool:
        """True once Proton has actually built the prefix."""
        return (self.path / "pfx").is_dir()


def shared_prefix_name() -> str:
    """The shared prefix folder name, honouring the .prefix-name override."""
    if PREFIX_NAME_FILE.is_file():
        try:
            first = PREFIX_NAME_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            return _DEFAULT_PREFIX_NAME
        if first and first[0].strip():
            return first[0].strip()
    return _DEFAULT_PREFIX_NAME


def shared_prefix_path() -> Path:
    """The prefix used by every game that does not name its own."""
    return BASE_DIR / shared_prefix_name()


def resolve(raw: str) -> Path:
    """Resolve a configured prefix value to a path.

    Empty means the shared prefix; ``~`` expands; a relative path is taken
    against the launcher directory so a prefix stays portable.
    """
    value = raw.strip()
    if not value:
        return shared_prefix_path()
    if value.startswith("~"):
        return Path(value).expanduser()
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def suggest(game_name: str) -> str:
    """A sensible per-game prefix path, relative to the launcher directory."""
    safe = _UNSAFE.sub("-", game_name).strip("-") or "game"
    return f"{PREFIXES_DIR.name}/{safe}"


def _reachable_from_sandbox(path: Path) -> bool:
    """Whether the Steam Flatpak is likely to be able to see this path.

    The game runs through `flatpak enter` into the Steam container, so a
    prefix outside the launcher directory or the home directory usually
    is not visible there without an explicit flatpak override.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in (BASE_DIR.resolve(), Path.home().resolve()):
        if resolved == root or root in resolved.parents:
            return True
    return False


def inspect(raw: str) -> PrefixInfo:
    """Describe a configured prefix value for display."""
    path = resolve(raw)

    if not raw.strip():
        return PrefixInfo(
            raw=raw,
            path=path,
            state=PrefixState.SHARED,
            message=f"Shared prefix ({shared_prefix_name()})",
        )

    if path.exists() and not path.is_dir():
        return PrefixInfo(
            raw=raw,
            path=path,
            state=PrefixState.NOT_A_DIRECTORY,
            message="A file already exists at this path.",
        )

    if not _reachable_from_sandbox(path):
        return PrefixInfo(
            raw=raw,
            path=path,
            state=PrefixState.OUTSIDE_SANDBOX,
            message=(
                "Outside the launcher and home folders - the Steam Flatpak "
                "may not be able to see this path. Grant access with "
                "flatpak override if the game fails to start."
            ),
        )

    if path.is_dir():
        return PrefixInfo(raw=raw, path=path, state=PrefixState.EXISTS)

    return PrefixInfo(
        raw=raw,
        path=path,
        state=PrefixState.WILL_CREATE,
        message="Does not exist - will be created on first launch.",
    )


def describe(raw: str) -> str:
    """One line summarising a prefix, for the detail panel."""
    info = inspect(raw)
    if info.is_shared:
        return f"Shared ({shared_prefix_name()})"
    try:
        shown = info.path.relative_to(BASE_DIR)
    except ValueError:
        shown = info.path
    suffix = "" if info.path.is_dir() else "  (not created yet)"
    return f"{shown}{suffix}"
