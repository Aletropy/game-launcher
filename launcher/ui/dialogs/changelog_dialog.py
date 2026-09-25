"""What's new: the release notes of the version just installed.

Shown once, on the first startup after an update. Opened from the main
window after an upgrade is detected, and on demand from Settings →
About → What's new.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ChangelogDialog(QDialog):
    """The release notes of a version, read-only."""

    def __init__(
        self,
        version: str,
        notes: str,
        page_url: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_url = page_url
        self.setWindowTitle(f"What's new in {version}" if version else "What's new")
        self.resize(520, 420)
        self.setMinimumSize(440, 320)
        self._setup_ui(version, notes)

    def _setup_ui(self, version: str, notes: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 14)
        outer.setSpacing(10)

        title = QLabel(f"Updated to version {version}." if version else "What's new.")
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        outer.addWidget(title)

        cleaned = (notes or "").strip()[:8000]
        if cleaned:
            body = QPlainTextEdit()
            body.setReadOnly(True)
            body.setObjectName("input")
            body.setPlainText(cleaned)
            outer.addWidget(body, stretch=1)
        else:
            missing = QLabel(
                "No release notes were found for this version. "
                "They may need a network connection to load."
            )
            missing.setObjectName("hintLabel")
            missing.setWordWrap(True)
            outer.addWidget(missing)
            outer.addStretch(stretch=1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.AcceptRole)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        if self._page_url:
            view = QPushButton("View on GitHub")
            view.clicked.connect(self._open_release_page)
            buttons.addButton(view, QDialogButtonBox.ButtonRole.HelpRole)
        outer.addWidget(buttons)

    def _open_release_page(self) -> None:
        if self._page_url:
            QDesktopServices.openUrl(QUrl(self._page_url))
