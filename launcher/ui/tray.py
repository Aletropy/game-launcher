"""The system tray icon, its menu and its timers.

Owns everything about the tray except the window itself: availability,
the icon lifecycle, the per-game Stop rows with live elapsed times, and
the tooltip. The window connects the three signals and keeps no other
tray state.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget


class TrayController(QObject):
    """A tray icon driven by callbacks, so it never imports the app."""

    #: The user asked to see the window (left-click or Show).
    show_requested = Signal()
    #: The user chose Quit from the tray menu.
    quit_requested = Signal()
    #: The user chose Stop for one running game; carries its name.
    stop_requested = Signal(str)

    def __init__(
        self,
        icon: QIcon,
        running_games: Callable[[], list[str]],
        elapsed_seconds: Callable[[str], int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent or None)
        self._icon = icon
        self._running_games = running_games
        self._elapsed_seconds = elapsed_seconds
        self._tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        self._timer: QTimer | None = None
        self._hint_shown = False

    # -- state -----------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        try:
            return QSystemTrayIcon.isSystemTrayAvailable()
        except (AttributeError, RuntimeError):
            return False

    @property
    def active(self) -> bool:
        """Whether a tray icon is currently shown."""
        return self._tray is not None

    @staticmethod
    def format_elapsed(seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        minutes, secs = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {secs:02d}s" if secs else f"{minutes}m"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m"

    # -- lifecycle -------------------------------------------------------

    def sync(self, enabled: bool, window_visible: bool) -> None:
        """Create or drop the icon to match the setting and platform."""
        if not enabled or not self.is_available():
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setQuitOnLastWindowClosed(True)
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            if self._tray is not None:
                self._tray.hide()
                self._tray.deleteLater()
            self._tray = None
            self._menu = None
            return
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setQuitOnLastWindowClosed(False)
        if self._tray is None:
            self._tray = QSystemTrayIcon(self._icon, None)
            self._menu = QMenu()
            self._tray.setContextMenu(self._menu)
            self._tray.activated.connect(self._on_activated)
            self._timer = QTimer(self)
            self._timer.setInterval(5000)
            self._timer.timeout.connect(lambda: self.refresh(window_visible))
            self._timer.start()
            self._tray.show()
        self.refresh(window_visible)

    def refresh(self, window_visible: bool = True) -> None:
        """Rebuild the menu and tooltip, including live timers."""
        if self._tray is None or self._menu is None:
            return
        menu = self._menu
        menu.clear()
        running = sorted(self._running_games())
        toggle = QAction("Hide" if window_visible else "Show", self)
        toggle.triggered.connect(self.show_requested.emit)
        menu.addAction(toggle)
        menu.addSeparator()
        if running:
            header = QAction(f"{len(running)} playing", self)
            header.setEnabled(False)
            menu.addAction(header)
            for name in running:
                elapsed = self.format_elapsed(self._elapsed_seconds(name))
                stop = QAction(f"Stop {name} — {elapsed}", self)
                stop.triggered.connect(
                    lambda _checked=False, n=name: self.stop_requested.emit(n)
                )
                menu.addAction(stop)
            menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)
        if not running:
            self._tray.setToolTip("Milso Launcher")
        elif len(running) == 1:
            elapsed = self.format_elapsed(self._elapsed_seconds(running[0]))
            self._tray.setToolTip(f"Milso Launcher — Playing {running[0]} ({elapsed})")
        else:
            self._tray.setToolTip(f"Milso Launcher — {len(running)} games running")

    def hint_once(self) -> None:
        """Tell the user the app is still in the tray, at most once."""
        if self._hint_shown or self._tray is None:
            return
        self._hint_shown = True
        with contextlib.suppress(AttributeError, RuntimeError):
            self._tray.showMessage(
                "Milso Launcher",
                "Still running in the tray. Games keep playing and "
                "their time keeps counting.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click shows; right-click is the menu with per-game Stop.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_requested.emit()
