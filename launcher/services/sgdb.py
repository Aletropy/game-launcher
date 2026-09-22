"""SteamGridDB API client for fetching game artwork."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.data.settings_store import SettingsStore

import json
import urllib.parse
import urllib.request

_BASE_URL = "https://www.steamgriddb.com/api/v2"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class SGDBError(Exception):
    """Error from the SteamGridDB API."""


#: Art type -> SteamGridDB endpoint. The art type names match the
#: artwork service's specs, so a download lands in the right folder.
ENDPOINTS: dict[str, str] = {
    "grid": "grids",
    "hero": "heroes",
    "icon": "icons",
    "logo": "logos",
}


#: Styles SteamGridDB accepts, per art type.
STYLES: dict[str, tuple[str, ...]] = {
    "grid": ("alternate", "blurred", "white_logo", "material", "no_logo"),
    "hero": ("alternate", "blurred", "material"),
    "logo": ("official", "white", "black", "custom"),
    "icon": ("official", "custom"),
}
#: Portrait capsule sizes: what the library calls a cover.
PORTRAIT_DIMENSIONS = ("600x900", "342x482", "660x930")


@dataclass(frozen=True)
class ArtQuery:
    """Filters for one artwork search."""

    art: str
    style: str = ""
    #: Only portrait covers; SteamGridDB also serves wide grid capsules.
    portrait_only: bool = True
    nsfw: bool = False
    humor: bool = False
    page: int = 0

    def params(self) -> dict[str, str]:
        # Static only: the library draws still images, and an animated
        # upload would be stored as its first frame anyway.
        params = {
            "types": "static",
            "nsfw": "any" if self.nsfw else "false",
            "humor": "any" if self.humor else "false",
            "page": str(self.page),
        }
        if self.style and self.style in STYLES.get(self.art, ()):
            params["styles"] = self.style
        if self.art == "grid" and self.portrait_only:
            params["dimensions"] = ",".join(PORTRAIT_DIMENSIONS)
        return params


@dataclass(frozen=True)
class ArtResult:
    """One image SteamGridDB offers."""

    id: int
    url: str
    thumb: str
    width: int
    height: int
    style: str = ""
    author: str = ""
    score: int = 0

    @classmethod
    def from_api(cls, raw: dict) -> ArtResult:
        author = raw.get("author") or {}
        return cls(
            id=int(raw.get("id", 0)),
            url=str(raw.get("url", "")),
            thumb=str(raw.get("thumb") or raw.get("url", "")),
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            style=str(raw.get("style", "")),
            author=str(author.get("name", "")) if isinstance(author, dict) else "",
            score=int(raw.get("score") or 0),
        )

    @property
    def size_label(self) -> str:
        return f"{self.width}\u00d7{self.height}" if self.width and self.height else ""


@dataclass(frozen=True)
class GameMatch:
    """A game SteamGridDB knows."""

    id: int
    name: str
    year: int | None = None
    verified: bool = False

    @classmethod
    def from_api(cls, raw: dict) -> GameMatch:
        year = None
        stamp = raw.get("release_date")
        if isinstance(stamp, int | float) and stamp > 0:
            year = datetime.fromtimestamp(stamp, tz=UTC).year
        return cls(
            id=int(raw.get("id", 0)),
            name=str(raw.get("name", "")),
            year=year,
            verified=bool(raw.get("verified", False)),
        )

    @property
    def label(self) -> str:
        year = f" ({self.year})" if self.year else ""
        return f"{self.name}{year}"


def _api_get(endpoint: str, api_key: str, params: dict | None = None) -> dict:
    """Make an authenticated GET request to the SGDB API."""
    url = f"{_BASE_URL}{endpoint}"
    if params:
        qs = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{qs}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    for k, v in _HEADERS.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
            raise SGDBError(data.get("message", f"HTTP {e.code}")) from e
        except (json.JSONDecodeError, KeyError):
            raise SGDBError(f"HTTP {e.code}: {body[:200]}") from e
    except urllib.error.URLError as e:
        raise SGDBError(f"Network error: {e.reason}") from e


class SgdbClient:
    """SteamGridDB, with the API key taken from settings."""

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings

    @property
    def api_key(self) -> str:
        return self._settings.get_str("sgdb_api_key")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def set_api_key(self, key: str) -> None:
        self._settings.set("sgdb_api_key", key.strip())

    def search(self, query: str) -> list[dict]:
        return search_games(query, self.api_key)

    def verify_key(self, key: str) -> str:
        """Check a key works. Returns a message describing the result."""
        try:
            search_games("portal", key)
        except SGDBError as e:
            return f"Key rejected: {e}"
        return "Key works."

    def download(self, url: str) -> bytes:
        return download_bytes(url)

    # -- typed API, used by the artwork wizard -------------------------

    def find_games(self, query: str) -> list[GameMatch]:
        return [GameMatch.from_api(raw) for raw in self.search(query)]

    def find_art(self, game_id: int, query: ArtQuery) -> list[ArtResult]:
        endpoint = ENDPOINTS.get(query.art)
        if endpoint is None:
            raise SGDBError(f"Unknown artwork type: {query.art}")
        result = _api_get(f"/{endpoint}/game/{game_id}", self.api_key, query.params())
        return [ArtResult.from_api(raw) for raw in result.get("data", []) if raw.get("url")]


def search_games(query: str, api_key: str) -> list[dict]:
    """Search for games by name. Returns list of {id, name, types, verified}."""
    result = _api_get(f"/search/autocomplete/{urllib.parse.quote(query)}", api_key)
    return result.get("data", [])


def download_bytes(url: str) -> bytes:
    """Download an image and return its bytes.

    The caller decides where it lands; the artwork service re-encodes it
    rather than storing whatever the API happened to serve.
    """
    req = urllib.request.Request(url)
    for k, v in _HEADERS.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return bytes(resp.read())
    except (urllib.error.URLError, OSError) as e:
        raise SGDBError(f"Failed to download image: {e}") from e
