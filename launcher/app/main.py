"""Application entry point."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from launcher.app.context import AppContext
from launcher.app.library_controller import LibraryController
from launcher.app.single_instance import SingleInstance
from launcher.app.startup import StartupProfiler
from launcher.ui.main_window import MainWindow
from launcher.ui.theme import Appearance, apply_theme
from launcher.ui.theme.custom import CustomThemeStore


def build_window(context: AppContext) -> MainWindow:
    """Wire a window to a context. Shared with the tests."""
    controller = LibraryController(context)
    window = MainWindow(controller)
    if context.paths.icon.is_file():
        window.setWindowIcon(QIcon(str(context.paths.icon)))
    return window


def parse_launch_request(argv: list[str]) -> tuple[str | None, bool]:
    """The game to play from the command line, and profile verbosity.

    Accepts ``milso-launcher --play "Name"`` or a bare ``milso-launcher
    "Name"``; anything starting with ``-`` is a flag, never a game.
    """
    game: str | None = None
    profile = False
    args = list(argv[1:])
    while args:
        arg = args.pop(0)
        if arg == "--profile":
            profile = True
        elif arg in ("--import-profile", "--export-profile"):
            # Handled headless in maybe_handle_profile_cli() before Qt starts.
            if args and not args[0].startswith("-"):
                args.pop(0)
        elif arg == "--play" and args:
            game = args.pop(0)
        elif arg == "--play":
            game = None
        elif not arg.startswith("-") and game is None:
            game = arg
    return game, profile


def _profile_cli_args(argv: list[str]) -> tuple[str | None, str | None]:
    import_profile = export_profile = None
    i = 0
    while i < len(args := argv):
        if args[i] == "--import-profile" and i + 1 < len(args):
            import_profile = args[i + 1]
            i += 2
        elif args[i] == "--export-profile" and i + 1 < len(args):
            export_profile = args[i + 1]
            i += 2
        else:
            i += 1
    return import_profile, export_profile


def _import_profile_file(store: object, paths: object, src: str) -> None:
    """Adopt a profile backup, keeping the local upload cursor when missing."""
    import json

    from launcher.data.state_store import StateStore
    from launcher.services.friends import Account, AccountFile
    from launcher.services.friends_client import check_url

    assert isinstance(store, AccountFile)
    try:
        data = dict(AccountFile.read_export(src))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"import failed: {e}", file=sys.stderr)
        sys.exit(1)
    account = store.load()
    try:
        state = StateStore(paths.state_db)  # type: ignore[attr-defined]
        try:
            tip = state.last_session_id()
        finally:
            state.close()
    except (OSError, ValueError):
        tip = 0
    try:
        cursor = int(data.get("uploaded_through", -1))
    except (TypeError, ValueError):
        cursor = -1
    if not str(data.get("client_id") or "") or cursor < 0:
        data["client_id"] = account.client_id or str(data.get("client_id") or "")
        data["uploaded_through"] = max(account.uploaded_through, tip)
    try:
        server = check_url(str(data["server"]).strip().rstrip("/"))
    except ValueError as e:
        print(f"import failed: {e}", file=sys.stderr)
        sys.exit(1)
    new_account = Account(
        server=server,
        token=str(data.get("token") or ""),
        user_id=int(data.get("user_id") or 0),
        display_name=str(data.get("display_name") or ""),
        friend_code=str(data.get("friend_code") or ""),
        client_id=str(data.get("client_id") or account.client_id),
        uploaded_through=int(data.get("uploaded_through") or 0),
    )
    store.save(new_account)
    print(f"imported profile for {new_account.display_name} ({new_account.friend_code})")
    if data.get("recovery_key"):
        print("recovery key included — store it somewhere safe, then delete this file.")


def maybe_handle_profile_cli(argv: list[str] | None = None) -> bool:
    """Handle --import-profile/--export-profile without starting Qt.

    Returns True when a profile command ran (the caller should exit).
    """
    from pathlib import Path

    args = list(sys.argv[1:] if argv is None else argv)
    import_profile, export_profile = _profile_cli_args(args)
    if not import_profile and not export_profile:
        return False
    from launcher.data.paths import Paths
    from launcher.services.friends import AccountFile

    paths = Paths.default()
    store = AccountFile(paths)
    if import_profile:
        _import_profile_file(store, paths, import_profile)
    if export_profile:
        account = store.load()
        if not account.registered:
            print("no profile to export (not registered)", file=sys.stderr)
            sys.exit(1)
        store.export_profile(account, Path(export_profile), server_url=account.server)
        print(f"exported profile for {account.display_name} to {export_profile} (0600)")
    return True


def main() -> None:
    if maybe_handle_profile_cli():
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setApplicationName("Milso Launcher")
    app.setApplicationDisplayName("Milso Launcher")
    app.setDesktopFileName("milso-launcher")
    requested_game, profile = parse_launch_request(sys.argv)

    guard = SingleInstance(parent=app)
    if not guard.try_acquire():
        lines = ["show"]
        if requested_game:
            lines.append(f"play:{requested_game}")
        guard.forward(lines)
        sys.exit(0)

    profiler = StartupProfiler()
    with profiler.stage("context"):
        context = AppContext.create(profiler=profiler)
    with profiler.stage("theme"):
        # The user's themes first, so a saved choice of one of them is valid.
        CustomThemeStore(context.paths.themes_dir).load_all()
        apply_theme(app, Appearance.from_settings(context.settings))
        if context.paths.icon.is_file():
            app.setWindowIcon(QIcon(str(context.paths.icon)))

    with profiler.stage("window"):
        window = build_window(context)
    app.aboutToQuit.connect(context.close)

    def _on_forwarded(line: str) -> None:
        window._show_window()
        if line.startswith("play:"):
            window.play_game(line[len("play:"):])

    guard.message_received.connect(_on_forwarded)

    # Ctrl-C in the terminal should close the window rather than be
    # swallowed by the Qt event loop.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    window.show()
    if profile:
        for name, milliseconds in profiler.report():
            print(f"startup {name}: {milliseconds:.0f}ms")
    if requested_game:
        QTimer.singleShot(0, lambda: window.play_game(requested_game))
    # After the window is up, so the prompt has something behind it.
    QTimer.singleShot(0, window.offer_tray_choice)
    QTimer.singleShot(0, window.offer_artwork_cleanup)
    QTimer.singleShot(0, window.share_saves_everywhere)
    QTimer.singleShot(0, window.check_for_updates_on_startup)
    QTimer.singleShot(0, window.announce_recovered_sessions)
    QTimer.singleShot(0, window.offer_changelog)
    # Does nothing in Offline Mode, the default.
    QTimer.singleShot(0, context.friends.start)
    # Does nothing until enabled in Settings -> Discord.
    QTimer.singleShot(0, context.discord.start)

    sys.exit(app.exec())
