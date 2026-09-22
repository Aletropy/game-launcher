"""Tags and notes for one game.

A single small dialog: comma-separated tags on one line, free-form
notes below. Save applies both; Cancel changes nothing.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class OrganizeDialog(QDialog):
    """Edit a game's tags and notes."""

    def __init__(
        self,
        game_name: str,
        tags: tuple[str, ...],
        notes: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Organize — {game_name}")
        self.setMinimumWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)
        self._tags = QLineEdit(", ".join(tags))
        self._tags.setPlaceholderText("rpg, co-op, backlog")
        form.addRow("Tags", self._tags)
        hint = QLabel("Comma-separated. Search finds games by tag.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)
        outer.addLayout(form)

        outer.addWidget(QLabel("Notes"))
        self._notes = QPlainTextEdit(notes)
        self._notes.setPlaceholderText("Personal notes — builds, mods, where you left off…")
        self._notes.setFixedHeight(120)
        self._notes.setObjectName("input")
        outer.addWidget(self._notes)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("playButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def get_tags(self) -> str:
        """Raw tags text, split and normalised by the caller."""
        return self._tags.text()

    def get_notes(self) -> str:
        return self._notes.toPlainText()
