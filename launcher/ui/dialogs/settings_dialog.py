"""Application preferences."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.data.settings_store import DEFAULTS
from launcher.domain import prefixes
from launcher.domain.backup_policy import DEFAULT_EXCLUDES
from launcher.services.tasks import TaskGroup

#: Prompts the user can silence, and how to describe re-enabling them.
_SILENCEABLE = {
    "skip_missing_check": "Ask before removing games whose executable is missing",
    "artwork_cleanup_prompted": "Offer the artwork cleanup again",
}


class SettingsDialog(QDialog):
    """One place for every preference."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._tasks = TaskGroup(self)
        self._tasks.finished.connect(lambda _t, r: self._show_key_result(str(r)))
        self._tasks.failed.connect(lambda _t, m: self._show_key_result(m))
        self._verify_token = -1

        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._build_general(), "General")
        tabs.addTab(self._build_saves(), "Saves")
        tabs.addTab(self._build_artwork(), "Artwork")
        tabs.addTab(self._build_prompts(), "Prompts")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("playButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(12, 16, 12, 12)
        form.setSpacing(10)

        self._confirm_remove = QCheckBox("Confirm before removing a game")
        form.addRow(self._confirm_remove)

        self._log_lines = QSpinBox()
        self._log_lines.setRange(500, 100_000)
        self._log_lines.setSingleStep(500)
        self._log_lines.setToolTip(
            "Older output is discarded once a game's log reaches this many lines."
        )
        form.addRow("Log limit (lines)", self._log_lines)

        shared = prefixes.shared_prefix_path(self._ctx.paths)
        prefix_label = QLabel(str(shared))
        prefix_label.setObjectName("hintLabel")
        prefix_label.setWordWrap(True)
        form.addRow("Shared prefix", prefix_label)

        note = QLabel(
            "Games use the shared prefix unless they name their own in "
            "Edit → Wine Prefix."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _build_saves(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(12, 16, 12, 12)
        form.setSpacing(10)

        self._share_default = QCheckBox("Share every prefix's saves automatically")
        self._share_default.setToolTip(
            "New and existing prefixes join the shared Saves folder before "
            "and after a game runs."
        )
        form.addRow(self._share_default)

        self._backup_auto = QCheckBox("Back up saves after playing")
        form.addRow(self._backup_auto)
        self._backup_interval = QSpinBox()
        self._backup_interval.setRange(0, 24 * 60)
        self._backup_interval.setSingleStep(15)
        self._backup_interval.setSuffix(" min")
        self._backup_interval.setToolTip("0 backs up after every session")
        form.addRow("At most every", self._backup_interval)

        keep = QHBoxLayout()
        self._keep_recent = QSpinBox()
        self._keep_recent.setRange(1, 100)
        self._keep_recent.setSuffix(" latest")
        self._keep_daily = QSpinBox()
        self._keep_daily.setRange(0, 60)
        self._keep_daily.setSuffix(" days")
        self._keep_weekly = QSpinBox()
        self._keep_weekly.setRange(0, 52)
        self._keep_weekly.setSuffix(" weeks")
        for box in (self._keep_recent, self._keep_daily, self._keep_weekly):
            keep.addWidget(box)
        form.addRow("Keep", keep)
        keep_hint = QLabel(
            "Keeps the latest backups, then one per day and one per week "
            "for as long as set. Manual backups are kept until deleted."
        )
        keep_hint.setObjectName("hintLabel")
        keep_hint.setWordWrap(True)
        form.addRow(keep_hint)

        self._exclude = QPlainTextEdit()
        self._exclude.setPlaceholderText(
            "One folder per line, e.g.\nDocuments/Euro Truck Simulator 2/mod"
        )
        self._exclude.setFixedHeight(84)
        self._exclude.setToolTip(
            "Always left out: " + ", ".join(DEFAULT_EXCLUDES)
        )
        form.addRow("Also leave out", self._exclude)
        return page

    def _build_artwork(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(12, 16, 12, 12)
        form.setSpacing(10)

        key_row = QHBoxLayout()
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("SteamGridDB API key")
        key_row.addWidget(self._api_key)
        self._verify_btn = QPushButton("Test")
        self._verify_btn.setFixedWidth(70)
        self._verify_btn.clicked.connect(self._verify_key)
        key_row.addWidget(self._verify_btn)
        form.addRow("API key", key_row)

        self._key_status = QLabel("")
        self._key_status.setObjectName("hintLabel")
        self._key_status.setWordWrap(True)
        form.addRow(self._key_status)

        hint = QLabel(
            "Get a key at steamgriddb.com/profile/preferences. Artwork is "
            "stored at display size, so the library stays small."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)

        self._fetch_on_add = QCheckBox("Offer to fetch artwork when adding a game")
        form.addRow(self._fetch_on_add)
        return page

    def _build_prompts(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Prompts you silenced with “Don't ask again”. Tick one to "
            "start being asked again."
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._prompt_boxes: dict[str, QCheckBox] = {}
        for key, label in _SILENCEABLE.items():
            box = QCheckBox(label)
            layout.addWidget(box)
            self._prompt_boxes[key] = box

        layout.addStretch()
        return page

    # -- values --------------------------------------------------------

    def _load(self) -> None:
        settings = self._ctx.settings
        self._confirm_remove.setChecked(settings.get_bool("confirm_remove"))
        self._log_lines.setValue(settings.get_int("log_max_lines"))
        self._api_key.setText(settings.get_str("sgdb_api_key"))
        self._fetch_on_add.setChecked(settings.get_bool("fetch_artwork_on_add"))
        self._share_default.setChecked(settings.get_bool("share_saves_by_default"))
        self._backup_auto.setChecked(settings.get_bool("backup_auto"))
        self._backup_interval.setValue(settings.get_int("backup_interval_minutes"))
        self._keep_recent.setValue(settings.get_int("backup_keep_recent"))
        self._keep_daily.setValue(settings.get_int("backup_keep_daily"))
        self._keep_weekly.setValue(settings.get_int("backup_keep_weekly"))
        self._exclude.setPlainText(settings.get_str("backup_exclude"))
        # These flags mean "silenced", so the checkbox is the inverse.
        for key, box in self._prompt_boxes.items():
            box.setChecked(not settings.get_bool(key))

    def _save(self) -> None:
        values = {
            "confirm_remove": self._confirm_remove.isChecked(),
            "log_max_lines": self._log_lines.value(),
            "sgdb_api_key": self._api_key.text().strip(),
            "fetch_artwork_on_add": self._fetch_on_add.isChecked(),
            "share_saves_by_default": self._share_default.isChecked(),
            "backup_auto": self._backup_auto.isChecked(),
            "backup_interval_minutes": self._backup_interval.value(),
            "backup_keep_recent": self._keep_recent.value(),
            "backup_keep_daily": self._keep_daily.value(),
            "backup_keep_weekly": self._keep_weekly.value(),
            "backup_exclude": self._exclude.toPlainText().strip(),
        }
        for key, box in self._prompt_boxes.items():
            values[key] = not box.isChecked()
        self._ctx.settings.update(values)
        self.accept()

    # -- API key check -------------------------------------------------

    def _verify_key(self) -> None:
        key = self._api_key.text().strip()
        if not key:
            self._key_status.setText("Enter a key first.")
            return
        self._verify_btn.setEnabled(False)
        self._key_status.setText("Checking…")
        self._verify_token = self._tasks.submit(self._ctx.sgdb.verify_key, key)

    def _show_key_result(self, message: str) -> None:
        self._verify_btn.setEnabled(True)
        self._key_status.setText(message)

    def reject(self) -> None:
        self._tasks.cancel_all()
        super().reject()


def default_for(key: str) -> object:
    """The shipped default for a preference."""
    return DEFAULTS.get(key)
