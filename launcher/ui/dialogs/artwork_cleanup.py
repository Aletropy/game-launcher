"""Artwork cleanup: show what would change, then do only what was agreed."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.services.artwork import ArtworkCleaner, CleanupReport, CleanupResult


def human(num_bytes: int) -> str:
    """Format a byte count for display."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if num_bytes >= scale:
            return f"{num_bytes / scale:.1f} {unit}"
    return f"{num_bytes} B"


class ArtworkCleanupDialog(QDialog):
    """Summarise a scan and apply the actions the user keeps ticked."""

    def __init__(
        self,
        cleaner: ArtworkCleaner,
        report: CleanupReport,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cleaner = cleaner
        self.report = report
        self.result_summary: CleanupResult | None = None

        self.setWindowTitle("Clean Up Artwork")
        self.setMinimumWidth(460)
        self._setup_ui()
        self._update_estimate()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("Artwork cleanup")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        current = QLabel(
            f"{len(self.report.files)} images currently use "
            f"{human(self.report.total_bytes)}."
        )
        layout.addWidget(current)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        layout.addWidget(line)

        self._reencode = self._action(
            layout,
            "Resize to display size",
            len(self.report.shrinkable),
            self.report.shrink_bytes,
            "Artwork is stored at the size it is shown at. Originals are "
            "replaced and cannot be restored.",
        )
        self._dedupe = self._action(
            layout,
            "Remove duplicate files",
            len(self.report.duplicates),
            self.report.duplicate_bytes,
            "The same game stored more than once under different file types.",
        )
        self._orphans = self._action(
            layout,
            "Delete artwork with no game",
            len(self.report.orphans),
            self.report.orphan_bytes,
            "Images left behind by games that are no longer in the library.",
        )

        if self.report.legacy:
            note = QLabel(
                f"{len(self.report.legacy)} image(s) will also move into the "
                "new artwork folder."
            )
            note.setObjectName("hintLabel")
            note.setWordWrap(True)
            layout.addWidget(note)

        self._estimate = QLabel()
        self._estimate.setObjectName("sectionTitle")
        layout.addWidget(self._estimate)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self._clean_btn = buttons.addButton(
            "Clean Up", QDialogButtonBox.ButtonRole.AcceptRole
        )
        assert isinstance(self._clean_btn, QPushButton)
        self._clean_btn.setObjectName("playButton")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _action(
        self,
        layout: QVBoxLayout,
        title: str,
        count: int,
        saving: int,
        explanation: str,
    ) -> QCheckBox:
        """Add one tickable action, disabled when it has nothing to do."""
        box = QCheckBox(f"{title}  —  {count} file(s), {human(saving)}")
        box.setChecked(count > 0)
        box.setEnabled(count > 0)
        box.toggled.connect(self._update_estimate)
        layout.addWidget(box)

        hint = QLabel(explanation)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        hint.setContentsMargins(24, 0, 0, 4)
        layout.addWidget(hint)
        return box

    def _any_action_selected(self) -> bool:
        return (
            self._reencode.isChecked()
            or self._dedupe.isChecked()
            or self._orphans.isChecked()
        )

    def _update_estimate(self) -> None:
        freed = self.report.reclaimable(
            reencode=self._reencode.isChecked(),
            dedupe=self._dedupe.isChecked(),
            orphans=self._orphans.isChecked(),
        )
        remaining = max(0, self.report.total_bytes - freed)
        self._estimate.setText(
            f"After cleanup: {human(remaining)}  (frees {human(freed)})"
        )
        self._clean_btn.setEnabled(freed > 0 or bool(self.report.legacy))

    def _apply(self) -> None:
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self.result_summary = self._cleaner.apply(
                self.report,
                reencode=self._reencode.isChecked(),
                dedupe=self._dedupe.isChecked(),
                delete_orphans=self._orphans.isChecked(),
                migrate=self._any_action_selected(),
            )
        finally:
            self.unsetCursor()
        self.accept()
