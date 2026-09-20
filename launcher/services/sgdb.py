"""SteamGridDB API client for fetching game artwork."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

_BASE_URL = "https://www.steamgriddb.com/api/v2"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class SGDBError(Exception):
    """Error from the SteamGridDB API."""


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


def search_games(query: str, api_key: str) -> list[dict]:
    """Search for games by name. Returns list of {id, name, types, verified}."""
    result = _api_get(f"/search/autocomplete/{urllib.parse.quote(query)}", api_key)
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
