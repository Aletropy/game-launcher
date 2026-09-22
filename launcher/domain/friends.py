"""Friends: what the friends server says about you and the people you added.

Pure data. The service fetches it and the Friends view draws it; parsing
lives here so both agree on one shape, whatever the server sends.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from launcher.domain.models import GameConfig

#: The placeholder app id the launcher fills in when none is given; every
#: game without its own id has it, so it says nothing about the game.
_PLACEHOLDER_APP_ID = "480"


class FriendsState(Enum):
    """Where the friends feature is, as the Friends tab shows it."""

    #: Offline Mode: nothing is sent or fetched.
    OFFLINE = "offline"
    #: Online, but no profile yet.
    UNREGISTERED = "unregistered"
    CONNECTING = "connecting"
    ONLINE = "online"
    #: Online, but the server did not answer; retrying.
    UNREACHABLE = "unreachable"


class BoardPeriod(Enum):
    """What the leaderboard adds up."""

    WEEK = "week"
    ALL_TIME = "all"

    @property
    def label(self) -> str:
        return "This week" if self is BoardPeriod.WEEK else "All time"


def game_key(config: GameConfig) -> str:
    """One key for the same game on everyone's machine.

    A Steam app id when the game has a real one, otherwise the name with
    case and punctuation dropped, so 'ELDEN RING' and 'Elden Ring' match.
    """
    app_id = config.override_app_id.strip() or config.game_id.strip()
    if app_id.isdigit() and app_id != _PLACEHOLDER_APP_ID:
        return f"steam:{app_id}"
    return name_key(config.name)


def name_key(name: str) -> str:
    return "name:" + re.sub(r"[^0-9a-z]+", "", name.lower())


def _int(raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _when(raw: Any) -> datetime | None:
    stamp = _int(raw)
    # Local wall-clock time, like every other date the launcher shows.
    return datetime.fromtimestamp(stamp) if stamp > 0 else None  # noqa: DTZ006


@dataclass(frozen=True)
class GameTotal:
    key: str
    name: str
    seconds: int

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> GameTotal:
        return cls(
            key=str(raw.get("game_key", "")),
            name=str(raw.get("game_name", "")),
            seconds=_int(raw.get("seconds")),
        )


@dataclass(frozen=True)
class Presence:
    """A game someone is playing right now."""

    key: str
    name: str
    since: datetime | None

    @classmethod
    def parse(cls, raw: Any) -> Presence | None:
        if not isinstance(raw, dict):
            return None
        return cls(
            key=str(raw.get("game_key", "")),
            name=str(raw.get("game_name", "")),
            since=_when(raw.get("since")),
        )


@dataclass(frozen=True)
class Friend:
    """A person as the Friends tab shows them; also used for yourself."""

    user_id: int
    name: str
    presence: Presence | None = None
    last_seen: datetime | None = None
    week_seconds: int = 0
    total_seconds: int = 0
    top_games: tuple[GameTotal, ...] = ()

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Friend:
        return cls(
            user_id=_int(raw.get("user_id")),
            name=str(raw.get("display_name", "")),
            presence=Presence.parse(raw.get("presence")),
            last_seen=_when(raw.get("last_seen")),
            week_seconds=_int(raw.get("week_seconds")),
            total_seconds=_int(raw.get("total_seconds")),
            top_games=tuple(
                GameTotal.parse(g) for g in raw.get("top_games") or [] if isinstance(g, dict)
            ),
        )


@dataclass(frozen=True)
class SharedGame:
    """A game someone in your circle has played, for the per-game ranking."""

    key: str
    name: str
    players: int


@dataclass(frozen=True)
class CommonGame:
    """A game you own that friends play too, with who and how much."""

    key: str
    name: str
    friend_names: tuple[str, ...] = ()
    friends_seconds: int = 0
    mine_seconds: int = 0


def common_games(
    friends: tuple[Friend, ...] | list[Friend],
    *,
    local_name: Callable[[str], str | None],
    local_seconds: Callable[[str], int] | None = None,
) -> list[CommonGame]:
    """Games the user owns that at least one friend has played.

    Matched by game key across friends' top games. Sorted by friends'
    total time, so the most-shared habit comes first. Pure.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for friend in friends:
        for total in friend.top_games:
            name = local_name(total.key)
            if name is None:
                continue
            entry = by_key.setdefault(
                total.key, {"name": name, "friends": [], "seconds": 0}
            )
            entry["name"] = name
            if friend.name not in entry["friends"]:
                entry["friends"].append(friend.name)
            entry["seconds"] += total.seconds
    found = [
        CommonGame(
            key=key,
            name=str(entry["name"]),
            friend_names=tuple(entry["friends"]),
            friends_seconds=int(entry["seconds"]),
            mine_seconds=local_seconds(key) if local_seconds else 0,
        )
        for key, entry in by_key.items()
    ]
    found.sort(key=lambda g: (g.friends_seconds, len(g.friend_names)), reverse=True)
    return found


