"""Friends: the one object that talks to the friends server.

Opt-in. In Offline Mode, the default, nothing is sent or fetched and the
rest of the launcher behaves as though this did not exist. Online, it
uploads play history, says what is being played, and polls for what
friends are doing.

No failure here ever reaches the library: an unreachable server only
changes what the Friends tab shows, and every call runs off the GUI
thread.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from launcher.data.game_repository import GameRepository
from launcher.data.paths import Paths
from launcher.data.settings_store import SettingsStore
from launcher.data.state_store import StateStore
from launcher.domain import journal
from launcher.domain.friends import (
    BoardPeriod,
    FriendsSnapshot,
    FriendsState,
    format_code,
    game_key,
    name_key,
)
from launcher.services.friends_client import (
    AuthError,
    FriendsClient,
    FriendsError,
    ServerUnreachableError,
    check_url,
)
from launcher.services.process import ProcessService
from launcher.services.tasks import TaskGroup

#: Overrides the server address, e.g. http://127.0.0.1:8765 while developing.
SERVER_ENV = "MILSO_FRIENDS_SERVER"
_LEGACY_SERVER_ENV = "LAUNCHER_FRIENDS_SERVER"

#: Poll intervals, in seconds.
POLL_VISIBLE = 30
POLL_HIDDEN = 120
#: Retries after a failure back off through these.
BACKOFF = (30, 60, 120, 300)
#: Presence expires on the server after 150 s; beat well inside that.
HEARTBEAT = 60
UPLOAD_BATCH = 500


@dataclass
class Account:
    """The profile on one server, as kept in friends.json."""

    server: str = ""
    token: str = ""
    user_id: int = 0
    display_name: str = ""
    friend_code: str = ""
    #: Identifies this install's sessions, so ids never clash across PCs.
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    #: The largest local session id uploaded so far.
    uploaded_through: int = 0
    #: Game keys cleared locally while offline, to clear on the server too.
    pending_forget: list[str] = field(default_factory=list)
    #: True when every game's history was cleared while offline.
    pending_forget_all: bool = False

    @property
    def registered(self) -> bool:
        return bool(self.token)


class AccountFile:
    """friends.json: holds a token, so it is readable by its owner only."""

    def __init__(self, paths: Paths) -> None:
        self._path = paths.friends_file

    def load(self) -> Account:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Account()
        if not isinstance(raw, dict):
            return Account()
        known = {k: v for k, v in raw.items() if k in Account.__dataclass_fields__}
        try:
            return Account(**known)
        except TypeError:
            return Account()

    def save(self, account: Account) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        # Created private rather than chmod-ed after: never readable by others.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(account), handle, indent=2)
        tmp.replace(self._path)


class FriendsService(QObject):
    """Presence, history upload and polling, or nothing at all when offline."""

    state_changed = Signal(object)
    snapshot_changed = Signal(object)
    #: A short message for the Friends tab: "Request sent", an error.
    notice = Signal(str)

    def __init__(
        self,
        paths: Paths,
        settings: SettingsStore,
        state: StateStore,
        games: GameRepository,
        processes: ProcessService,
        *,
        parent: QObject | None = None,
        client_factory: Callable[[str, str], FriendsClient] = FriendsClient,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._state = state
        self._games = games
        self._processes = processes
        self._client_factory = client_factory
        self._file = AccountFile(paths)
        self._account = self._file.load()
        self._client: FriendsClient | None = None
        self._status = FriendsState.OFFLINE
        self._snapshot: FriendsSnapshot | None = None
        self._started = False

        self._tasks = TaskGroup(self)
        self._tasks.finished.connect(self._on_task_finished)
        self._tasks.failed.connect(self._on_task_failed)
        #: token -> (on success, on failure)
        self._pending: dict[
            int, tuple[Callable[[Any], None] | None, Callable[[FriendsError], None] | None]
        ] = {}

        self._visible = False
        self._failures = 0
        self._refreshing = False
        self._refresh_again = False
        self._uploading = False
        self._upload_again = False
        self._board_period = BoardPeriod.WEEK
        self._board_game = ""
        #: The game presence is being sent for, as (key, name).
        self._presence: tuple[str, str] | None = None

        self._poll = QTimer(self)
        self._poll.setSingleShot(True)
        self._poll.timeout.connect(self.refresh)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT * 1000)
        self._heartbeat.timeout.connect(self._beat)

        settings.changed.connect(self._on_setting_changed)
        processes.game_started.connect(self._on_game_started)
        processes.game_finished.connect(self._on_game_finished)
        processes.session_recorded.connect(self._on_session_recorded)

    # -- state -----------------------------------------------------------

    @property
    def state(self) -> FriendsState:
        return self._status

    @property
    def snapshot(self) -> FriendsSnapshot | None:
        return self._snapshot

    @property
    def account(self) -> Account:
        return self._account

    @property
    def online_mode(self) -> bool:
        return self._settings.get_str("friends_mode") == "online"

    @property
    def server_url(self) -> str:
        return (
            os.environ.get(SERVER_ENV, "").strip()
            or os.environ.get(_LEGACY_SERVER_ENV, "").strip()
            or self._settings.get_str("friends_server_url")
        )

    @property
    def share_presence(self) -> bool:
        return self._settings.get_bool("friends_share_presence")

    @property
    def registered_here(self) -> bool:
        """A profile exists on the server currently configured."""
        return self._account.registered and self._account.server == self._normalised_url()

    def _normalised_url(self) -> str:
        try:
            return check_url(self.server_url)
        except ValueError:
            return ""

    def _set_state(self, status: FriendsState) -> None:
        if status is not self._status:
            self._status = status
            self.state_changed.emit(status)

    def _is_live(self) -> bool:
        return self._client is not None and self.registered_here

    # -- lifetime --------------------------------------------------------

    def start(self) -> None:
        """Begin, if Online. Called once the window is up."""
        self._started = True
        self._apply_mode()

    def stop(self) -> None:
        """Stop all timers and drop work in flight. Sends nothing."""
        self._poll.stop()
        self._heartbeat.stop()
        self._tasks.cancel_all()
        self._pending.clear()
        self._refreshing = self._uploading = False

    def set_visible(self, visible: bool) -> None:
        """The Friends tab is on screen: poll more often, and now."""
        was = self._visible
        self._visible = visible
        if visible and not was and self._status in (FriendsState.ONLINE, FriendsState.UNREACHABLE):
            self.refresh()

    def _apply_mode(self) -> None:
        if not self._started:
            return
        if not self.online_mode:
            self._go_offline()
            return
        url = self._normalised_url()
        if not url:
            self.stop()
            self._client = None
            self._set_state(FriendsState.UNREACHABLE)
            self.notice.emit(f"The friends server address is not valid: {self.server_url}")
            return
        token = self._account.token if self._account.server == url else ""
        self._client = self._client_factory(url, token)
        if not token:
            self.stop()
            self._set_state(FriendsState.UNREGISTERED)
            return
        self._set_state(FriendsState.CONNECTING)
        self._after_connect()

    def _go_offline(self) -> None:
        # One last word so friends don't see a game for another two
        # minutes; after this, nothing more is sent.
        if self._presence is not None and self._is_live():
            client = self._client
            assert client is not None
            self._tasks.submit(_quietly(client.clear_presence))
        self._presence = None
        self.stop()
        self._client = None
        self._snapshot = None
        self._set_state(FriendsState.OFFLINE)

    def _after_connect(self) -> None:
        # Clears made while offline go first, or they would delete
        # sessions uploaded a moment later.
        self._flush_forgets(then=self.sync_history)
        self._update_presence()
        self.refresh()

    def _on_setting_changed(self, key: str, _value: object) -> None:
        if key in ("friends_mode", "friends_server_url"):
            self._apply_mode()
        elif key == "friends_share_presence":
            self._update_presence()

    # -- running work ----------------------------------------------------

    def _run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        ok: Callable[[Any], None] | None = None,
        fail: Callable[[FriendsError], None] | None = None,
    ) -> None:
        token = self._tasks.submit(_capture(fn), *args)
        self._pending[token] = (ok, fail)

    def _on_task_finished(self, token: int, result: object) -> None:
        ok, fail = self._pending.pop(token, (None, None))
        if isinstance(result, FriendsError):
            self._handle_error(result, fail)
        elif ok is not None:
            ok(result)

    def _on_task_failed(self, token: int, message: str) -> None:
        # Not a FriendsError: a bug rather than the network. Treat it as
        # a server failure so the tab says something instead of hanging.
        _, fail = self._pending.pop(token, (None, None))
        self._handle_error(FriendsError(message), fail)

    def _handle_error(
        self, error: FriendsError, fail: Callable[[FriendsError], None] | None
    ) -> None:
        if isinstance(error, AuthError):
            self._forget_account()
            self.notice.emit(str(error))
        elif fail is not None:
            fail(error)
        else:
            self.notice.emit(str(error))

    # -- polling ---------------------------------------------------------

    def refresh(self) -> None:
        """Fetch friends, requests and the leaderboard, then poll again later."""
        if not self._is_live():
            return
        if self._refreshing:
            self._refresh_again = True
            return
        self._refreshing = True
        self._poll.stop()
        client = self._client
        assert client is not None
        since = int(journal.week_start().timestamp())
        period, game = self._board_period, self._board_game
        board_since = since if period is BoardPeriod.WEEK else None

        def fetch() -> FriendsSnapshot:
            overview = client.overview(since)
            requests = client.requests()
            board = client.leaderboard(board_since, game or None)
            return FriendsSnapshot.parse(
                overview, requests, board, board_period=period, board_game=game
            )

        self._run(fetch, ok=self._on_snapshot, fail=self._on_refresh_failed)

    def _on_snapshot(self, snapshot: FriendsSnapshot) -> None:
        self._refreshing = False
        self._failures = 0
        self._snapshot = snapshot
        # The name and code can change on another machine; keep ours current.
        if (snapshot.me.name, snapshot.friend_code) != (
            self._account.display_name,
            self._account.friend_code,
        ):
            self._account.display_name = snapshot.me.name
            self._account.friend_code = snapshot.friend_code
            self._save_account()
        self._set_state(FriendsState.ONLINE)
        self.snapshot_changed.emit(snapshot)
        if self._refresh_again:
            self._refresh_again = False
            self.refresh()
        else:
            self._schedule(POLL_VISIBLE if self._visible else POLL_HIDDEN)

    def _on_refresh_failed(self, error: FriendsError) -> None:
        self._refreshing = False
        self._refresh_again = False
        self._failures += 1
        self._set_state(FriendsState.UNREACHABLE)
        if not isinstance(error, ServerUnreachableError):
            self.notice.emit(str(error))
        self._schedule(BACKOFF[min(self._failures, len(BACKOFF)) - 1])

    def _schedule(self, seconds: int) -> None:
        if self._is_live():
            self._poll.start(seconds * 1000)

    def set_board(self, period: BoardPeriod, game: str = "") -> None:
        """Change what the leaderboard ranks, and fetch it."""
        if (period, game) == (self._board_period, self._board_game):
            return
        self._board_period, self._board_game = period, game
        self.refresh()

    @property
    def board(self) -> tuple[BoardPeriod, str]:
        return self._board_period, self._board_game

    # -- account ---------------------------------------------------------

    def register(self, display_name: str) -> None:
        """Create a profile on the configured server."""
        name = " ".join(display_name.split())
        if not name or self._client is None:
            return
        url = self._normalised_url()
        client = self._client

        def done(result: dict[str, Any]) -> None:
            # A fresh profile starts its upload from the beginning.
            self._account = Account(
                server=url,
                token=str(result.get("token", "")),
                user_id=int(result.get("user_id", 0)),
                display_name=str(result.get("display_name", name)),
                friend_code=str(result.get("friend_code", "")),
                client_id=self._account.client_id,
            )
            self._save_account()
            if self._client is not None:
                self._client.token = self._account.token
            self._set_state(FriendsState.CONNECTING)
            self._after_connect()

        def failed(error: FriendsError) -> None:
            self._set_state(FriendsState.UNREGISTERED)
            self.notice.emit(str(error))

        self._set_state(FriendsState.CONNECTING)
        self._run(client.register, name, ok=done, fail=failed)

    def rename(self, display_name: str) -> None:
        name = " ".join(display_name.split())
        if not name or not self._is_live() or name == self._account.display_name:
            return
        client = self._client
        assert client is not None
        self._run(client.rename, name, ok=lambda _r: self.refresh())

    def delete_account(self, on_done: Callable[[bool, str], None] | None = None) -> None:
        """Delete the profile and everything uploaded, then go Offline."""

        def done(_result: object) -> None:
            self._forget_account()
            self._settings.set("friends_mode", "offline")
            if on_done is not None:
                on_done(True, "Your friends profile and everything it shared were deleted.")

        def failed(error: FriendsError) -> None:
            if on_done is not None:
                on_done(False, str(error))

        if not self._is_live():
            # Nothing on this server; just forget the local copy.
            done(None)
            return
        client = self._client
        assert client is not None
        self._run(client.delete_account, ok=done, fail=failed)

    def _forget_account(self) -> None:
        """Drop the token: the server no longer knows it, or it was deleted."""
        self.stop()
        self._presence = None
        self._snapshot = None
        self._account = Account(client_id=self._account.client_id)
        self._save_account()
        if self._client is not None:
            self._client.token = ""
        if self.online_mode and self._started:
            self._set_state(FriendsState.UNREGISTERED)

    def _save_account(self) -> None:
        with contextlib.suppress(OSError):
            self._file.save(self._account)

    # -- friends ---------------------------------------------------------

    def _act(self, fn: Callable[..., Any], *args: Any, message: str) -> None:
        if not self._is_live():
            return

        def done(_result: object) -> None:
            if message:
                self.notice.emit(message)
            self.refresh()

        self._run(fn, *args, ok=done)

    def send_request(self, code: str) -> None:
        if self._client is None:
            return
        self._act(
            self._client.send_request,
            format_code(code),
            message="Request sent. They'll show up here once they accept.",
        )

    def answer(self, request_id: int, accept: bool) -> None:
        if self._client is None:
            return
        self._act(self._client.answer, request_id, accept, message="")

    def cancel_request(self, request_id: int) -> None:
        if self._client is not None:
            self._act(self._client.cancel_request, request_id, message="Request withdrawn.")

    def unfriend(self, user_id: int) -> None:
        if self._client is not None:
            self._act(self._client.unfriend, user_id, message="Removed.")

    # -- presence --------------------------------------------------------

    def _key_for(self, name: str) -> str:
        game = self._games.get(name)
        return game_key(game.config) if game is not None else name_key(name)

    def _on_game_started(self, _name: str) -> None:
        self._update_presence()

    def _on_game_finished(self, _name: str, _code: int) -> None:
        self._update_presence()

    def _update_presence(self) -> None:
        """Send what is being played now, or that nothing is."""
        if not self._is_live():
            return
        running = self._processes.running_games
        wanted = None
        if running and self.share_presence:
            # The most recently started game is the one being played.
            name = running[-1]
            wanted = (self._key_for(name), name)
        if wanted == self._presence:
            return
        client = self._client
        assert client is not None
        self._presence = wanted
        if wanted is None:
            self._heartbeat.stop()
            self._run(client.clear_presence, fail=_ignore)
        else:
            self._heartbeat.start()
            self._run(client.set_presence, *wanted, fail=_ignore)
        # Show yourself as playing without waiting for the next poll.
        QTimer.singleShot(1500, self.refresh)

    def _beat(self) -> None:
        if self._presence is None or not self._is_live():
            self._heartbeat.stop()
            return
        client = self._client
        assert client is not None
        self._run(client.set_presence, *self._presence, fail=_ignore)

    # -- history ---------------------------------------------------------

    def _on_session_recorded(self, _name: str, _seconds: int) -> None:
        # The controller writes the session from the same signal; let it
        # land in the database before reading it back.
        QTimer.singleShot(0, self.sync_history)

    def sync_history(self) -> None:
        """Upload sessions not sent yet, a batch at a time."""
        if not self._is_live():
            return
        if self._uploading:
            self._upload_again = True
            return
        batch = self._state.sessions_after(self._account.uploaded_through, UPLOAD_BATCH)
        if not batch:
            return
        keys: dict[str, str] = {}
        payload = []
        for local_id, session in batch:
            if session.name not in keys:
                keys[session.name] = self._key_for(session.name)
            payload.append(
                {
                    "id": f"{self._account.client_id}:{local_id}",
                    "game_key": keys[session.name],
                    "game_name": session.name,
                    "started": int(session.started.timestamp()),
                    "seconds": session.seconds,
                }
            )
        last_id = batch[-1][0]
        client = self._client
        assert client is not None
        self._uploading = True

        def done(_stored: object) -> None:
            self._uploading = False
            self._account.uploaded_through = last_id
            self._save_account()
            full = len(batch) == UPLOAD_BATCH
            if full or self._upload_again:
                self._upload_again = False
                self.sync_history()
            else:
                self.refresh()

        def failed(_error: FriendsError) -> None:
            # Picked up again on the next connect or session.
            self._uploading = False
            self._upload_again = False

        self._run(client.upload_sessions, payload, ok=done, fail=failed)

    def forget_games(self, names: list[str] | None) -> None:
        """Mirror a local history clear on the server.

        Online, it is sent now; otherwise it is remembered and sent the
        next time a connection is made, so a clear is never lost. None
        means every game.
        """
        if not self._account.registered:
            return
        if names is None:
            self._account.pending_forget_all = True
            self._account.pending_forget = []
        else:
            keys = {self._key_for(n) for n in names} | set(self._account.pending_forget)
            self._account.pending_forget = sorted(keys)
        self._save_account()
        self._flush_forgets()

    def _flush_forgets(self, then: Callable[[], None] | None = None) -> None:
        if not self._is_live():
            return
        everything = self._account.pending_forget_all
        keys = list(self._account.pending_forget)
        if not everything and not keys:
            if then is not None:
                then()
            return
        client = self._client
        assert client is not None

        def done(_result: object) -> None:
            if everything:
                self._account.pending_forget_all = False
            self._account.pending_forget = [
                k for k in self._account.pending_forget if k not in keys
            ]
            self._save_account()
            if then is not None:
                then()
            self.refresh()

        def failed(_error: FriendsError) -> None:
            # Kept for the next connect. Uploading now is safe: pending
            # clears only ever name sessions recorded before them.
            if then is not None:
                then()

        self._run(
            client.delete_sessions, None if everything else keys, ok=done, fail=failed
        )


def _capture(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Return a FriendsError instead of raising it, so its type survives."""

    def run(*args: Any) -> Any:
        try:
            return fn(*args)
        except FriendsError as e:
            return e

    return run


def _quietly(fn: Callable[[], Any]) -> Callable[[], None]:
    def run() -> None:
        with contextlib.suppress(FriendsError):
            fn()

    return run


def _ignore(_error: FriendsError) -> None:
    """For background sends whose failure changes nothing visible."""

