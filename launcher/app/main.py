"""Application entry point."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from launcher.app.context import AppContext
from launcher.app.library_controller import LibraryController
from launcher.ui.main_window import MainWindow
from launcher.ui.theme import apply_theme


def build_window(context: AppContext) -> MainWindow:
    """Wire a window to a context. Shared with the tests."""
    controller = LibraryController(context)
    window = MainWindow(controller)
    if context.paths.icon.is_file():
        window.setWindowIcon(QIcon(str(context.paths.icon)))
    return window


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Game Launcher")
    app.setApplicationDisplayName("Game Launcher")
    app.setDesktopFileName("game-launcher")
    apply_theme(app)

    context = AppContext.create()
    if context.paths.icon.is_file():
        app.setWindowIcon(QIcon(str(context.paths.icon)))

    window = build_window(context)
    app.aboutToQuit.connect(context.close)

    # Ctrl-C in the terminal should close the window rather than be
    # swallowed by the Qt event loop.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    window.show()
    # After the window is up, so the prompt has something behind it.
    QTimer.singleShot(0, window.offer_artwork_cleanup)
    QTimer.singleShot(0, window.share_saves_everywhere)

    sys.exit(app.exec())
