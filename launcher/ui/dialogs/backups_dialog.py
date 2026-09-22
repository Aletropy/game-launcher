"""Browsing save snapshots and restoring from them."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.app.save_keeper import SaveKeeper
from launcher.services.backups import BackupError, RestoreResult, Snapshot
from launcher.ui.dialogs.confirm import Answer, ask, warn
from launcher.ui.dialogs.saves_dialog import human

_FOLDER_ROLE = Qt.ItemDataRole.UserRole


def _depth(item: QTreeWidgetItem) -> int:
    depth = 0
    parent = item.parent()
    while parent is not None:
        depth += 1
        parent = parent.parent()
    return depth


def _starts_word(name: str, token: str) -> bool:
    """Whether a token begins a word in a name: "elden" is not in "Helden"."""
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}", name) is not None


def hint_tokens(text: str) -> list[str]:
    """Words from a game's name worth searching folder names for."""
    return [w for w in text.casefold().replace("-", " ").split() if len(w) >= 4]


class BackupsDialog(QDialog):
    """Snapshots on the left, what is in the selected one on the right."""

    def __init__(
        self,
        context: AppContext,
        keeper: SaveKeeper,
        parent: QWidget | None = None,
        game_hint: str = "",
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._keeper = keeper
        self._game_hint = game_hint
        self.setWindowTitle("Save Backups")
        self.setMinimumSize(820, 520)
        self._setup_ui()
        keeper.backups_changed.connect(self.refresh)
        self.refresh()

    # -- layout --------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("Save backups")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self._intro = QLabel()
        self._intro.setObjectName("hintLabel")
        self._intro.setWordWrap(True)
        layout.addWidget(self._intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Snapshots.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setSpacing(3)
        self._list.currentItemChanged.connect(lambda *_: self._on_snapshot())
        left_layout.addWidget(self._list, stretch=1)
        row = QHBoxLayout()
        self._backup_btn = QPushButton("Back up now")
        self._backup_btn.setObjectName("playButton")
        self._backup_btn.setToolTip("Manual backups are kept until you delete them")
        self._backup_btn.clicked.connect(self._backup_now)
        row.addWidget(self._backup_btn)
        self._pin_btn = QPushButton("Keep forever")
        self._pin_btn.clicked.connect(self._toggle_pin)
        row.addWidget(self._pin_btn)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        row.addWidget(self._delete_btn)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        # Contents.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Find a game's folder…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        right_layout.addWidget(self._filter)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Folder", "Files", "Size"])
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        right_layout.addWidget(self._tree, stretch=1)
        row = QHBoxLayout()
        self._restore_folder_btn = QPushButton("Restore this folder")
        self._restore_folder_btn.clicked.connect(self._restore_folder)
        row.addWidget(self._restore_folder_btn)
        self._restore_all_btn = QPushButton("Restore everything")
        self._restore_all_btn.clicked.connect(lambda: self._restore(""))
        row.addWidget(self._restore_all_btn)
        row.addStretch()
        open_btn = QPushButton("Open")
        open_btn.setToolTip("Browse this backup in the file manager")
        open_btn.clicked.connect(self._open)
        row.addWidget(open_btn)
        right_layout.addLayout(row)
        splitter.addWidget(right)
        splitter.setSizes([300, 520])
        layout.addWidget(splitter, stretch=1)

        close = QDialogButtonBox()
        close.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    # -- state ---------------------------------------------------------

    def refresh(self) -> None:
        selected = self._snapshot()
        snapshots = self._ctx.backups.snapshots()
        self._list.blockSignals(True)
        self._list.clear()
        for snapshot in snapshots:
            item = QListWidgetItem(self._describe(snapshot))
            item.setData(Qt.ItemDataRole.UserRole, snapshot)
            item.setToolTip(snapshot.reason or "")
            self._list.addItem(item)
            if selected is not None and snapshot.name == selected.name:
                self._list.setCurrentItem(item)
        if self._list.currentItem() is None and self._list.count():
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)

        settings = self._ctx.settings
        auto = (
            f"Taken automatically after playing, at most every "
            f"{settings.get_int('backup_interval_minutes')} min, and before "
            f"anything moves saves around."
            if settings.get_bool("backup_auto")
            else "Automatic backups are off."
        )
        count = len(snapshots)
        self._intro.setText(
            f"Snapshots of the shared saves. Files that did not change are "
            f"shared between snapshots, so each costs only what changed. "
            f"{auto} Caches are left out. {count} snapshot(s)."
        )
        self._on_snapshot()

    @staticmethod
    def _describe(snapshot: Snapshot) -> str:
        kept = "  ★ kept" if snapshot.pinned else ""
        reason = snapshot.reason or "backup"
        return (
            f"{snapshot.label}{kept}\n{reason}  ·  "
            f"{human(snapshot.total_bytes)}, {human(snapshot.new_bytes)} new"
        )

    def _snapshot(self) -> Snapshot | None:
        item = self._list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _folder(self) -> str | None:
        item = self._tree.currentItem()
        return None if item is None else item.data(0, _FOLDER_ROLE)

    def _on_snapshot(self) -> None:
        keep_folder = self._folder()
        self._tree.clear()
        snapshot = self._snapshot()
        if snapshot is not None:
            items: dict[str, QTreeWidgetItem] = {}
            for folder in self._ctx.backups.folders(snapshot, depth=4):
                parent_key, _, name = folder.relative.rpartition("/")
                item = QTreeWidgetItem(
                    [name, str(folder.files), human(folder.size)]
                )
                item.setData(0, _FOLDER_ROLE, folder.relative)
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
                item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
                parent = items.get(parent_key)
                if parent is None:
                    self._tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                items[folder.relative] = item
            for index in range(self._tree.topLevelItemCount()):
                top = self._tree.topLevelItem(index)
                if top is not None:
                    top.setExpanded(True)
            if self._game_hint and not self._filter.text():
                self._suggest_folder()
            else:
                self._apply_filter(self._filter.text())
                if keep_folder and keep_folder in items:
                    self._tree.setCurrentItem(items[keep_folder])
        self._update_buttons()

    def _suggest_folder(self) -> None:
        """Opened for a game: show the folders that look like its own."""
        tokens = hint_tokens(self._game_hint)
        if not tokens:
            return
        scored = []
        for item in self._all_items():
            name = item.text(0).casefold()
            hits = sum(_starts_word(name, t) for t in tokens)
            if hits:
                # Most words matched, then the deepest (the game's own
                # folder rather than a publisher folder above it).
                scored.append((hits, _depth(item), item))
        self._game_hint = ""
        if not scored:
            return
        best = max(scored, key=lambda s: (s[0], s[1]))[2]
        self._filter.setText(best.text(0))
        self._tree.setCurrentItem(best)
        self._tree.scrollToItem(best)

    def _all_items(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []

        def walk(item: QTreeWidgetItem) -> None:
            found.append(item)
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for index in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(index)
            if top is not None:
                walk(top)
        return found

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        items = self._all_items()
        if not needle:
            for item in items:
                item.setHidden(False)
            return
        for item in items:
            item.setHidden(True)
        for item in items:
            if needle in item.text(0).casefold():
                # Show the match, its ancestors, and everything inside it.
                node: QTreeWidgetItem | None = item
                while node is not None:
                    node.setHidden(False)
                    node.setExpanded(True)
                    node = node.parent()
                stack = [item]
                while stack:
                    current = stack.pop()
                    current.setHidden(False)
                    stack.extend(
                        c for i in range(current.childCount())
                        if (c := current.child(i)) is not None
                    )

    def _update_buttons(self) -> None:
        snapshot = self._snapshot()
        has = snapshot is not None
        self._pin_btn.setEnabled(has)
        self._delete_btn.setEnabled(has)
        self._restore_all_btn.setEnabled(has)
        self._restore_folder_btn.setEnabled(has and bool(self._folder()))
        self._pin_btn.setText(
            "Let expire" if snapshot is not None and snapshot.pinned else "Keep forever"
        )
        self._backup_btn.setEnabled(
            self._ctx.save_store.exists and not self._ctx.backups.busy
        )

    # -- actions -------------------------------------------------------

    def _backup_now(self) -> None:
        self._keeper.backup_in_background("manual backup", pinned=True)
        self._backup_btn.setEnabled(False)

    def _toggle_pin(self) -> None:
        snapshot = self._snapshot()
        if snapshot is None:
            return
        self._ctx.backups.set_pinned(snapshot, not snapshot.pinned)
        self.refresh()

    def _delete(self) -> None:
        snapshot = self._snapshot()
        if snapshot is None:
            return
        if ask(
            self,
            "Delete Backup",
            f"Delete the backup from {snapshot.label}?",
            default=Answer.NO,
        ) is not Answer.YES:
            return
        try:
            self._ctx.backups.delete(snapshot)
        except OSError as e:
            warn(self, "Delete Backup", str(e))
        self.refresh()

    def _restore_folder(self) -> None:
        folder = self._folder()
        if folder:
            self._restore(folder)

    def _restore(self, folder: str) -> None:
        snapshot = self._snapshot()
        if snapshot is None:
            return
        running = self._ctx.processes.running_games
        if running:
            warn(
                self,
                "Restore",
                "Close these games first, so they cannot overwrite what is "
                "restored:\n  " + "\n  ".join(running),
            )
            return
        what = f"'{folder}'" if folder else "all shared saves"
        if ask(
            self,
            "Restore",
            f"Put {what} back as it was on {snapshot.label}?\n\n"
            "Files saved since then will be replaced or removed. A backup of "
            "the saves as they are now is taken first, so this can be undone.",
            default=Answer.NO,
        ) is not Answer.YES:
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self._ctx.backups.restore(snapshot, folder)
        except BackupError as e:
            warn(self, "Restore Failed", str(e))
            return
        except OSError as e:
            warn(self, "Restore Failed", str(e))
            return
        finally:
            self.unsetCursor()
        self._keeper.backups_changed.emit()
        warn(self, "Restore", self._summary(result))

    @staticmethod
    def _summary(result: RestoreResult) -> str:
        lines = [
            f"Restored {result.restored} file(s), removed {result.removed}, "
            f"{result.unchanged} already matched."
        ]
        if result.safety is not None:
            lines.append(
                f"The saves as they were are in the backup from "
                f"{result.safety.label}."
            )
        if result.errors:
            lines.append("Problems:\n" + "\n".join(result.errors[:6]))
        return "\n\n".join(lines)

    def _open(self) -> None:
        from launcher.services.prefix_tools import open_path

        snapshot = self._snapshot()
        folder = self._folder()
        if snapshot is None:
            open_path(self._ctx.backups.root)
        elif folder:
            open_path(snapshot.data / folder)
        else:
            open_path(snapshot.data)
