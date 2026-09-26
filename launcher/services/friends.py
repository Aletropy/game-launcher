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
    #: Human label for this install in the devices list.
    device_name: str = ""
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


PROFILE_EXPORT_VERSION = 1


class AccountFile:
    """friends.json: holds a token, so it is readable by its owner only."""

    def __init__(self, paths: Paths) -> None:
        self._path = paths.friends_file
        #: Keys from a newer version, kept so downgrades don't discard them.
        self._extra: dict[str, Any] = {}

    def _candidates(self) -> list[Any]:
        return [
            self._path,
            self._path.with_suffix(".json.bak"),
            self._path.parent / "friends.json.pre-profile-v2.bak",
        ]

    def _parse(self, raw: object) -> Account | None:
        if not isinstance(raw, dict):
            return None
        known = {k: v for k, v in raw.items() if k in Account.__dataclass_fields__}
        try:
            account = Account(**known)
        except TypeError:
            return None
        self._extra = {k: v for k, v in raw.items() if k not in Account.__dataclass_fields__}
        return account

    def load(self) -> Account:
        self._extra = {}
        for candidate in self._candidates():
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            account = self._parse(raw)
            if account is not None:
                # A backup saved the day: restore it as the primary file so
                # the next save doesn't need the fallback again.
                if candidate != self._path:
                    with contextlib.suppress(OSError):
                        self.save(account)
                return account
        return Account()

    def save(self, account: Account) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_file():
            # One backup generation + one pre-upgrade copy, kept once.
            # The live file is never truncated before its copy lands.
            with contextlib.suppress(OSError):
                import shutil

                shutil.copy2(self._path, self._path.with_suffix(".json.bak"))
                pre = self._path.parent / "friends.json.pre-profile-v2.bak"
                if not pre.is_file():
                    shutil.copy2(self._path, pre)
        payload = {**self._extra, **asdict(account)}
        tmp = self._path.with_suffix(".json.tmp")
        # Created private rather than chmod-ed after: never readable by others.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp.replace(self._path)

    # -- portable backup -------------------------------------------------

    def export_profile(
        self,
        account: Account,
        dest: Any,
        *,
        server_url: str = "",
        recovery_key: str = "",
    ) -> Any:
        """Write a portable recovery file (0600). Returns the path."""
        from pathlib import Path as _Path

        dest = _Path(dest)
        payload: dict[str, Any] = {
            "version": PROFILE_EXPORT_VERSION,
            "server": server_url or account.server,
            "user_id": account.user_id,
            "display_name": account.display_name,
            "friend_code": account.friend_code,
            "token": account.token,
            "client_id": account.client_id,
            "uploaded_through": account.uploaded_through,
            "exported": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }
        if recovery_key:
            payload["recovery_key"] = recovery_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp.replace(dest)
        return dest

    @staticmethod
    def read_export(dest: Any) -> dict[str, Any]:
        from pathlib import Path as _Path

        raw = json.loads(_Path(dest).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("profile file must be a JSON object")
        for key in ("server", "token"):
            if not isinstance(raw.get(key), str) or not str(raw.get(key)).strip():
                raise ValueError(f"profile file is missing {key!r}")
        return raw


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
        #: Recovery key shown once after register/rotate, until saved.
        self._pending_recovery_key = ""

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
        if self._status is FriendsState.RECOVERY:
            return False
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
            # Never wipe on a 401: the DB may have been restored, the wrong
            # --db picked, or the device revoked. Keep the local copy so a
            # backup or recovery key can bring the same user_id back.
            self._enter_recovery(str(error))
            if fail is not None:
                fail(error)
        elif fail is not None:
            fail(error)
        else:
            self.notice.emit(str(error))

    def _enter_recovery(self, message: str = "") -> None:
        """Park in RECOVERY, keeping token/client_id/uploaded_through."""
        self.stop()
        self._presence = None
        if self.online_mode and self._started:
            self._set_state(FriendsState.RECOVERY)
        if message:
            self.notice.emit(
                f"{message}. Your play history is safe here;"
                " restore a profile backup or reclaim with your recovery key."
            )

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
        if isinstance(error, AuthError):
            # _handle_error already parked us in RECOVERY; don't override.
            return
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
        from launcher import platform as _platform

        def done(result: dict[str, Any]) -> None:
            # A fresh profile starts its upload from the beginning.
            # uploaded_through resets (new user_id), but client_id stays so
            # session ids keep their shape across re-registers on this PC.
            self._account = Account(
                server=url,
                token=str(result.get("token", "")),
                user_id=int(result.get("user_id", 0)),
                display_name=str(result.get("display_name", name)),
                friend_code=str(result.get("friend_code", "")),
                device_name=_platform.device_name(),
                client_id=self._account.client_id,
                uploaded_through=0,
            )
            self._save_account()
            if self._client is not None:
                self._client.token = self._account.token
            recovery = str(result.get("recovery_key", ""))
            if recovery:
                self._pending_recovery_key = recovery
                self.notice.emit(
                    "Profile created. Save your recovery key now"
                    " (Friends → Show recovery key) — it restores this exact"
                    f" profile if this file is lost. Code: {self._account.friend_code}"
                )
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
        """Explicit delete only: drop the token after the user confirmed."""
        self.stop()
        self._presence = None
        self._snapshot = None
        self._pending_recovery_key = ""
        self._account = Account(client_id=self._account.client_id)
        self._save_account()
        if self._client is not None:
            self._client.token = ""
        if self.online_mode and self._started:
            self._set_state(FriendsState.UNREGISTERED)

    def _save_account(self) -> None:
        with contextlib.suppress(OSError):
            self._file.save(self._account)

    # -- backup / recovery -------------------------------------------------

    @property
    def pending_recovery_key(self) -> str:
        """A recovery key shown once, until the user saves it."""
        return self._pending_recovery_key

    def export_profile(self, dest: Any, *, recovery_key: str = "") -> Any:
        """Write a portable backup of this profile. Returns the path."""
        key = recovery_key or self._pending_recovery_key
        return self._file.export_profile(
            self._account, dest, server_url=self._normalised_url(), recovery_key=key
        )

    def import_profile_data(self, data: dict[str, Any]) -> Account:
        """Adopt a profile backup, preserving upload cursor when possible.

        Full exports carry client_id + uploaded_through, so re-importing on
        the same machine is idempotent. Bare reclaim responses (no cursor)
        are treated as a new device: the cursor jumps to the local tip so
        existing local sessions aren't re-uploaded as duplicates.
        """
        from launcher import platform as _platform
        from launcher.services.friends_client import check_url

        server = str(data.get("server") or "").strip().rstrip("/")
        token = str(data.get("token") or "").strip()
        if not server or not token:
            raise ValueError("profile file is missing server/token")
        try:
            server = check_url(server)
        except ValueError:
            raise ValueError(f"profile server address is not valid: {server!r}") from None
        try:
            user_id = int(data.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
        imported_client = str(data.get("client_id") or "")
        imported_cursor = data.get("uploaded_through")
        try:
            imported_cursor = int(imported_cursor if imported_cursor is not None else -1)
        except (TypeError, ValueError):
            imported_cursor = -1
        if imported_client and imported_cursor >= 0:
            client_id, cursor = imported_client, imported_cursor
        else:
            # New device without a cursor: don't re-upload local history.
            client_id = self._account.client_id or imported_client or uuid.uuid4().hex[:12]
            try:
                cursor = self._state.last_session_id()
            except (OSError, ValueError):
                cursor = 0
        self._account = Account(
            server=server,
            token=token,
            user_id=user_id,
            display_name=str(data.get("display_name") or ""),
            friend_code=str(data.get("friend_code") or ""),
            device_name=_platform.device_name(),
            client_id=client_id,
            uploaded_through=cursor,
        )
        self._save_account()
        self._pending_recovery_key = str(data.get("recovery_key") or "")
        self._snapshot = None
        self._failures = 0
        self._apply_mode()
        return self._account

    def import_profile_file(self, dest: Any) -> Account:
        return self.import_profile_data(AccountFile.read_export(dest))

    def rotate_recovery(self) -> None:
        """Mint a fresh recovery key; the tab shows it once via notice."""
        if not self._is_live() or self._client is None:
            self.notice.emit("Go online first, then ask for a recovery key.")
            return
        client = self._client

        def done(key: object) -> None:
            self._pending_recovery_key = str(key)
            self.notice.emit(
                "New recovery key — save it now (it is shown only here):"
                f" {self._pending_recovery_key}"
            )

        self._run(client.rotate_recovery, ok=done)

    def reclaim(self, friend_code: str, recovery_key: str) -> None:
        """Restore the same user_id on this install with code + recovery key."""
        if self._client is None:
            self.notice.emit("Set the server address first.")
            return
        from launcher.domain.friends import format_code as _fmt

        client = self._client
        code = _fmt(friend_code)
        key = recovery_key.strip()
        if not key:
            self.notice.emit("Enter your recovery key.")
            return

        def done(result: dict[str, Any]) -> None:
            payload = dict(result)
            payload["server"] = self._normalised_url()
            # No cursor in a reclaim response: import treats it as a new
            # device and pins the cursor to the local tip.
            self.import_profile_data(payload)
            self.notice.emit("Profile restored — same name, code, friends and history.")

        def failed(error: FriendsError) -> None:
            self.notice.emit(str(error))

        self._set_state(FriendsState.CONNECTING)
        self._run(client.reclaim, code, key, ok=done, fail=failed)

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
        from launcher import platform as _platform

        here = _platform.app_platform()
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
                    "platform": here,
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

