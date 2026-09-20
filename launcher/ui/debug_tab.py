"""Debug tab with live log viewer for running games."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class DebugTab(QWidget):
    """Debug tab showing stdout/stderr for each running game."""

    stop_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log_widgets: dict[str, QPlainTextEdit] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QHBoxLayout()
        header.setContentsMargins(16, 12, 16, 8)

        title = QLabel("Debug Output")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #e6edf3;")
        header.addWidget(title)
        header.addStretch()

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.clicked.connect(self._clear_all)
        header.addWidget(self._clear_btn)

        layout.addLayout(header)

        # Tabs for each running game
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._empty_label = QLabel("No games currently running")
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        self._update_empty()

    def add_game(self, game_name: str) -> None:
        if game_name in self._log_widgets:
            return

        log_widget = QPlainTextEdit()
        log_widget.setReadOnly(True)
        font = QFont("Monospace", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        log_widget.setFont(font)
        self._log_widgets[game_name] = log_widget

        # Tab with close button
        tab_container = QWidget()
        tab_layout = QVBoxLayout(tab_container)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(log_widget)

        stop_row = QHBoxLayout()
        stop_row.setContentsMargins(8, 4, 8, 4)
        stop_row.addStretch()
        stop_btn = QPushButton("Stop Game")
        stop_btn.setFixedHeight(28)
        stop_btn.clicked.connect(lambda: self.stop_requested.emit(game_name))
        stop_row.addWidget(stop_btn)
        tab_layout.addLayout(stop_row)

        self._tabs.addTab(tab_container, game_name)
        self._update_empty()

    def remove_game(self, game_name: str) -> None:
        widget = self._log_widgets.pop(game_name, None)
        if widget is None:
            return
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == game_name:
                self._tabs.removeTab(i)
                break
        self._update_empty()

    def append_output(self, game_name: str, text: str) -> None:
        log = self._log_widgets.get(game_name)
        if log is None:
            return
        log.moveCursor(QTextCursor.MoveOperation.End)
        log.insertPlainText(text)
        log.moveCursor(QTextCursor.MoveOperation.End)

    def _clear_all(self) -> None:
        for log in self._log_widgets.values():
            log.clear()

    def _update_empty(self) -> None:
        has_tabs = len(self._log_widgets) > 0
        self._empty_label.setVisible(not has_tabs)
        self._tabs.setVisible(has_tabs)
