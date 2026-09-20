"""Where save data lives, and how a prefix is wired to the shared store.

Pure: this module describes and inspects, it never writes. Everything
that changes the filesystem lives in services/save_store.py.

The shape is one Windows user profile stored once, with each prefix
holding symlinks into it, so a prefix can be rebuilt without losing
saves and a game finds its data whichever prefix it runs in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class LinkSpec:
    """One directory that is shared between prefixes."""

    #: Path inside drive_c, e.g. "users/steamuser/Documents".
    in_prefix: str
    #: Path inside the store, e.g. "Documents".
    in_store: str

    @property
    def label(self) -> str:
        """Short name for the UI."""
        return self.in_store


#: The six directories that hold save data. AppData's children are linked
#: individually rather than AppData itself, so AppData stays a real
#: directory: Wine keeps its own aliases there ("Application Data" ->
#: AppData/Roaming) and a broken link can be repaired one folder at a time.
LINKS: tuple[LinkSpec, ...] = (
    LinkSpec("users/steamuser/AppData/Local", "AppData/Local"),
    LinkSpec("users/steamuser/AppData/LocalLow", "AppData/LocalLow"),
    LinkSpec("users/steamuser/AppData/Roaming", "AppData/Roaming"),
    LinkSpec("users/steamuser/Documents", "Documents"),
    LinkSpec("users/steamuser/Saved Games", "Saved Games"),
    LinkSpec("ProgramData", "ProgramData"),
)

#: Merge losers are quarantined here rather than deleted.
CONFLICTS_DIR = ".conflicts"
#: Records which prefixes are linked.
MANIFEST_FILE = ".manifest.json"


class LinkState(Enum):
    """What one shared path currently looks like inside a prefix."""

    #: A symlink pointing at the right place in the store.
    LINKED = "linked"
    #: A symlink pointing somewhere else.
    FOREIGN_LINK = "foreign_link"
    #: A real directory holding data that has not been adopted yet.
    REAL_DIR = "real_dir"
    #: Nothing there; the link can simply be created.
    MISSING = "missing"
    #: A file sits where a directory belongs.
    NOT_A_DIR = "not_a_dir"

    @property
    def needs_work(self) -> bool:
        return self is not LinkState.LINKED

    @property
    def is_blocked(self) -> bool:
        """States a plain adopt cannot resolve on its own."""
        return self in (LinkState.FOREIGN_LINK, LinkState.NOT_A_DIR)


@dataclass
class PathStatus:
    """The state of one shared path inside one prefix."""

    spec: LinkSpec
    #: Where it lives in the prefix.
    path: Path
    #: Where it should point.
    target: Path
    state: LinkState
    #: Where a FOREIGN_LINK actually points.
    actual_target: Path | None = None

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def describe(self) -> str:
        return {
            LinkState.LINKED: "shared",
            LinkState.FOREIGN_LINK: f"links elsewhere: {self.actual_target}",
            LinkState.REAL_DIR: "holds its own copy",
            LinkState.MISSING: "not created yet",
            LinkState.NOT_A_DIR: "a file is in the way",
        }[self.state]


@dataclass
class PrefixStatus:
    """How one prefix relates to the shared store."""

    prefix: Path
    drive_c: Path | None
    paths: list[PathStatus] = field(default_factory=list)

    @property
    def exists(self) -> bool:
        return self.drive_c is not None

    @property
    def linked_count(self) -> int:
        return sum(1 for p in self.paths if p.state is LinkState.LINKED)

    @property
    def fully_linked(self) -> bool:
        return bool(self.paths) and all(
            p.state is LinkState.LINKED for p in self.paths
        )

    @property
    def unlinked(self) -> bool:
        return not any(p.state is LinkState.LINKED for p in self.paths)

    @property
    def needs_adoption(self) -> list[PathStatus]:
        return [p for p in self.paths if p.state.needs_work]

    @property
    def blocked(self) -> list[PathStatus]:
        return [p for p in self.paths if p.state.is_blocked]

    @property
    def summary(self) -> str:
        if not self.exists:
            return "prefix not created yet"
        if self.fully_linked:
            return f"shared ({self.linked_count} links)"
        if self.unlinked:
            return "not shared"
        broken = len(self.needs_adoption)
        return f"partly shared ({self.linked_count}/{len(self.paths)}, {broken} to fix)"


def drive_c_of(prefix: Path) -> Path | None:
    """Locate drive_c inside a prefix. Proton nests it under pfx/."""
    for candidate in (prefix / "pfx" / "drive_c", prefix / "drive_c"):
        if candidate.is_dir():
            return candidate
    return None


def store_path(store: Path, spec: LinkSpec) -> Path:
    return store / spec.in_store


def link_target(link: Path, target: Path, base: Path) -> str:
    """The string to store in the symlink.

    Relative when both sides live under the launcher directory, so the
    whole folder can be moved; absolute otherwise.
    """
    try:
        link.relative_to(base)
        target.relative_to(base)
    except ValueError:
        return str(target)
    return os.path.relpath(target, link.parent)


def inspect_path(
    drive_c: Path, store: Path, spec: LinkSpec, base: Path
) -> PathStatus:
    """Classify one shared path inside a prefix."""
    path = drive_c / spec.in_prefix
    target = store_path(store, spec)

    if path.is_symlink():
        try:
            actual = Path(os.path.realpath(path))
        except OSError:
            actual = None
        wanted = Path(os.path.realpath(target)) if target.exists() else target
        if actual is not None and actual == wanted:
            state = LinkState.LINKED
        else:
            return PathStatus(
                spec, path, target, LinkState.FOREIGN_LINK, actual_target=actual
            )
    elif not path.exists():
        state = LinkState.MISSING
    elif path.is_dir():
        state = LinkState.REAL_DIR
    else:
        state = LinkState.NOT_A_DIR

    return PathStatus(spec, path, target, state)


def inspect_prefix(prefix: Path, store: Path, base: Path) -> PrefixStatus:
    """Report how a prefix relates to the store. Reads only."""
    drive_c = drive_c_of(prefix)
    if drive_c is None:
        return PrefixStatus(prefix=prefix, drive_c=None)
    return PrefixStatus(
        prefix=prefix,
        drive_c=drive_c,
        paths=[inspect_path(drive_c, store, spec, base) for spec in LINKS],
    )


def store_is_reachable(store: Path, base: Path) -> bool:
    """Whether games will be able to follow links into the store.

    Games run inside the Steam Flatpak container, and a symlink is
    resolved there, not here. Prefixes under the launcher directory are
    already visible inside that container, so a store alongside them is
    too. A store anywhere else would silently appear empty in-game.
    """
    try:
        store.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return False
    return True
