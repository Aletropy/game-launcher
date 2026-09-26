"""The HTTP API: JSON in, JSON out, a bearer token for everything but sign-up."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from server.db import NotFoundError, SessionIn, Store, User

MAX_BODY = 256 * 1024
MAX_NAME = 32
MAX_KEY = 128
#: Sessions accepted in one upload; clients send history in batches.
MAX_BATCH = 1000
#: Longer than any real session; guards the totals against garbage.
MAX_SESSION_SECONDS = 7 * 24 * 3600


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail


def _bad(detail: str) -> ApiError:
    return ApiError(HTTPStatus.BAD_REQUEST, "bad_request", detail)


@dataclass
class Request:
    user: User | None
    body: dict[str, Any]
    query: dict[str, str]
    params: tuple[str, ...]

    @property
    def me(self) -> User:
        assert self.user is not None
        return self.user


# -- validation ------------------------------------------------------------


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _bad(f"{field} is required")
    text = " ".join(value.split())
    if len(text) > limit:
        raise _bad(f"{field} is longer than {limit} characters")
    return text


def _int(value: object, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _bad(f"{field} must be a whole number from {low} to {high}")
    return value


def _since(query: dict[str, str]) -> int | None:
    raw = query.get("since")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise _bad("since must be a Unix timestamp") from None


def _platform(raw: object) -> str:
    from server.db import normalise_platform

    return normalise_platform(raw)


def _session(raw: object) -> SessionIn:
    if not isinstance(raw, dict):
        raise _bad("each session must be an object")
    return SessionIn(
        client_session_id=_text(raw.get("id"), "id", MAX_KEY),
        game_key=_text(raw.get("game_key"), "game_key", MAX_KEY),
        game_name=_text(raw.get("game_name"), "game_name", MAX_KEY),
        started=_int(raw.get("started"), "started", 0, 2**40),
        seconds=_int(raw.get("seconds"), "seconds", 1, MAX_SESSION_SECONDS),
        platform=_platform(raw.get("platform")),
    )


# -- handlers ----------------------------------------------------------------


def _register(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    device_name = str(req.body.get("device_name") or "this PC")[:64]
    user, token, recovery_key = store.register(
        _text(req.body.get("display_name"), "display_name", MAX_NAME),
        _platform(req.body.get("platform")),
        device_name,
    )
    return HTTPStatus.CREATED, {
        "user_id": user.id,
        "display_name": user.display_name,
        "friend_code": user.friend_code,
        "token": token,
        "recovery_key": recovery_key,
    }


def _me(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    user = req.me
    return HTTPStatus.OK, {
        "user_id": user.id,
        "display_name": user.display_name,
        "friend_code": user.friend_code,
    }


def _rename(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.rename(req.me.id, _text(req.body.get("display_name"), "display_name", MAX_NAME))
    return HTTPStatus.NO_CONTENT, None


def _delete_me(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.delete_user(req.me.id)
    return HTTPStatus.NO_CONTENT, None


def _send_request(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.send_request(req.me.id, _text(req.body.get("code"), "code", 16))
    # The same answer whether or not the code exists, so codes can't be probed.
    return HTTPStatus.ACCEPTED, {"ok": True}


def _requests(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, store.requests(req.me.id)


def _answer(accept: bool) -> Callable[[Store, Request], tuple[HTTPStatus, Any]]:
    def handler(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
        store.answer_request(req.me.id, int(req.params[0]), accept=accept)
        return HTTPStatus.NO_CONTENT, None

    return handler


def _cancel_request(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.cancel_request(req.me.id, int(req.params[0]))
    return HTTPStatus.NO_CONTENT, None


def _unfriend(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.unfriend(req.me.id, int(req.params[0]))
    return HTTPStatus.NO_CONTENT, None


def _set_presence(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.set_presence(
        req.me.id,
        _text(req.body.get("game_key"), "game_key", MAX_KEY),
        _text(req.body.get("game_name"), "game_name", MAX_KEY),
        _platform(req.body.get("platform")),
    )
    return HTTPStatus.NO_CONTENT, None


def _clear_presence(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    store.clear_presence(req.me.id)
    return HTTPStatus.NO_CONTENT, None


def _upload_sessions(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    raw = req.body.get("sessions")
    if not isinstance(raw, list):
        raise _bad("sessions must be a list")
    if len(raw) > MAX_BATCH:
        raise _bad(f"at most {MAX_BATCH} sessions per upload")
    stored = store.upsert_sessions(req.me.id, [_session(item) for item in raw])
    return HTTPStatus.OK, {"stored": stored}


def _delete_sessions(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    keys = req.body.get("game_keys")
    if keys is not None and (
        not isinstance(keys, list) or not all(isinstance(k, str) for k in keys)
    ):
        raise _bad("game_keys must be a list of strings, or null for everything")
    return HTTPStatus.OK, {"deleted": store.delete_sessions(req.me.id, keys)}


def _friends(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, store.overview(req.me, _since(req.query))


def _leaderboard(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    game = req.query.get("game") or None
    return HTTPStatus.OK, {"rows": store.leaderboard(req.me, _since(req.query), game)}


def _devices(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, {"devices": store.list_devices(req.me.id)}


def _revoke_device(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    try:
        device_id = int(req.params[0])
    except (IndexError, ValueError):
        raise _bad("device id must be a whole number") from None
    if not store.revoke_device(req.me.id, device_id):
        raise NotFoundError
    return HTTPStatus.NO_CONTENT, None


def _rotate_recovery(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, {"recovery_key": store.issue_recovery(req.me.id)}


def _reclaim(store: Store, req: Request) -> tuple[HTTPStatus, Any]:
    # Unauthenticated but gated: wrong code/key looks the same as unknown
    # code, and callers should rate-limit (see _RECLAIM_ATTEMPTS below).
    code = _text(req.body.get("friend_code") or req.body.get("code"), "friend_code", 16)
    key = req.body.get("recovery_key")
    if not isinstance(key, str) or not key.strip():
        raise _bad("recovery_key is required")
    device_name = str(req.body.get("device_name") or "new device")[:64]
    if not _reclaim_allowed():
        raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "too_many_requests", "try again later")
    result = store.reclaim(code, key.strip(), device_name)
    if result is None:
        _reclaim_note_failure()
        # Same answer whether the code or the key was wrong.
        raise ApiError(HTTPStatus.UNAUTHORIZED, "unauthorized")
    user, token = result
    return HTTPStatus.OK, {
        "user_id": user.id,
        "display_name": user.display_name,
        "friend_code": user.friend_code,
        "token": token,
    }


#: Naive in-process brake for the unauthenticated reclaim endpoint.
_RECLAIM_WINDOW = 300.0
_RECLAIM_MAX = 20
_RECLAIM_ATTEMPTS: list[float] = []


def _reclaim_allowed() -> bool:
    import time as _time

    now = _time.time()
    while _RECLAIM_ATTEMPTS and _RECLAIM_ATTEMPTS[0] < now - _RECLAIM_WINDOW:
        _RECLAIM_ATTEMPTS.pop(0)
    return len(_RECLAIM_ATTEMPTS) < _RECLAIM_MAX


def _reclaim_note_failure() -> None:
    import time as _time

    _RECLAIM_ATTEMPTS.append(_time.time())


Handler = Callable[[Store, Request], tuple[HTTPStatus, Any]]

#: (method, path pattern, needs a token, handler)
ROUTES: list[tuple[str, re.Pattern[str], bool, Handler]] = [
    (method, re.compile(f"^{pattern}$"), auth, handler)
    for method, pattern, auth, handler in (
        ("POST", "/v1/register", False, _register),
        ("POST", "/v1/devices/reclaim", False, _reclaim),
        ("GET", "/v1/me", True, _me),
        ("PATCH", "/v1/me", True, _rename),
        ("DELETE", "/v1/me", True, _delete_me),
        ("GET", "/v1/devices", True, _devices),
        ("DELETE", r"/v1/devices/(\d+)", True, _revoke_device),
        ("POST", "/v1/recovery/rotate", True, _rotate_recovery),
        ("POST", "/v1/requests", True, _send_request),
        ("GET", "/v1/requests", True, _requests),
        ("POST", r"/v1/requests/(\d+)/accept", True, _answer(True)),
        ("POST", r"/v1/requests/(\d+)/decline", True, _answer(False)),
        ("DELETE", r"/v1/requests/(\d+)", True, _cancel_request),
        ("DELETE", r"/v1/friends/(\d+)", True, _unfriend),
        ("PUT", "/v1/presence", True, _set_presence),
        ("DELETE", "/v1/presence", True, _clear_presence),
        ("POST", "/v1/sessions", True, _upload_sessions),
        ("POST", "/v1/sessions/delete", True, _delete_sessions),
        ("GET", "/v1/friends", True, _friends),
        ("GET", "/v1/leaderboard", True, _leaderboard),
    )
]


# -- HTTP plumbing ---------------------------------------------------------


class FriendsHandler(BaseHTTPRequestHandler):
    server_version = "LauncherFriends/1"
    #: Set on the class by make_server.
    store: Store
    quiet = False

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        try:
            status, payload = self._handle(method)
        except ApiError as e:
            status = e.status
            payload = {"error": e.code, "detail": e.detail}
        except NotFoundError:
            status, payload = HTTPStatus.NOT_FOUND, {"error": "not_found", "detail": ""}
        except Exception as e:  # noqa: BLE001 - one bad request must not stop the server
            print(f"error handling {method} {self.path}: {e!r}", file=sys.stderr)
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            payload = {"error": "server_error", "detail": ""}
        self._send(status, payload)

    def _handle(self, method: str) -> tuple[HTTPStatus, Any]:
        parts = urlsplit(self.path)
        allowed = False
        for route_method, pattern, needs_auth, handler in ROUTES:
            match = pattern.match(parts.path)
            if match is None:
                continue
            allowed = True
            if route_method != method:
                continue
            user = self._user() if needs_auth else None
            if needs_auth and user is None:
                raise ApiError(HTTPStatus.UNAUTHORIZED, "unauthorized")
            query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
            return handler(self.store, Request(user, self._body(), query, match.groups()))
        if allowed:
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed")
        raise NotFoundError

    def _user(self) -> User | None:
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return self.store.authenticate(token.strip())

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _bad("bad Content-Length") from None
        if length > MAX_BODY:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too_large")
        if length <= 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _bad("body is not JSON") from None
        if not isinstance(body, dict):
            raise _bad("body must be a JSON object")
        return body

    def _send(self, status: HTTPStatus, payload: Any) -> None:
        data = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(format, *args)


def make_server(
    store: Store, host: str = "127.0.0.1", port: int = 8765, *, quiet: bool = False
) -> ThreadingHTTPServer:
    """A server ready for serve_forever(). Port 0 picks a free one."""
    handler = type("BoundFriendsHandler", (FriendsHandler,), {"store": store, "quiet": quiet})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
