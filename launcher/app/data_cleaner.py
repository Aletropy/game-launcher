"""Clearing what the launcher has recorded about games.

Every clear takes a copy of the database first, so nothing here is
beyond recovery: the copy can be put back by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from launcher.app.context import AppContext


class DataKind(Enum):
    """Something that can be cleared."""

    HISTORY = "history"
    PLAYTIME = "playtime"
    LAUNCHES = "launches"
    FAVORITES = "favorites"
    COLLECTIONS = "collections"
    ARTWORK = "artwork"
    LOGS = "logs"

    @property
    def label(self) -> str:
        return {
            DataKind.HISTORY: "Play history",
            DataKind.PLAYTIME: "Total playtime",
            DataKind.LAUNCHES: "Last played and launch count",
            DataKind.FAVORITES: "Favourites",
            DataKind.COLLECTIONS: "Tags, notes and hidden",
            DataKind.ARTWORK: "Artwork",
            DataKind.LOGS: "Logs",
        }[self]

    @property
    def description(self) -> str:
        return {
            DataKind.HISTORY: "Every session: the Journal's heatmap, streaks and records",
            DataKind.PLAYTIME: "The hours shown in the library",
            DataKind.LAUNCHES: "Recently played order and Most launched",
            DataKind.FAVORITES: "Stars",
            DataKind.COLLECTIONS: "Tags, personal notes and hidden games",
            DataKind.ARTWORK: "Covers, banners, logos and icons on disk",
            DataKind.LOGS: "Output kept since the launcher started",
        }[self]


#: What "Clear everything" ticks.
ALL_KINDS = frozenset(DataKind)
#: Kept in the database; a copy is taken before these are cleared.
_RECORDED = {
    DataKind.HISTORY,
    DataKind.PLAYTIME,
    DataKind.LAUNCHES,
    DataKind.FAVORITES,
    DataKind.COLLECTIONS,
}


@dataclass
class ClearReport:
    sessions: int = 0
    artwork_files: int = 0
    forgotten: int = 0
    #: The copy of the database taken first, if one was needed.
    snapshot: Path | None = None


def orphaned_names(context: AppContext) -> list[str]:
    """Games with recorded state that are no longer in the library."""
    known = {game.name for game in context.games.list_games()}
    return sorted(context.state.known_names() - known)


def clear(
    context: AppContext, names: list[str], kinds: set[DataKind]
) -> ClearReport:
    """Clear some kinds of data for some games.

    Logs live in the window, so the caller clears those; they are listed
    as a kind only so one dialog can offer everything.
    """
    report = ClearReport()
    state = context.state
    if kinds & _RECORDED and names:
        report.snapshot = state.snapshot(context.paths.state_backups_dir)
    if DataKind.HISTORY in kinds:
        report.sessions = state.clear_sessions(names)
        # Friends see totals built from history; clear it there too.
        context.friends.forget_games(names)
    if DataKind.PLAYTIME in kinds:
        state.reset_playtime(names)
    if DataKind.LAUNCHES in kinds:
        state.reset_launches(names)
    if DataKind.FAVORITES in kinds:
        state.clear_favorites(names)
    if DataKind.COLLECTIONS in kinds:
        state.clear_collections(names)
    if DataKind.ARTWORK in kinds:
        for name in names:
            report.artwork_files += context.artwork.remove(name)
    if DataKind.LOGS in kinds:
        for name in names or sorted(context.state.known_names()):
            context.logs.clear(name)
    return report


def forget_orphans(context: AppContext) -> ClearReport:
    """Drop every record of games that have been removed."""
    names = orphaned_names(context)
    report = ClearReport(forgotten=len(names))
    if names:
        report.snapshot = context.state.snapshot(context.paths.state_backups_dir)
        report.sessions = context.state.session_count(names)
        context.state.forget(names)
        context.friends.forget_games(names)
    return report
