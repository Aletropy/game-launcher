"""Managing the shared save store."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.services.save_store import AdoptPlan, AdoptResult, SaveStore
from launcher.ui.dialogs.confirm import Answer, ask, warn


def human(num_bytes: int) -> str:
    """Format a byte count for display."""
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if num_bytes >= scale:
            return f"{num_bytes / scale:.1f} {unit}"
    return f"{num_bytes} B"


class AdoptPreviewDialog(QDialog):
    """Exactly what adopting a prefix will move, before anything moves."""

    def __init__(self, plan: AdoptPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle(f"Share saves — {plan.prefix.name}")
        self.setMinimumWidth(560)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel(f"Share {self.plan.prefix.name}'s saves")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Its save folders move into the shared store and are replaced "
            "by links. Nothing is deleted: where the same file exists on "
            "both sides the newer one wins and the other is kept in "
            "Saves/.conflicts."
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Folder", "What happens"])
        tree.setRootIsDecorated(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for path_plan in self.plan.paths:
            item = QTreeWidgetItem([path_plan.label, path_plan.action])
            if path_plan.skipped_reason:
                item.setToolTip(1, path_plan.skipped_reason)
            tree.addTopLevelItem(item)
        layout.addWidget(tree)

        summary = QLabel(
            f"{self.plan.total_moves} file(s) to move ({human(self.plan.total_bytes)}), "
            f"{self.plan.total_conflicts} conflict(s)."
        )
        summary.setObjectName("sectionTitle")
        layout.addWidget(summary)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        run = buttons.addButton("Share saves", QDialogButtonBox.ButtonRole.AcceptRole)
        run.setObjectName("playButton")
        run.setEnabled(self.plan.can_run)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SavesDialog(QDialog):
    """Status of every prefix, and the actions that change it."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._store: SaveStore = context.save_store
        self.setWindowTitle("Shared Saves")
        self.setMinimumSize(640, 460)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("Shared saves")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self._intro = QLabel()
        self._intro.setObjectName("hintLabel")
        self._intro.setWordWrap(True)
        layout.addWidget(self._intro)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Prefix", "Saves"])
        self._tree.setRootIsDecorated(False)
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self._tree, stretch=1)

        actions = QHBoxLayout()
        self._share_btn = QPushButton("Share saves…")
        self._share_btn.setObjectName("playButton")
        self._share_btn.clicked.connect(self._share)
        actions.addWidget(self._share_btn)

        self._repair_btn = QPushButton("Repair links")
        self._repair_btn.clicked.connect(self._repair)
        actions.addWidget(self._repair_btn)

        self._release_btn = QPushButton("Stop sharing")
        self._release_btn.clicked.connect(self._release)
        actions.addWidget(self._release_btn)

        actions.addStretch()
        open_btn = QPushButton("Open Saves folder")
        open_btn.clicked.connect(self._open_store)
        actions.addWidget(open_btn)
        layout.addLayout(actions)

        close = QDialogButtonBox()
        close.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    # -- state ---------------------------------------------------------

    def refresh(self) -> None:
        selected = self._selected_prefix()
        self._tree.clear()
        for prefix in self._store.known_prefixes():
            status = self._store.status(prefix)
            item = QTreeWidgetItem([prefix.name, status.summary])
            item.setData(0, Qt.ItemDataRole.UserRole, prefix)
            if not status.exists:
                item.setToolTip(1, "The prefix is created on first launch.")
            else:
                item.setToolTip(
                    1,
                    "\n".join(f"{p.label}: {p.describe}" for p in status.paths),
                )
            self._tree.addTopLevelItem(item)
            if selected is not None and prefix == selected:
                self._tree.setCurrentItem(item)

        if self._tree.currentItem() is None and self._tree.topLevelItemCount():
            first = self._tree.topLevelItem(0)
            if first is not None:
                self._tree.setCurrentItem(first)

        size = human(self._store.size()) if self._store.exists else "nothing yet"
        self._intro.setText(
            f"One set of save folders in {self._store.root.name}/, linked into "
            f"every prefix, so a prefix can be rebuilt without losing saves. "
            f"Currently holding {size}."
        )
        self._update_buttons()

    def _selected_prefix(self) -> Path | None:
        item = self._tree.currentItem()
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def _update_buttons(self) -> None:
        prefix = self._selected_prefix()
        if prefix is None:
            for button in (self._share_btn, self._repair_btn, self._release_btn):
                button.setEnabled(False)
            return
        status = self._store.status(prefix)
        self._share_btn.setEnabled(status.exists and not status.fully_linked)
        self._repair_btn.setEnabled(
            status.exists and not status.unlinked and bool(status.needs_adoption)
        )
        self._release_btn.setEnabled(status.exists and not status.unlinked)

    # -- actions -------------------------------------------------------

    def _share(self) -> None:
        prefix = self._selected_prefix()
        if prefix is None:
            return
        plan = self._store.plan_adopt(prefix)
        if plan.blocked_reason:
            warn(self, "Share Saves", plan.blocked_reason)
            return
        if not plan.can_run:
            warn(self, "Share Saves", "There is nothing left to share here.")
            return

        preview = AdoptPreviewDialog(plan, self)
        if not preview.exec():
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self._store.adopt(prefix)
        finally:
            self.unsetCursor()
        self._report(prefix, result)
        self.refresh()

    def _repair(self) -> None:
        prefix = self._selected_prefix()
        if prefix is None:
            return
        result = self._store.repair(prefix)
        if result.errors:
            warn(self, "Repair Links", "\n".join(result.errors[:8]))
        else:
            warn(
                self,
                "Repair Links",
                f"Restored {len(result.repaired)} link(s), keeping "
                f"{result.recovered_files} new file(s).",
            )
        self.refresh()

    def _release(self) -> None:
        prefix = self._selected_prefix()
        if prefix is None:
            return
        if ask(
            self,
            "Stop Sharing",
            f"Give {prefix.name} its own copy of the saves again?\n\n"
            "The shared store keeps its data; this prefix gets a full "
            "copy, so it will use more disk.",
            default=Answer.NO,
        ) is not Answer.YES:
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self._store.release(prefix)
        finally:
            self.unsetCursor()
        if result.errors:
            warn(self, "Stop Sharing", "\n".join(result.errors[:8]))
        self.refresh()

    def _open_store(self) -> None:
        from launcher.services.prefix_tools import open_path

        self._store.ensure()
        open_path(self._store.root)

    def _report(self, prefix: Path, result: AdoptResult) -> None:
        if result.errors:
            warn(
                self,
                "Share Saves",
                f"{prefix.name} was only partly shared:\n"
                + "\n".join(result.errors[:8]),
            )
            return
        lines = [
            f"{prefix.name} now shares its saves.",
            f"{result.moved_files} file(s) moved into the store.",
        ]
        if result.conflict_count:
            lines.append(
                f"{result.conflict_count} conflict(s): the newer copy won, "
                f"the other is in {self._store.conflicts_root.name}/."
            )
        if result.skipped:
            lines.append(
                "Skipped: "
                + ", ".join(f"{label} ({why})" for label, why in result.skipped)
            )
        warn(self, "Share Saves", "\n".join(lines))
