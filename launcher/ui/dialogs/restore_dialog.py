"""Pick a save backup to restore."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.services.saves import Backup


def _human_size(size: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}"
    return f"{size} B"


class RestoreBackupDialog(QDialog):
    """Choose which backup to copy back into a game's prefix."""

    def __init__(
        self,
        game_name: str,
        backups: list[Backup],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.selected: Backup | None = None
        self.delete_requested: Backup | None = None
        self._backups = backups

        self.setWindowTitle(f"Restore saves — {game_name}")
        self.setMinimumWidth(460)
        self._setup_ui(game_name)

    def _setup_ui(self, game_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        heading = QLabel(f"Backups for {game_name}")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self._list = QListWidget()
        for backup in self._backups:
            item = QListWidgetItem(
                f"{backup.label}    {_human_size(backup.size)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, backup)
            self._list.addItem(item)
        if self._backups:
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(lambda _: self._accept())
        layout.addWidget(self._list)

        note = QLabel(
            "Restoring overwrites files the backup contains. Anything else in "
            "the prefix is left alone."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        delete_btn = QPushButton("Delete this backup")
        delete_btn.clicked.connect(self._delete)
        delete_btn.setEnabled(bool(self._backups))
        layout.addWidget(delete_btn)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        restore = buttons.addButton(
            "Restore", QDialogButtonBox.ButtonRole.AcceptRole
        )
        restore.setObjectName("playButton")
        restore.setEnabled(bool(self._backups))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _current(self) -> Backup | None:
        item = self._list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _accept(self) -> None:
        self.selected = self._current()
        if self.selected is not None:
            self.accept()

    def _delete(self) -> None:
        self.delete_requested = self._current()
        if self.delete_requested is not None:
            self.done(2)
