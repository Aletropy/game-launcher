"""What save backups leave out, and which ones they keep.

Pure: the backup service applies these rules to real files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from fnmatch import translate

#: Paths never worth backing up, relative to the save store. Matched
#: case-insensitively against the whole relative path; a directory that
#: matches takes everything under it along. `*` crosses folders.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    # Rebuilt by the system or the game, and often the bulk of the size.
    "appdata/local/temp",
    "appdata/local/dxvk",
    "appdata/local/d3dscache",
    "appdata/local/nvidia",
    "appdata/local/nvidia corporation",
    "appdata/local/microsoft/windows/inetcache",
    "appdata/local/crashdumps",
    "programdata/package cache",
    "*/cache",
    "*/caches",
    "*/shadercache",
    "*/shader_cache",
    "*/gpucache",
    "*/code cache",
    "*/webcache",
    "*.tmp",
)


def parse_patterns(text: str) -> tuple[str, ...]:
    """User exclusions: one pattern per line, # starts a comment."""
    patterns = []
    for raw in text.splitlines():
        pattern = raw.split("#", 1)[0].strip().strip("/")
        if pattern:
            patterns.append(pattern.casefold())
    return tuple(patterns)


@dataclass(frozen=True)
class Exclusions:
    """Decides which paths a backup skips."""

    patterns: tuple[str, ...] = DEFAULT_EXCLUDES
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        joined = "|".join(f"(?:{translate(p.casefold())})" for p in self.patterns)
        # An empty alternation would match everything.
        object.__setattr__(self, "_regex", re.compile(joined or r"(?!)"))

    @classmethod
    def with_extra(cls, extra: str) -> Exclusions:
        return cls(DEFAULT_EXCLUDES + parse_patterns(extra))

    def excludes(self, relative: str) -> bool:
        """Whether a path (posix, relative to the store) is left out.

        A path inside an excluded folder is excluded too.
        """
        parts = relative.casefold().strip("/").split("/")
        return any(
            self._regex.match("/".join(parts[: i + 1])) for i in range(len(parts))
        )


# --------------------------------------------------------------------------
# retention
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Retention:
    """How many snapshots to keep, by age.

    The newest `recent` are always kept, then the newest of each of the
    last `daily` days and of each of the last `weekly` weeks. Pinned
    snapshots are never pruned.
    """

    recent: int = 5
    daily: int = 7
    weekly: int = 4


@dataclass(frozen=True)
class SnapshotAge:
    """What retention needs to know about a snapshot."""

    name: str
    created: datetime
    pinned: bool = False


def to_prune(
    snapshots: list[SnapshotAge], policy: Retention, today: date | None = None
) -> list[str]:
    """Names of the snapshots the policy no longer wants."""
    today = today or date.today()
    newest_first = sorted(snapshots, key=lambda s: s.created, reverse=True)
    keep: set[str] = {s.name for s in newest_first if s.pinned}
    keep.update(s.name for s in newest_first[: max(1, policy.recent)])

    first_day = today - timedelta(days=policy.daily - 1)
    this_monday = today - timedelta(days=today.weekday())
    first_week = this_monday - timedelta(weeks=policy.weekly - 1)
    seen_days: set[date] = set()
    seen_weeks: set[date] = set()
    for snap in newest_first:
        day = snap.created.date()
        if policy.daily > 0 and day >= first_day and day not in seen_days:
            seen_days.add(day)
            keep.add(snap.name)
        monday = day - timedelta(days=day.weekday())
        if policy.weekly > 0 and monday >= first_week and monday not in seen_weeks:
            seen_weeks.add(monday)
            keep.add(snap.name)

    return [s.name for s in newest_first if s.name not in keep]