@dataclass(frozen=True)
class FriendRequest:
    id: int
    name: str
    #: True for requests made to you, False for ones you sent.
    incoming: bool


@dataclass(frozen=True)
class LeaderboardRow:
    rank: int
    user_id: int
    name: str
    seconds: int
    is_me: bool

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> LeaderboardRow:
        return cls(
            rank=_int(raw.get("rank")),
            user_id=_int(raw.get("user_id")),
            name=str(raw.get("display_name", "")),
            seconds=_int(raw.get("seconds")),
            is_me=bool(raw.get("is_me")),
        )


@dataclass(frozen=True)
class FriendsSnapshot:
    """Everything the Friends tab draws, fetched together."""

    me: Friend
    friend_code: str
    friends: tuple[Friend, ...] = ()
    games: tuple[SharedGame, ...] = ()
    requests: tuple[FriendRequest, ...] = ()
    board: tuple[LeaderboardRow, ...] = ()
    #: What `board` ranks: a period, and a game key or "" for every game.
    board_period: BoardPeriod = field(default_factory=lambda: BoardPeriod.WEEK)
    board_game: str = ""
    fetched: datetime = field(default_factory=datetime.now)

    @property
    def playing_now(self) -> list[Friend]:
        return [f for f in self.friends if f.presence is not None]

    @property
    def incoming(self) -> list[FriendRequest]:
        return [r for r in self.requests if r.incoming]

    @property
    def outgoing(self) -> list[FriendRequest]:
        return [r for r in self.requests if not r.incoming]

    @classmethod
    def parse(
        cls,
        overview: dict[str, Any],
        requests: dict[str, Any],
        board: list[dict[str, Any]] | None = None,
        *,
        board_period: BoardPeriod | None = None,
        board_game: str = "",
    ) -> FriendsSnapshot:
        me = overview.get("me") or {}
        pending = [
            FriendRequest(_int(r.get("id")), str(r.get("display_name", "")), incoming)
            for incoming, bucket in ((True, "incoming"), (False, "outgoing"))
            for r in requests.get(bucket) or []
            if isinstance(r, dict)
        ]
        return cls(
            me=Friend.parse(me),
            friend_code=str(me.get("friend_code", "")),
            friends=tuple(
                Friend.parse(f) for f in overview.get("friends") or [] if isinstance(f, dict)
            ),
            games=tuple(
                SharedGame(
                    str(g.get("game_key", "")),
                    str(g.get("game_name", "")),
                    _int(g.get("players")),
                )
                for g in overview.get("games") or []
                if isinstance(g, dict)
            ),
            requests=tuple(pending),
            board=tuple(LeaderboardRow.parse(r) for r in board or [] if isinstance(r, dict)),
            board_period=board_period or BoardPeriod.WEEK,
            board_game=board_game,
        )


def format_code(raw: str) -> str:
    """Tidy a typed friend code: 'k7qx 29mb' -> 'K7QX-29MB'."""
    letters = "".join(ch for ch in raw.upper() if ch.isalnum())
    return f"{letters[:4]}-{letters[4:]}" if len(letters) == 8 else raw.strip().upper()


def is_valid_code(raw: str) -> bool:
    return len("".join(ch for ch in raw if ch.isalnum())) == 8


def format_since(when: datetime | None, now: datetime | None = None) -> str:
    """'for 12m', 'for 1h 05m': how long someone has been playing."""
    if when is None:
        return ""
    seconds = int(((now or datetime.now()) - when).total_seconds())
    minutes = max(0, seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f"for {hours}h {minutes:02d}m" if hours else f"for {minutes}m"


def format_seen(when: datetime | None, now: datetime | None = None) -> str:
    """'Online now', 'Seen 5m ago', 'Seen 3d ago'."""
    if when is None:
        return "Never seen"
    seconds = int(((now or datetime.now()) - when).total_seconds())
    if seconds < 180:
        return "Online now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"Seen {seconds // size}{unit} ago"
    return "Online now"
