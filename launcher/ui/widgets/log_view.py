"""Live output for the selected game."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextDocumentLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: Keep logs bounded; a long session would otherwise grow without limit.
MAX_LINES = 5000


def new_document(max_lines: int = MAX_LINES) -> QTextDocument:
    """A log buffer for one game.

    QPlainTextEdit refuses a document that does not carry a
    QPlainTextDocumentLayout, so install one here rather than at each
    call site.
    """
    doc = QTextDocument()
    doc.setDocumentLayout(QPlainTextDocumentLayout(doc))
    doc.setMaximumBlockCount(max(100, max_lines))
    doc.setDefaultFont(QFont("Monospace", 10))
    return doc


def append(doc: QTextDocument, text: str) -> None:
    """Append output to a buffer, keeping the cursor at the end."""
    cursor = QTextCursor(doc)
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText(text)


class LogView(QWidget):
    """Displays one game's log buffer, with stop and clear actions.

    Buffers live in MainWindow and are swapped in with attach(), so a
    game keeps accumulating output while another game is selected.
    """

    stop_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMinimumHeight(120)
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(font)
        layout.addWidget(self._output)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch()

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.clicked.connect(self._copy)
        actions.addWidget(self._copy_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.clear_requested)
        actions.addWidget(self._clear_btn)

        self._stop_btn = QPushButton("Stop Game")
        self._stop_btn.clicked.connect(self.stop_requested)
        actions.addWidget(self._stop_btn)

        layout.addLayout(actions)
        self.set_running(False)

    def attach(self, doc: QTextDocument | None) -> None:
        """Show a buffer, or an empty placeholder when there is none."""
        if doc is None:
            self._output.setDocument(new_document())
            self._output.setPlaceholderText("This game is not running.")
        else:
            self._output.setDocument(doc)
        self._scroll_to_end()

    def set_running(self, running: bool) -> None:
        self._stop_btn.setEnabled(running)

    def _scroll_to_end(self) -> None:
        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def follow(self) -> None:
        """Keep the newest output visible if the user has not scrolled up."""
        bar = self._output.verticalScrollBar()
        if bar.value() >= bar.maximum() - 4 * bar.singleStep():
            bar.setValue(bar.maximum())

    def _copy(self) -> None:
        self._output.selectAll()
        self._output.copy()
        cursor = self._output.textCursor()
        cursor.clearSelection()
        self._output.setTextCursor(cursor)
