"""Take saves to another machine and back.

Export writes the shared store (or chosen folders) to a zip archive with
a manifest; import previews an archive, takes a safety snapshot, and
merges it with newer-wins rules, quarantining every loser. Both run
through file dialogs and report what they did in plain sentences.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.services import save_exchange
from launcher.ui.dialogs.confirm import warn
from launcher.ui.dialogs.saves_dialog import human


class SaveExchangeDialog(QDialog):
    """Export saves to a zip, or import one. One mode per instance."""

    def __init__(
        self,
        context: AppContext,
        *,
        mode: str = "export",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._mode = mode
        self.setWindowTitle("Export saves" if mode == "export" else "Import saves")
        self.resize(560, 480)
        self._setup_ui()

    # -- layout ----------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(10)
        if self._mode == "export":
            self._build_export(outer)
        else:
            self._build_import(outer)

    def _build_export(self, outer: QVBoxLayout) -> None:
        outer.addWidget(QLabel("Folders to export:"))
        self._folders = QListWidget()
        for folder in save_exchange.top_folders(self._ctx.save_store):
            item = QListWidgetItem(folder)
            item.setCheckState(Qt.CheckState.Checked)
            self._folders.addItem(item)
        if self._folders.count() == 0:
            outer.addWidget(QLabel("Nothing is shared yet — no saves to export."))
        outer.addWidget(self._folders, stretch=1)

        row = QHBoxLayout()
        self._dest = QLineEdit()
        self._dest.setPlaceholderText("Choose where to save the zip…")
        row.addWidget(self._dest, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_dest)
        row.addWidget(browse)
        outer.addLayout(row)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        export = buttons.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        export.setObjectName("playButton")
        buttons.accepted.connect(self._do_export)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _build_import(self, outer: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self._source = QLineEdit()
        self._source.setPlaceholderText("Choose a saves zip…")
        self._source.textChanged.connect(lambda _t: self._preview())
        row.addWidget(self._source, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_source)
        row.addWidget(browse)
        outer.addLayout(row)

        self._preview_label = QLabel("No archive chosen.")
        self._preview_label.setWordWrap(True)
        self._preview_label.setObjectName("hintLabel")
        outer.addWidget(self._preview_label)
        outer.addStretch()

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self._import_btn = buttons.addButton("Import", QDialogButtonBox.ButtonRole.AcceptRole)
        self._import_btn.setObjectName("playButton")
        self._import_btn.setEnabled(False)
        buttons.accepted.connect(self._do_import)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # -- export ----------------------------------------------------------

    def _picked_folders(self) -> list[str] | None:
        chosen = [
            self._folders.item(i).text()
            for i in range(self._folders.count())
            if self._folders.item(i).checkState() == Qt.CheckState.Checked
        ]
        if chosen and len(chosen) == self._folders.count():
            return None
        return chosen

    def _pick_dest(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export saves", "milso-saves.zip", "Zip archives (*.zip)"
        )
        if path:
            self._dest.setText(path)

    def _do_export(self) -> None:
        dest = Path(self._dest.text().strip())
        if not dest.name:
            warn(self, "Export saves", "Choose where to save the zip first.")
            return
        if dest.suffix != ".zip":
            dest = dest.with_suffix(".zip")
        try:
            summary = save_exchange.export_zip(
                self._ctx.save_store, self._picked_folders(), dest
            )
        except OSError as e:
            warn(self, "Export saves", f"Could not write the archive:\n{e}")
            return
        if summary.files == 0:
            warn(self, "Export saves", "There were no saves to export.")
            return
        warn(
            self,
            "Export saves",
            f"Exported {summary.files} file(s), {human(summary.total_bytes)},\nto {summary.dest}.",
        )
        self.accept()

    # -- import ----------------------------------------------------------

    def _pick_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import saves", "", "Zip archives (*.zip)"
        )
        if path:
            self._source.setText(path)

    def _preview(self) -> None:
        raw = self._source.text().strip()
        if not raw:
            self._preview_label.setText("No archive chosen.")
            self._import_btn.setEnabled(False)
            return
        try:
            preview = save_exchange.preview_import(Path(raw))
        except (ValueError, OSError) as e:
            self._preview_label.setText(str(e))
            self._import_btn.setEnabled(False)
            return
        folders = ", ".join(preview.folders[:8])
        if len(preview.folders) > 8:
            folders += f", and {len(preview.folders) - 8} more"
        self._preview_label.setText(
            f"{preview.files} file(s), {human(preview.total_bytes)}.\nFolders: {folders}."
        )
        self._import_btn.setEnabled(preview.files > 0)

    def _do_import(self) -> None:
        try:
            result = save_exchange.import_zip(
                self._ctx.save_store, self._ctx.backups, Path(self._source.text().strip())
            )
        except (ValueError, OSError) as e:
            warn(self, "Import saves", str(e))
            return
        parts = [
            f"Brought in {result.moved} file(s), {result.identical} already matched."
        ]
        if result.conflicts:
            parts.append(
                f"{result.conflicts} conflict(s): the newer copy won, "
                "the other is in Saves/.conflicts/."
            )
        if result.safety is not None:
            parts.append(f"A backup from {result.safety.label} was taken first.")
        if result.errors:
            parts.append("Problems:\n" + "\n".join(result.errors[:6]))
        warn(self, "Import saves", "\n\n".join(parts))
        self.accept()
