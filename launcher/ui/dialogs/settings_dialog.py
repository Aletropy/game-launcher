"""Application preferences, grouped into pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.data.settings_store import DEFAULTS
from launcher.domain import prefixes
from launcher.domain.backup_policy import DEFAULT_EXCLUDES
from launcher.domain.journal import format_duration
from launcher.services.tasks import TaskGroup
from launcher.ui.theme import Appearance, apply_theme
from launcher.ui.widgets.appearance_picker import AppearancePanel

#: Prompts the user can silence, and how to describe re-enabling them.
_SILENCEABLE = {
    "skip_missing_check": "Ask before removing games whose executable is missing",
    "artwork_cleanup_prompted": "Offer the artwork cleanup again",
}

#: Page id, title, one-line description.
_PAGES = (
    ("appearance", "Appearance", "Themes, colours, layout and text."),
    ("library", "Library", "How games are listed, removed and run."),
    ("artwork", "Artwork", "Where artwork comes from and what it costs on disk."),
    ("saves", "Saves & backups", "One set of saves for every prefix, kept safe."),
    ("data", "Data", "What the launcher has recorded, and clearing it."),
    ("prompts", "Prompts", "Questions you asked not to be asked again."),
    ("about", "About", "Version and where everything lives."),
)


def _human(num_bytes: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if num_bytes >= scale:
            return f"{num_bytes / scale:.1f} {unit}"
    return f"{num_bytes} B"


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hintLabel")
    label.setWordWrap(True)
    return label


class _Card(QFrame):
    """A titled group of related settings."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        outer.addWidget(heading)
        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(self.form)


