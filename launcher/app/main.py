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
        elif arg == "--play" and args:
            game = args.pop(0)
        elif arg == "--play":
            game = None
        elif not arg.startswith("-") and game is None:
            game = arg
    return game, profile


def main() -> None:
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
