"""Domain models.

These are plain data. They know nothing about where they are stored, how
they are drawn, or how a game is launched — that belongs to the data and
service layers.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


@dataclass
class GameConfig:
    """Everything the launcher script needs to run one game.

    Mirrors the keys of a ``games/<name>.conf`` file.
    """

    name: str
    executable: str = ""
    game_id: str = "480"
    game_args: list[str] = field(default_factory=list)
    custom_proton_path: str = ""
    additional_dlls: list[str] = field(default_factory=list)
    use_gamescope: bool = False
    gamescope_w: str = "1280"
    gamescope_h: str = "720"
    gamescope_w_out: str = "1920"
    gamescope_h_out: str = "1080"
    gamescope_args: str = "-f -e"
    override_app_id: str = ""
    #: Per-game Wine prefix; empty means the shared prefix.
    prefix: str = ""
    extra_vars: list[str] = field(default_factory=list)
    proton_use_wine_sync: str = ""
    winedebug: str = ""
    radv_perftest: str = ""
    pulse_latency_msec: str = ""
    vkd3d_config: str = ""


@dataclass
class GameStats:
    """Per-game state the launcher records for itself."""

    favorite: bool = False
    playtime_seconds: int = 0
    last_played: datetime | None = None
    added: datetime | None = None
    launch_count: int = 0
    tags: tuple[str, ...] = ()
    notes: str = ""
    hidden: bool = False


def normalize_tags(raw: str | Collection[str]) -> tuple[str, ...]:
    """Split, lowercase and dedupe tags, preserving first-seen order."""
    parts = re.split(r"[,;]", raw) if isinstance(raw, str) else [str(p) for p in raw]
    seen: list[str] = []
    for part in parts:
        tag = part.strip().casefold()
        if tag and tag not in seen:
            seen.append(tag)
    return tuple(seen)


@dataclass
class Game:
    """A game as the UI sees it: its config, its stats and where it lives."""

    config: GameConfig
    conf_path: Path
    stats: GameStats = field(default_factory=GameStats)
    #: False when the executable is missing, e.g. an unmounted drive.
    executable_exists: bool = True

    # Convenience passthroughs; the UI reads these constantly.
    @property
    def name(self) -> str:
        return self.config.name

    @property
    def executable(self) -> str:
        return self.config.executable

    @property
    def prefix(self) -> str:
        return self.config.prefix

    @property
    def is_favorite(self) -> bool:
        return self.stats.favorite

    @property
    def tags(self) -> tuple[str, ...]:
        return self.stats.tags

    @property
    def notes(self) -> str:
        return self.stats.notes

    @property
    def hidden(self) -> bool:
        return self.stats.hidden

    @property
    def playtime_seconds(self) -> int:
        return self.stats.playtime_seconds

    @property
    def last_played(self) -> datetime | None:
        return self.stats.last_played


class SortOrder(Enum):
    """How the library is ordered."""

    NAME = "name"
    NAME_DESC = "name_desc"
    LAST_PLAYED = "last_played"
    PLAYTIME = "playtime"
    LEAST_PLAYED = "playtime_asc"
    RECENTLY_ADDED = "added"
    MOST_LAUNCHED = "launches"

    @property
    def label(self) -> str:
        return {
            SortOrder.NAME: "Name (A\u2013Z)",
            SortOrder.NAME_DESC: "Name (Z\u2013A)",
            SortOrder.LAST_PLAYED: "Last played",
            SortOrder.PLAYTIME: "Most played",
            SortOrder.LEAST_PLAYED: "Least played",
            SortOrder.RECENTLY_ADDED: "Recently added",
            SortOrder.MOST_LAUNCHED: "Most launched",
        }[self]


def sort_games(
    games: list[Game], order: SortOrder, *, favorites_first: bool = False
) -> list[Game]:
    """Return the games in the requested order.

    Names break ties, always A\u2013Z. Games with no value for a "most" or
    "last" key (never played, no recorded add date) sort after the rest
    rather than jumbling in with the zeros.
    """
    by_name = sorted(games, key=lambda g: g.name.casefold())
    epoch = datetime.min

    if order is SortOrder.NAME:
        ordered = by_name
    elif order is SortOrder.NAME_DESC:
        ordered = sorted(games, key=lambda g: g.name.casefold(), reverse=True)
    elif order is SortOrder.LAST_PLAYED:
        ordered = sorted(by_name, key=lambda g: g.stats.last_played or epoch, reverse=True)
    elif order is SortOrder.PLAYTIME:
        ordered = sorted(by_name, key=lambda g: g.stats.playtime_seconds, reverse=True)
    elif order is SortOrder.LEAST_PLAYED:
        ordered = sorted(by_name, key=lambda g: g.stats.playtime_seconds)
    elif order is SortOrder.MOST_LAUNCHED:
        ordered = sorted(by_name, key=lambda g: g.stats.launch_count, reverse=True)
    else:
        ordered = sorted(by_name, key=lambda g: g.stats.added or epoch, reverse=True)

    if favorites_first:
        # Stable, so each group keeps the chosen order.
        ordered = sorted(ordered, key=lambda g: not g.stats.favorite)
    return ordered


def format_playtime(seconds: int) -> str:
    """Human playtime, e.g. '12.4h' or '48m'. Empty when never played."""
    if seconds <= 0:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


#: (max days, singular, plural template) checked in order.
_AGO_STEPS = (
    (7, None, "{n} days ago"),
    (30, "last week", "{n} weeks ago"),
    (365, "last month", "{n} months ago"),
)


def format_last_played(when: datetime | None, *, now: datetime | None = None) -> str:
    """Human 'time ago', e.g. 'today' or '3 days ago'. Empty when never."""
    if when is None:
        return ""
    days = ((now or datetime.now()) - when).days
    if days < 0:
        return "just now"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"

    divisor = 1
    for limit, singular, plural in _AGO_STEPS:
        if days < limit:
            count = days // divisor
            return singular if count == 1 and singular else plural.format(n=count)
        divisor = limit if limit != 365 else divisor
    years = days // 365
    return "last year" if years == 1 else f"{years} years ago"