class SettingsDialog(QDialog):
    """One place for every preference, a page per subject."""

    #: Actions that open other windows; the main window owns those.
    clear_data_requested = Signal()
    cleanup_requested = Signal()
    shared_saves_requested = Signal()
    backups_requested = Signal()

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        page: str = "appearance",
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._tasks = TaskGroup(self)
        self._tasks.finished.connect(lambda _t, r: self._show_key_result(str(r)))
        self._tasks.failed.connect(lambda _t, m: self._show_key_result(m))
        self._verify_token = -1
        #: Put back on Cancel; changes preview live while the dialog is open.
        self._original_look = Appearance.from_settings(context.settings)

        self.setWindowTitle("Settings")
        self.resize(940, 640)
        self.setMinimumSize(820, 520)
        self._setup_ui()
        self._load()
        self.show_page(page)

    # -- layout --------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 12)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        self._nav.setFixedWidth(196)
        body.addWidget(self._nav)

        self._stack = QStackedWidget()
        builders = {
            "appearance": self._build_appearance,
            "library": self._build_library,
            "artwork": self._build_artwork,
            "saves": self._build_saves,
            "data": self._build_data,
            "prompts": self._build_prompts,
            "about": self._build_about,
        }
        self._page_ids: list[str] = []
        for page_id, title, description in _PAGES:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, page_id)
            # Stylesheet padding does not size list rows; the hint does.
            item.setSizeHint(QSize(0, 38))
            self._nav.addItem(item)
            self._stack.addWidget(self._page(title, description, builders[page_id]()))
            self._page_ids.append(page_id)
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        body.addWidget(self._stack, stretch=1)
        outer.addLayout(body, stretch=1)

        buttons = QDialogButtonBox()
        buttons.setContentsMargins(0, 12, 16, 0)
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("playButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    @staticmethod
    def _page(heading: str, description: str, content: QWidget) -> QScrollArea:
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 16)
        layout.setSpacing(14)
        title = QLabel(heading)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(_hint(description))
        layout.addWidget(content)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _column(*cards: QWidget) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for card in cards:
            layout.addWidget(card)
        return column

    @staticmethod
    def _button_row(*widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch()
        return row

    def show_page(self, page_id: str) -> None:
        if page_id in self._page_ids:
            self._nav.setCurrentRow(self._page_ids.index(page_id))

    # -- pages ---------------------------------------------------------

    def _build_appearance(self) -> QWidget:
        self._appearance = AppearancePanel(self._original_look)
        self._appearance.changed.connect(self._preview_look)
        return self._appearance

    def _build_library(self) -> QWidget:
        behaviour = _Card("Behaviour")
        self._confirm_remove = QCheckBox("Confirm before removing a game")
        behaviour.form.addRow(self._confirm_remove)
        self._log_lines = QSpinBox()
        self._log_lines.setRange(500, 100_000)
        self._log_lines.setSingleStep(500)
        self._log_lines.setSuffix(" lines")
        behaviour.form.addRow("Keep game logs up to", self._log_lines)

        wine = _Card("Wine")
        shared = prefixes.shared_prefix_path(self._ctx.paths)
        path = QLabel(str(shared))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        wine.form.addRow("Shared prefix", path)
        wine.form.addRow(
            _hint("Games use it unless they have their own, set in Edit → Compatibility.")
        )
        return self._column(behaviour, wine)

    def _build_artwork(self) -> QWidget:
        source = _Card("SteamGridDB")
        key_row = QHBoxLayout()
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("API key")
        key_row.addWidget(self._api_key, stretch=1)
        self._verify_btn = QPushButton("Test")
        self._verify_btn.clicked.connect(self._verify_key)
        key_row.addWidget(self._verify_btn)
        source.form.addRow("API key", key_row)
        self._key_status = _hint("")
        source.form.addRow(self._key_status)
        source.form.addRow(_hint("Get a key at steamgriddb.com/profile/preferences."))
        self._fetch_on_add = QCheckBox("Offer to choose artwork when adding a game")
        source.form.addRow(self._fetch_on_add)

        storage = _Card("Storage")
        files = [p for p in self._ctx.paths.artwork_dir.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        storage.form.addRow(
            QLabel(f"{len(files)} image(s), {_human(size)}, stored at display size.")
        )
        cleanup = QPushButton("Clean up artwork…")
        cleanup.setToolTip("Re-encode, remove duplicates and images of removed games")
        cleanup.clicked.connect(self.cleanup_requested)
        storage.form.addRow(self._button_row(cleanup))
        return self._column(source, storage)

    def _build_saves(self) -> QWidget:
        sharing = _Card("Shared saves")
        self._share_default = QCheckBox("Share every prefix's saves automatically")
        self._share_default.setToolTip(
            "Prefixes join the shared Saves folder on startup and around each game."
        )
        sharing.form.addRow(self._share_default)
        store = self._ctx.save_store
        sharing.form.addRow(
            _hint(
                f"{store.root.name}/ holds {_human(store.size())}."
                if store.exists
                else "Nothing is shared yet."
            )
        )
        manage = QPushButton("Shared saves…")
        manage.clicked.connect(self.shared_saves_requested)
        sharing.form.addRow(self._button_row(manage))

        backups = _Card("Automatic backups")
        self._backup_auto = QCheckBox("Back up saves after playing")
        backups.form.addRow(self._backup_auto)
        self._backup_interval = QSpinBox()
        self._backup_interval.setRange(0, 24 * 60)
        self._backup_interval.setSingleStep(15)
        self._backup_interval.setSuffix(" min")
        self._backup_interval.setToolTip("0 backs up after every session")
        backups.form.addRow("At most every", self._backup_interval)
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
        backups.form.addRow("Keep", keep)
        backups.form.addRow(
            _hint(
                "The latest backups, then one a day and one a week for as long "
                "as set. Manual backups are kept until deleted."
            )
        )
        count = len(self._ctx.backups.snapshots())
        browse = QPushButton("Backups…")
        browse.clicked.connect(self.backups_requested)
        backups.form.addRow(self._button_row(browse, _hint(f"{count} backup(s) now.")))

        exclude = _Card("Leave out of backups")
        self._exclude = QPlainTextEdit()
        self._exclude.setObjectName("input")
        self._exclude.setPlaceholderText(
            "One folder per line, e.g.\nDocuments/Euro Truck Simulator 2/mod"
        )
        self._exclude.setFixedHeight(90)
        exclude.form.addRow(self._exclude)
        exclude.form.addRow(
            _hint("Caches are always left out, e.g. " + ", ".join(DEFAULT_EXCLUDES[:4]) + ".")
        )
        return self._column(sharing, backups, exclude)

    def _build_data(self) -> QWidget:
        recorded = _Card("Recorded")
        state = self._ctx.state
        recorded.form.addRow("Play sessions", QLabel(str(state.session_count())))
        recorded.form.addRow("Playtime", QLabel(format_duration(state.total_playtime())))
        recorded.form.addRow(
            _hint(
                "Clear play history, playtime, launch counts, favourites or "
                "artwork, for one game or all of them. A copy of the database "
                "is saved first."
            )
        )
        button = QPushButton("Clear data…")
        button.setObjectName("dangerButton")
        button.clicked.connect(self.clear_data_requested)
        recorded.form.addRow(self._button_row(button))
        return self._column(recorded)

    def _build_prompts(self) -> QWidget:
        card = _Card("Ask me again")
        card.form.addRow(_hint("Tick a prompt to start being asked again."))
        self._prompt_boxes: dict[str, QCheckBox] = {}
        for key, label in _SILENCEABLE.items():
            box = QCheckBox(label)
            card.form.addRow(box)
            self._prompt_boxes[key] = box
        return self._column(card)

    def _build_about(self) -> QWidget:
        about = _Card("Game Launcher")
        about.form.addRow("Version", QLabel(_version()))
        paths = self._ctx.paths
        places = _Card("Where things live")
        for label, path in (
            ("Games", paths.games_dir),
            ("Shared saves", paths.saves_dir),
            ("Backups", paths.backups_dir),
            ("Artwork", paths.artwork_dir),
            ("Preferences", paths.config),
            ("Play history", paths.data),
        ):
            row = QHBoxLayout()
            text = QLabel(str(path))
            text.setObjectName("hintLabel")
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(text, stretch=1)
            button = QPushButton("Open")
            button.setEnabled(path.exists())
            button.clicked.connect(lambda _=False, p=path: _open(p))
            row.addWidget(button)
            places.form.addRow(label, row)
        return self._column(about, places)

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
        values.update(self._appearance.appearance.to_settings())
        self._ctx.settings.update(values)
        self.accept()

    def _preview_look(self, look: Appearance) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, look)

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
        if self._appearance.appearance != self._original_look:
            self._preview_look(self._original_look)
        super().reject()


def _open(path: Path) -> None:
    from launcher.services.prefix_tools import open_path

    open_path(path)


def _version() -> str:
    """The installed package's version, or pyproject's when run from source."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("game-launcher")
    except PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def default_for(key: str) -> object:
    """The shipped default for a preference."""
    return DEFAULTS.get(key)
