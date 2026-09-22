"""Which games the library shows.

Pure: facts that are not on the Game itself (what is running, which
games have artwork) are passed in, so this stays free of I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from launcher.domain.models import Game


class Availability(Enum):
    ANY = "any"
    INSTALLED = "installed"
    MISSING = "missing"

    @property
    def label(self) -> str:
        return {
            Availability.ANY: "All games",
            Availability.INSTALLED: "Installed",
            Availability.MISSING: "Executable missing",
        }[self]


class PlayState(Enum):
    ANY = "any"
    PLAYED = "played"
    UNPLAYED = "unplayed"

    @property
    def label(self) -> str:
        return {
            PlayState.ANY: "Played or not",
            PlayState.PLAYED: "Played",
            PlayState.UNPLAYED: "Never played",
        }[self]


class PrefixKind(Enum):
    ANY = "any"
    SHARED = "shared"
    OWN = "own"

    @property
    def label(self) -> str:
        return {
            PrefixKind.ANY: "Any prefix",
            PrefixKind.SHARED: "Shared prefix",
            PrefixKind.OWN: "Own prefix",
        }[self]


@dataclass(frozen=True)
class LibraryFilter:
    """Everything that narrows the list. The default shows every game."""

    text: str = ""
    favorites: bool = False
    availability: Availability = Availability.ANY
    played: PlayState = PlayState.ANY
    prefix: PrefixKind = PrefixKind.ANY
    running: bool = False
    missing_art: bool = False
    #: Only games carrying at least one of these tags (empty means any).
    tags: tuple[str, ...] = ()
    #: Hidden games are excluded unless this is on.
    show_hidden: bool = False

    @property
    def active_count(self) -> int:
        """Filters in effect, not counting the search text."""
        return sum(
            (
                self.favorites,
                self.availability is not Availability.ANY,
                self.played is not PlayState.ANY,
                self.prefix is not PrefixKind.ANY,
                self.running,
                self.missing_art,
                bool(self.tags),
                self.show_hidden,
            )
        )

    @property
    def is_default(self) -> bool:
        return self.active_count == 0 and not self.text

    def cleared(self) -> LibraryFilter:
        """No filters, keeping the search text."""
        return LibraryFilter(text=self.text)

    def with_(self, **changes: Any) -> LibraryFilter:
        return replace(self, **changes)

    def matches(
        self,
        game: Game,
        *,
        running: Collection[str] = (),
        has_art: Callable[[str], bool] | None = None,
    ) -> bool:
        played = game.playtime_seconds > 0 or game.last_played is not None
        installed = game.executable_exists
        folded = self.text.casefold()
        game_tags = set(game.tags)
        checks = (
            not self.text
            or folded in game.name.casefold()
            or any(folded in tag for tag in game_tags),
            not self.favorites or game.is_favorite,
            self.availability is not Availability.INSTALLED or installed,
            self.availability is not Availability.MISSING or not installed,
            self.played is not PlayState.PLAYED or played,
            self.played is not PlayState.UNPLAYED or not played,
            self.prefix is not PrefixKind.SHARED or not game.prefix,
            self.prefix is not PrefixKind.OWN or bool(game.prefix),
            not self.running or game.name in running,
            not self.missing_art or has_art is None or not has_art(game.name),
            not game.hidden or self.show_hidden,
            not self.tags or bool(game_tags & set(self.tags)),
        )
        return all(checks)

    # -- persistence ---------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Stored without the search text, which is per session."""
        return {
            "favorites": self.favorites,
            "availability": self.availability.value,
            "played": self.played.value,
            "prefix": self.prefix.value,
            "running": self.running,
            "missing_art": self.missing_art,
            "tags": sorted(self.tags),
            "show_hidden": self.show_hidden,
        }

    @classmethod
    def from_json(cls, raw: object) -> LibraryFilter:
        if not isinstance(raw, dict):
            return cls()

        def pick(enum: type[Enum], key: str, default: Enum) -> Any:
            try:
                return enum(raw.get(key, default.value))
            except ValueError:
                return default

        stored_tags = raw.get("tags", [])
        tags: tuple[str, ...] = ()
        if isinstance(stored_tags, list):
            tags = tuple(t for t in (str(t) for t in stored_tags) if t)
        return cls(
            favorites=bool(raw.get("favorites", False)),
            availability=pick(Availability, "availability", Availability.ANY),
            played=pick(PlayState, "played", PlayState.ANY),
            prefix=pick(PrefixKind, "prefix", PrefixKind.ANY),
            running=bool(raw.get("running", False)),
            missing_art=bool(raw.get("missing_art", False)),
            tags=tags,
            show_hidden=bool(raw.get("show_hidden", False)),
        )
