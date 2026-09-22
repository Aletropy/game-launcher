"""The friends server's HTTP API, as blocking calls.

Run these off the GUI thread; FriendsService does. Every failure comes
back as a FriendsError subclass, so a caller never has to know urllib.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TIMEOUT = 5.0
_HEADERS = {"User-Agent": "GameLauncher-Friends/1", "Accept": "application/json"}


class FriendsError(Exception):
    """Anything that went wrong talking to the friends server."""


class ServerUnreachableError(FriendsError):
    """No answer: the server is down, or the address is wrong."""


class AuthError(FriendsError):
    """The server does not know this token, e.g. the account was deleted."""


class ServerError(FriendsError):
    """The server answered with an error."""

    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(detail or code or f"HTTP {status}")
        self.status = status
        self.code = code


def check_url(url: str) -> str:
    """The base URL without a trailing slash, or ValueError if unusable."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"Not an http(s) address: {url!r}")
    return url.strip().rstrip("/")


class FriendsClient:
    """One method per endpoint. Holds the address and the token, nothing else."""

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = check_url(base_url)
        self.token = token

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        url = self.base_url + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        data = None if body is None else json.dumps(body).encode("utf-8")
        # The scheme was checked in check_url; only http(s) gets here.
        request = urllib.request.Request(  # noqa: S310
            url, data=data, method=method, headers=_HEADERS
        )
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
                raw = response.read()
        except urllib.error.HTTPError as e:
            raise self._error(e) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise ServerUnreachableError(f"Can't reach {self.base_url}: {reason}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ServerError(200, "bad_response", "The server sent something unreadable") from None

    @staticmethod
    def _error(e: urllib.error.HTTPError) -> FriendsError:
        try:
            payload = json.loads(e.read() or b"{}")
        except (json.JSONDecodeError, OSError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if e.code == 401:
            return AuthError("The friends server no longer recognises this profile")
        return ServerError(e.code, str(payload.get("error", "")), str(payload.get("detail", "")))

    # -- account ---------------------------------------------------------

    def register(self, display_name: str) -> dict[str, Any]:
        return self._call("POST", "/v1/register", {"display_name": display_name})

    def me(self) -> dict[str, Any]:
        return self._call("GET", "/v1/me")

    def rename(self, display_name: str) -> None:
        self._call("PATCH", "/v1/me", {"display_name": display_name})

    def delete_account(self) -> None:
        self._call("DELETE", "/v1/me")

    def ping(self) -> str:
        """A readable result for the Settings 'Test' button."""
        try:
            self._call("GET", "/v1/me")
        except AuthError:
            return "Server found."
        return "Server found; signed in."

    # -- friends ---------------------------------------------------------

    def send_request(self, code: str) -> None:
        self._call("POST", "/v1/requests", {"code": code})

    def requests(self) -> dict[str, Any]:
        return self._call("GET", "/v1/requests")

    def answer(self, request_id: int, accept: bool) -> None:
        verb = "accept" if accept else "decline"
        self._call("POST", f"/v1/requests/{int(request_id)}/{verb}")

    def cancel_request(self, request_id: int) -> None:
        self._call("DELETE", f"/v1/requests/{int(request_id)}")

    def unfriend(self, user_id: int) -> None:
        self._call("DELETE", f"/v1/friends/{int(user_id)}")

    def overview(self, since: int | None) -> dict[str, Any]:
        return self._call("GET", "/v1/friends", query={"since": since})

    def leaderboard(self, since: int | None, game_key: str | None) -> list[dict[str, Any]]:
        result = self._call("GET", "/v1/leaderboard", query={"since": since, "game": game_key})
        return list((result or {}).get("rows") or [])

    # -- what you share --------------------------------------------------

    def set_presence(self, game_key: str, game_name: str) -> None:
        self._call("PUT", "/v1/presence", {"game_key": game_key, "game_name": game_name})

    def clear_presence(self) -> None:
        self._call("DELETE", "/v1/presence")

    def upload_sessions(self, sessions: list[dict[str, Any]]) -> int:
        result = self._call("POST", "/v1/sessions", {"sessions": sessions})
        return int((result or {}).get("stored", 0))

    def delete_sessions(self, game_keys: list[str] | None) -> None:
        self._call("POST", "/v1/sessions/delete", {"game_keys": game_keys})
