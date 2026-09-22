"""The failure card: what went wrong, and what to do next.

Shown modelessly when a session looks like a crash (or a launch dies in
seconds): the assessed reason, any pre-launch warnings, and the tail of
the persisted game log, with actions for the useful next steps. It never
blocks the library; the game can be fixed and relaunched beside it.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.ui.errors import copy_text


class LaunchFailureDialog(QDialog):
    """A modeless diagnosis card for one failed game."""

    def __init__(
        self,
        context: AppContext,
        game_name: str,
        summary: str = "",
        hint: str = "",
        *,
        warnings: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._name = game_name
        self.setWindowTitle(f"{game_name} — failed to start")
        self.resize(640, 480)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._setup_ui(summary, hint, warnings or [])

    # -- layout ----------------------------------------------------------

    def _setup_ui(self, summary: str, hint: str, warnings: list[str]) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(10)

        title = QLabel(summary or "The game exited quickly.")
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        outer.addWidget(title)

        lines = list(warnings)
        if hint:
            lines.append(hint)
        if lines:
            tip = QLabel("\n".join(lines))
            tip.setObjectName("hintLabel")
            tip.setWordWrap(True)
            outer.addWidget(tip)

        section = QLabel("Log tail")
        section.setObjectName("hintLabel")
        outer.addWidget(section)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setObjectName("input")
        tail = self._ctx.logs.recent(self._name).splitlines()[-120:]
        self._log_view.setPlainText("\n".join(tail) or "(no output captured)")
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )
        outer.addWidget(self._log_view, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(8)
        copy_btn = QPushButton("Copy log")
        copy_btn.clicked.connect(self._copy_log)
        row.addWidget(copy_btn)
        dry_btn = QPushButton("Dry run")
        dry_btn.setToolTip("Show the prefix, Proton and environment a launch would use")
        dry_btn.clicked.connect(self._dry_run)
        row.addWidget(dry_btn)
        prefix_btn = QPushButton("Open prefix")
        prefix_btn.clicked.connect(self._open_prefix)
        row.addWidget(prefix_btn)
        row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)
        outer.addLayout(row)

    # -- actions ---------------------------------------------------------

    def _copy_log(self) -> None:
        copy_text(self._ctx.logs.recent(self._name))

    def _dry_run(self) -> None:
        import shutil

        script = self._ctx.paths.launcher_script
        if not script.is_file():
            self._log_view.appendPlainText(f"Launcher script not found: {script}")
            return
        shell = shutil.which("bash") or "bash"
        try:
            out = subprocess.run(  # noqa: S603 - resolved shell, fixed argv
                [shell, str(script), "--dry-run", self._name],
                capture_output=True,
                text=True,
                check=False,
                cwd=self._ctx.paths.base,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError) as e:
            self._log_view.appendPlainText(f"Dry run failed: {e}")
            return
        self._log_view.appendPlainText("\n── dry run ──\n" + (out.stdout or out.stderr))

    def _open_prefix(self) -> None:
        game = self._ctx.games.get(self._name)
        prefix = game.prefix if game is not None else ""
        self._ctx.prefix_tools.open_folder(prefix)
