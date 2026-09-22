"""Play history: sessions, and what they add up to.

Pure: the Journal view draws what these functions compute.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Session:
    """One stretch of play."""

    name: str
    started: datetime
    seconds: int
    #: Reconstructed from totals recorded before sessions existed; the
    #: date is the day the game was last played, not when it was played.
    imported: bool = False
    #: Process exit code; 0 means the game exited cleanly.
    exit_code: int = 0
    #: The exit looks like a crash rather than a quit.
    crashed: bool = False

    @property
    def day(self) -> date:
        return self.started.date()


@dataclass
class Day:
    """Everything played on one calendar day."""

    day: date
    seconds: int = 0
    games: dict[str, int] = field(default_factory=dict)
    approximate: bool = False

    @property
    def top_game(self) -> str | None:
        if not self.games:
            return None
        return max(self.games.items(), key=lambda item: item[1])[0]


def days(sessions: list[Session]) -> dict[date, Day]:
    """Group sessions by the calendar day they started on."""
    grouped: dict[date, Day] = {}
    for session in sessions:
        entry = grouped.setdefault(session.day, Day(session.day))
        entry.seconds += session.seconds
        entry.games[session.name] = entry.games.get(session.name, 0) + session.seconds
        entry.approximate = entry.approximate or session.imported
    return grouped


def heatmap(
    sessions: list[Session], *, weeks: int = 26, today: date | None = None
) -> list[list[Day | None]]:
    """A calendar grid: one column per week, Monday first, oldest left.

    Days after today are None, so the last column is only as tall as the
    current week.
    """
    today = today or date.today()
    by_day = days(sessions)
    # Start on the Monday `weeks - 1` weeks before this week's Monday.
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(weeks=weeks - 1)

    grid: list[list[Day | None]] = []
    for week in range(weeks):
        column: list[Day | None] = []
        for weekday in range(7):
            current = start + timedelta(weeks=week, days=weekday)
            if current > today:
                column.append(None)
            else:
                column.append(by_day.get(current, Day(current)))
        grid.append(column)
    return grid


def intensity(seconds: int, peak: int) -> int:
    """Bucket a day into 0-4 for colouring, relative to the busiest day.

    Relative buckets keep the map readable whether someone plays ten
    minutes a day or six hours.
    """
    if seconds <= 0 or peak <= 0:
        return 0
    ratio = seconds / peak
    if ratio > 0.75:
        return 4
    if ratio > 0.5:
        return 3
    if ratio > 0.25:
        return 2
    return 1


def streak(sessions: list[Session], today: date | None = None) -> int:
    """Consecutive days played, ending today or yesterday.

    Yesterday counts so the streak does not read zero all morning before
    the first game of the day.
    """
    today = today or date.today()
    played = {d for d, day in days(sessions).items() if day.seconds > 0}
    cursor = today if today in played else today - timedelta(days=1)
    count = 0
    while cursor in played:
        count += 1
        cursor -= timedelta(days=1)
    return count


def total_since(sessions: list[Session], since: datetime) -> int:
    return sum(s.seconds for s in sessions if s.started >= since)


def longest(sessions: list[Session]) -> Session | None:
    """The longest real session. Reconstructed ones are totals, not sessions."""
    real = [s for s in sessions if not s.imported]
    return max(real, key=lambda s: s.seconds) if real else None


def week_start(today: date | None = None) -> datetime:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday, datetime.min.time())


def per_game(sessions: list[Session]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for session in sessions:
        totals[session.name] += session.seconds
    return dict(totals)


def format_duration(seconds: int) -> str:
    """'3h 12m', '45m', or '0m'."""
    minutes = max(0, seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"
    return f"{minutes}m"
