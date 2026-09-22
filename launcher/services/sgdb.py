"""SteamGridDB API client for fetching game artwork."""

from __future__ import annotations

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

    def heroes(self, game_id: int) -> list[dict]:
        return get_heroes(game_id, self.api_key)

    def grids(self, game_id: int) -> list[dict]:
        return get_grids(game_id, self.api_key)

    def artwork_for(self, query: str, art_type: str) -> list[dict]:
        """Look a game up by name and return its artwork of one type."""
        matches = self.search(query)
        if not matches:
            raise SGDBError("No games found.")
        return get_artwork(matches[0]["id"], art_type, self.api_key)

    def verify_key(self, key: str) -> str:
        """Check a key works. Returns a message describing the result."""
        try:
            search_games("portal", key)
        except SGDBError as e:
            return f"Key rejected: {e}"
        return "Key works."

    def download(self, url: str) -> bytes:
        return download_bytes(url)


def search_games(query: str, api_key: str) -> list[dict]:
    """Search for games by name. Returns list of {id, name, types, verified}."""
    result = _api_get(f"/search/autocomplete/{urllib.parse.quote(query)}", api_key)
    return result.get("data", [])


def get_artwork(game_id: int, art_type: str, api_key: str) -> list[dict]:
    """Fetch artwork of one type ("grid", "hero", "icon", "logo")."""
    endpoint = ENDPOINTS.get(art_type)
    if endpoint is None:
        raise SGDBError(f"Unknown artwork type: {art_type}")
    result = _api_get(f"/{endpoint}/game/{game_id}", api_key)
    return result.get("data", [])


def get_heroes(game_id: int, api_key: str) -> list[dict]:
    """Fetch hero images for a SGDB game ID."""
    result = _api_get(f"/heroes/game/{game_id}", api_key)
    return result.get("data", [])


def get_grids(game_id: int, api_key: str) -> list[dict]:
    """Fetch grid images for a SGDB game ID."""
    result = _api_get(f"/grids/game/{game_id}", api_key)
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
