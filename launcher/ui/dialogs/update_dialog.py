"""The update prompt: a newer GitHub release is available.

Opened from the tiny update badge in the top bar. Downloading only
starts when the user picks Install now; Later dismisses until the next
launch and Skip silences this version until a newer one appears.
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

from launcher.services.updates import UpdateInfo


def _human(num_bytes: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if num_bytes >= scale:
            return f"{num_bytes / scale:.1f} {unit}"
    return f"{num_bytes} B"


class UpdateDialog(QDialog):
    """Ask what to do about a newer release."""

    def __init__(
        self,
        info: UpdateInfo,
        current: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._info = info
        #: What the user chose: "install", "later" or "skip".
        self.result_action = "later"
        self.setWindowTitle("Update available")
        self.resize(520, 420)
        self.setMinimumSize(440, 320)
        self._setup_ui(current)

    # -- layout --------------------------------------------------------

    def _setup_ui(self, current: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 14)
        outer.setSpacing(10)

        title = QLabel(f"Version {self._info.version} is available.")
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        outer.addWidget(title)

        subtitle = QLabel(f"You have {current or 'an older version'}.")
        subtitle.setObjectName("hintLabel")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        if self._info.notes.strip():
            notes = QPlainTextEdit()
            notes.setReadOnly(True)
            notes.setObjectName("input")
            notes.setPlainText(self._info.notes.strip()[:8000])
            notes.setFixedHeight(180)
            outer.addWidget(notes, stretch=1)
        else:
            outer.addStretch(stretch=1)

        meta_bits = []
        if self._info.size_bytes > 0:
            meta_bits.append(f"Download: {_human(self._info.size_bytes)}.")
        meta_bits.append("Installing restarts the launcher; games and settings are kept.")
        meta = QLabel(" ".join(meta_bits))
        meta.setObjectName("hintLabel")
        meta.setWordWrap(True)
        outer.addWidget(meta)

        buttons = QDialogButtonBox()
        self._install_btn = QPushButton("Install now")
        self._install_btn.setObjectName("playButton")
        self._install_btn.setDefault(True)
        self._install_btn.clicked.connect(self._choose_install)
        buttons.addButton(self._install_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        later = buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        later.clicked.connect(self._choose_later)

        skip = QPushButton("Skip this version")
        skip.setToolTip("Don't offer this version again")
        skip.clicked.connect(self._choose_skip)
        buttons.addButton(skip, QDialogButtonBox.ButtonRole.ActionRole)

        if self._info.page_url or self._info.url:
            view = QPushButton("View on GitHub")
            view.clicked.connect(self._open_release_page)
            buttons.addButton(view, QDialogButtonBox.ButtonRole.HelpRole)

        outer.addWidget(buttons)
        self._install_btn.setFocus()

    # -- choices ---------------------------------------------------------

    def _choose_install(self) -> None:
        self.result_action = "install"
        self.accept()

    def _choose_later(self) -> None:
        self.result_action = "later"
        self.reject()

    def _choose_skip(self) -> None:
        self.result_action = "skip"
        self.accept()

    def _open_release_page(self) -> None:
        url = self._info.page_url or self._info.url
        if url:
            QDesktopServices.openUrl(QUrl(url))
