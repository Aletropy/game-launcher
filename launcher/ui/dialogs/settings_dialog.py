"""Application preferences, grouped into pages."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
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
from launcher.services.friends import SERVER_ENV
from launcher.services.friends_client import FriendsClient
from launcher.services.tasks import TaskGroup
from launcher.services.updates import UpdateInfo
from launcher.ui.dialogs.confirm import Answer, ask
from launcher.ui.theme import Appearance, apply_theme
from launcher.ui.theme.custom import CustomThemeStore
from launcher.ui.widgets.appearance_picker import AppearancePanel
from launcher.ui.widgets.forms import Card, button_row
from launcher.ui.widgets.forms import hint as _hint

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
    ("friends", "Friends", "Share play time with friends, or stay offline."),
    ("discord", "Discord", "Show what you're playing in Discord."),
    ("prompts", "Prompts", "Questions you asked not to be asked again."),
    ("about", "About", "Version and where everything lives."),
)


def _human(num_bytes: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if num_bytes >= scale:
            return f"{num_bytes / scale:.1f} {unit}"
    return f"{num_bytes} B"


# _Card and _hint used to live here; they are shared dialog pieces now.
_Card = Card
_button_row = button_row


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
        self._friends_tasks = TaskGroup(self)
        self._friends_tasks.finished.connect(lambda _t, r: self._show_server_result(str(r)))
        self._friends_tasks.failed.connect(lambda _t, m: self._show_server_result(m))
        self._update_tasks = TaskGroup(self)
        self._update_tasks.finished.connect(self._show_update_result)
        self._update_tasks.failed.connect(self._show_update_result)
        #: A newer release found by the last check, if any.
        self._pending_update: UpdateInfo | None = None
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
            "friends": self._build_friends,
            "discord": self._build_discord,
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

    def show_page(self, page_id: str) -> None:
        if page_id in self._page_ids:
            self._nav.setCurrentRow(self._page_ids.index(page_id))

    # -- pages ---------------------------------------------------------

    def _build_appearance(self) -> QWidget:
        self._appearance = AppearancePanel(
            self._original_look, CustomThemeStore(self._ctx.paths.themes_dir)
        )
        self._appearance.changed.connect(self._preview_look)
        return self._appearance

    def _build_library(self) -> QWidget:
        behaviour = _Card("Behaviour")
        self._confirm_remove = QCheckBox("Confirm before removing a game")
        behaviour.form.addRow(self._confirm_remove)
        self._close_to_tray = QCheckBox("Keep running in the tray when closed")
        self._close_to_tray.setToolTip(
            "Closing the window hides it. Games keep running and playtime keeps counting."
        )
        behaviour.form.addRow(self._close_to_tray)
        self._tray_hint = _hint(
            "Games keep running and playtime is recorded even with the window closed."
        )
        behaviour.form.addRow(self._tray_hint)
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        except (ImportError, AttributeError, RuntimeError):
            tray_available = False
        if not tray_available:
            self._close_to_tray.setEnabled(False)
            self._tray_hint.setText("System tray is not available on this desktop.")
        self._log_lines = QSpinBox()
        self._log_lines.setRange(500, 100_000)
        self._log_lines.setSingleStep(500)
        self._log_lines.setSuffix(" lines")
        behaviour.form.addRow("Keep game logs up to", self._log_lines)

        wine = _Card("Wine")
        from launcher import platform as _platform

        if _platform.is_windows():
            wine.form.addRow(
                _hint("Wine prefixes are Linux-only; Windows runs games natively.")
            )
        else:
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
        storage.form.addRow(_button_row(cleanup))
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
        sharing.form.addRow(_button_row(manage))

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
        backups.form.addRow(_button_row(browse, _hint(f"{count} backup(s) now.")))

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
        recorded.form.addRow(_button_row(button))
        return self._column(recorded)

    def _build_friends(self) -> QWidget:
        mode = _Card("Mode")
        self._offline_radio = QRadioButton("Offline Mode")
        self._online_radio = QRadioButton("Online: share play time with friends")
        mode.form.addRow(self._offline_radio)
        mode.form.addRow(
            _hint("Nothing is sent or fetched. The Friends tab explains the feature and waits.")
        )
        mode.form.addRow(self._online_radio)
        mode.form.addRow(
            _hint(
                "Friends you accept see your display name, which games you play and "
                "for how long, and what you're playing now. No chat, no messages."
            )
        )
        self._share_presence = QCheckBox("Show friends what I'm playing right now")
        mode.form.addRow(self._share_presence)

        server = _Card("Server")
        server_row = QHBoxLayout()
        self._server_url = QLineEdit()
        self._server_url.setPlaceholderText(str(DEFAULTS["friends_server_url"]))
        server_row.addWidget(self._server_url, stretch=1)
        self._server_test = QPushButton("Test")
        self._server_test.clicked.connect(self._test_server)
        server_row.addWidget(self._server_test)
        server.form.addRow("Address", server_row)
        self._server_status = _hint("")
        self._server_status.hide()
        server.form.addRow(self._server_status)
        override = os.environ.get(SERVER_ENV, "").strip()
        if override:
            server.form.addRow(_hint(f"{SERVER_ENV} is set, so {override} is used instead."))

        profile = _Card("Profile")
        account = self._ctx.friends.account
        registered = self._ctx.friends.registered_here
        self._display_name = QLineEdit()
        self._display_name.setMaxLength(32)
        self._display_name.setEnabled(registered)
        profile.form.addRow("Display name", self._display_name)
        code = QLabel(account.friend_code if registered else "No profile on this server yet")
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        profile.form.addRow("Friend code", code)
        self._delete_profile = QPushButton("Delete my friends profile…")
        self._delete_profile.setObjectName("dangerButton")
        self._delete_profile.setEnabled(account.registered)
        self._delete_profile.clicked.connect(self._confirm_delete_profile)
        self._profile_status = _hint(
            "Removes your profile, friends and everything shared from the server, "
            "and switches to Offline Mode. Your own library is not touched."
        )
        profile.form.addRow(_button_row(self._delete_profile))
        profile.form.addRow(self._profile_status)
        return self._column(mode, server, profile)

    def _build_discord(self) -> QWidget:
        from PySide6.QtWidgets import QComboBox

        from launcher.services.discord import LARGE_MODES, TEMPLATE_VARS

        setup = _Card("Setup")
        self._discord_enabled = QCheckBox("Show what I'm playing in Discord")
        setup.form.addRow(self._discord_enabled)
        self._discord_app_id = QLineEdit()
        self._discord_app_id.setPlaceholderText("Discord Application ID")
        setup.form.addRow("Application ID", self._discord_app_id)
        setup.form.addRow(
            _hint(
                "Discord Developer Portal → Applications → your app → "
                "General Information → Application ID. Paste it here. "
                "Requires the Discord desktop app running."
            )
        )
        self._discord_status = _hint("")
        setup.form.addRow(self._discord_status)

        text = _Card("What it shows")
        self._discord_details = QLineEdit()
        self._discord_details.setPlaceholderText("Playing {game}")
        text.form.addRow("Details", self._discord_details)
        self._discord_state = QLineEdit()
        self._discord_state.setPlaceholderText("via Milso Launcher")
        text.form.addRow("State", self._discord_state)
        self._discord_large_mode = QComboBox()
        for mode in LARGE_MODES:
            self._discord_large_mode.addItem(mode, mode)
        self._discord_large_mode.setToolTip(
            "game-key: per-game cover uploaded under the asset key below; "
            "static: one fixed image; url-template: hosted cover URL."
        )
        text.form.addRow("Cover source", self._discord_large_mode)
        self._discord_large_static = QLineEdit()
        self._discord_large_static.setPlaceholderText("milso-logo")
        text.form.addRow("Static image key", self._discord_large_static)
        self._discord_large_template = QLineEdit()
        self._discord_large_template.setPlaceholderText("https://example.com/{game_key}.png")
        text.form.addRow("Cover URL template", self._discord_large_template)
        self._discord_large_text = QLineEdit()
        self._discord_large_text.setPlaceholderText("{game}")
        text.form.addRow("Cover tooltip", self._discord_large_text)
        self._discord_small_key = QLineEdit()
        self._discord_small_key.setPlaceholderText("optional small image key")
        text.form.addRow("Small image key", self._discord_small_key)
        self._discord_small_text = QLineEdit()
        self._discord_small_text.setPlaceholderText("{elapsed}")
        text.form.addRow("Small tooltip", self._discord_small_text)
        self._discord_show_elapsed = QCheckBox("Show elapsed play time")
        text.form.addRow(self._discord_show_elapsed)
        text.form.addRow(_hint(f"Variables: {', '.join(TEMPLATE_VARS)}."))
        self._discord_key_hint = _hint("")
        text.form.addRow(self._discord_key_hint)

        idle = _Card("When idle")
        self._discord_idle_enabled = QCheckBox("Show something when nothing runs")
        idle.form.addRow(self._discord_idle_enabled)
        self._discord_idle_text = QLineEdit()
        self._discord_idle_text.setPlaceholderText("Browsing library")
        idle.form.addRow("Idle text", self._discord_idle_text)

        self._discord_preview = _hint("")
        preview = _Card("Preview")
        preview.form.addRow(self._discord_preview)

        for widget in (
            self._discord_details,
            self._discord_state,
            self._discord_large_text,
            self._discord_small_text,
            self._discord_small_key,
            self._discord_large_template,
            self._discord_idle_text,
        ):
            widget.textChanged.connect(self._refresh_discord_preview)
        self._discord_large_mode.currentIndexChanged.connect(self._refresh_discord_preview)
        return self._column(setup, text, idle, preview)

    def _refresh_discord_preview(self) -> None:
        from launcher.services.discord import format_template, game_key

        name = "Example Game"
        try:
            games = self._ctx.games.list_games()
            if games:
                name = games[0].name
        except (AttributeError, OSError, RuntimeError):
            pass
        key = game_key(name)
        details = format_template(
            self._discord_details.text() or "Playing {game}",
            game=name, key=key, elapsed=3723, total=7260, platform="linux",
        )
        state = format_template(
            self._discord_state.text() or "",
            game=name, key=key, elapsed=3723, total=7260, platform="linux",
        )
        mode = self._discord_large_mode.currentData() or "game-key"
        if mode == "static":
            image = self._discord_large_static.text() or "milso-logo"
        elif mode == "url-template":
            template = self._discord_large_template.text()
            if template:
                image = format_template(
                    template, game=name, key=key, elapsed=0, total=0, platform=""
                )
            else:
                image = key
        else:
            image = key
        self._discord_preview.setText(
            f"{details} — {state}\nCover: {image} (upload it under this key)."
        )
        self._discord_key_hint.setText(
            f"Upload '{name}' cover as asset key '{key}' (fallback: milso-logo)."
        )

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
        about = _Card("Milso Launcher")
        from launcher.services import updates

        about.form.addRow("Version", QLabel(updates.current_version()))
        self._update_status = _hint(self._update_summary())
        about.form.addRow(self._update_status)
        update_row = QHBoxLayout()
        check_btn = QPushButton("Check for updates")
        check_btn.clicked.connect(self._check_updates)
        update_row.addWidget(check_btn)
        self._download_btn = QPushButton("Download…")
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self._open_update_url)
        update_row.addWidget(self._download_btn)
        update_row.addStretch()
        about.form.addRow(update_row)
        self._auto_check = QCheckBox("Check automatically on startup")
        self._auto_check.setToolTip(
            "Once a day at most. Nothing is downloaded without asking."
        )
        about.form.addRow(self._auto_check)
        self._repo_edit = QLineEdit()
        self._repo_edit.setPlaceholderText(updates.DEFAULT_REPO)
        about.form.addRow("Releases", self._repo_edit)
        about.form.addRow(
            _hint("GitHub repository to check, as owner/name.")
        )
        skip_row = QHBoxLayout()
        self._skip_hint = _hint("")
        skip_row.addWidget(self._skip_hint, stretch=1)
        self._skip_clear_btn = QPushButton("Unskip")
        self._skip_clear_btn.setToolTip("Offer the skipped version again")
        self._skip_clear_btn.clicked.connect(self._clear_skipped_version)
        skip_row.addWidget(self._skip_clear_btn)
        about.form.addRow(skip_row)
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
        self._close_to_tray.setChecked(settings.get_bool("close_to_tray"))
        self._auto_check.setChecked(settings.get_bool("update_auto_check"))
        self._repo_edit.setText(settings.get_str("update_repo"))
        self._refresh_skip_row()
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
        online = settings.get_str("friends_mode") == "online"
        self._online_radio.setChecked(online)
        self._offline_radio.setChecked(not online)
        self._share_presence.setChecked(settings.get_bool("friends_share_presence"))
        self._server_url.setText(settings.get_str("friends_server_url"))
        self._display_name.setText(self._ctx.friends.account.display_name)
        self._discord_enabled.setChecked(settings.get_bool("discord_enabled"))
        self._discord_app_id.setText(settings.get_str("discord_app_id"))
        self._discord_details.setText(settings.get_str("discord_details"))
        self._discord_state.setText(settings.get_str("discord_state"))
        mode = settings.get_str("discord_large_mode") or "game-key"
        index = self._discord_large_mode.findData(mode)
        self._discord_large_mode.setCurrentIndex(index if index >= 0 else 0)
        self._discord_large_static.setText(settings.get_str("discord_large_static"))
        self._discord_large_template.setText(settings.get_str("discord_large_template"))
        self._discord_large_text.setText(settings.get_str("discord_large_text"))
        self._discord_small_key.setText(settings.get_str("discord_small_key"))
        self._discord_small_text.setText(settings.get_str("discord_small_text"))
        self._discord_show_elapsed.setChecked(settings.get_bool("discord_show_elapsed"))
        self._discord_idle_enabled.setChecked(settings.get_bool("discord_idle_enabled"))
        self._discord_idle_text.setText(settings.get_str("discord_idle_text"))
        self._refresh_discord_preview()
        # These flags mean "silenced", so the checkbox is the inverse.
        for key, box in self._prompt_boxes.items():
            box.setChecked(not settings.get_bool(key))

    def _save(self) -> None:
        values = {
            "confirm_remove": self._confirm_remove.isChecked(),
            "close_to_tray": self._close_to_tray.isChecked(),
            "close_to_tray_asked": True,
            "update_auto_check": self._auto_check.isChecked(),
            "update_repo": self._repo_edit.text().strip(),
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
            "friends_mode": "online" if self._online_radio.isChecked() else "offline",
            "friends_server_url": self._server_url.text().strip()
            or str(DEFAULTS["friends_server_url"]),
            "friends_share_presence": self._share_presence.isChecked(),
            "discord_enabled": self._discord_enabled.isChecked(),
            "discord_app_id": self._discord_app_id.text().strip(),
            "discord_details": self._discord_details.text().strip(),
            "discord_state": self._discord_state.text().strip(),
            "discord_large_mode": self._discord_large_mode.currentData() or "game-key",
            "discord_large_static": self._discord_large_static.text().strip(),
            "discord_large_template": self._discord_large_template.text().strip(),
            "discord_large_text": self._discord_large_text.text().strip(),
            "discord_small_key": self._discord_small_key.text().strip(),
            "discord_small_text": self._discord_small_text.text().strip(),
            "discord_show_elapsed": self._discord_show_elapsed.isChecked(),
            "discord_idle_enabled": self._discord_idle_enabled.isChecked(),
            "discord_idle_text": self._discord_idle_text.text().strip(),
        }
        for key, box in self._prompt_boxes.items():
            values[key] = not box.isChecked()
        values.update(self._appearance.appearance.to_settings())
        self._ctx.settings.update(values)
        if self._display_name.isEnabled():
            self._ctx.friends.rename(self._display_name.text())
        self.accept()

    def _preview_look(self, look: Appearance) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, look)

    def _update_summary(self) -> str:
        if self._pending_update is not None:
            return f"Version {self._pending_update.version} is available."
        skipped = self._ctx.settings.get_str("update_skipped_version").strip()
        if skipped:
            return f"Version {skipped} was skipped. Newer releases still notify."
        if not self._ctx.settings.get_bool("update_auto_check"):
            return "Automatic checks are off."
        last = self._ctx.settings.get_str("update_last_check")
        if last:
            return f"Up to date as of {last}."
        return "Never checked."

    def _refresh_skip_row(self) -> None:
        skipped = self._ctx.settings.get_str("update_skipped_version").strip()
        has_skip = bool(skipped)
        self._skip_hint.setText(
            f"Skipped version {skipped}." if has_skip else ""
        )
        self._skip_hint.setVisible(has_skip)
        self._skip_clear_btn.setVisible(has_skip)

    def _clear_skipped_version(self) -> None:
        self._ctx.settings.set("update_skipped_version", "")
        self._pending_update = None
        self._update_status.setText(self._update_summary())
        self._refresh_skip_row()

    def _check_updates(self) -> None:
        from launcher.services import updates

        repo = self._repo_edit.text().strip() or updates.DEFAULT_REPO
        self._update_status.setText("Checking…")
        self._download_btn.setEnabled(False)
        current = updates.current_version()
        self._update_tasks.submit(lambda: updates.check_github(repo, current))

    def _show_update_result(self, info: object) -> None:
        from launcher.services import updates

        if not isinstance(info, UpdateInfo):
            self._update_status.setText("Could not check for updates.")
            return
        if not info.available:
            self._pending_update = None
            if info.version:
                self._ctx.settings.set("update_last_check", updates.stamp_now())
                self._update_status.setText(
                    f"Up to date as of {self._ctx.settings.get_str('update_last_check')}."
                )
            else:
                self._update_status.setText("Could not check for updates.")
            return
        self._ctx.settings.set("update_last_check", updates.stamp_now())
        skipped = self._ctx.settings.get_str("update_skipped_version").strip()
        if info.version and info.version == skipped:
            self._pending_update = None
            self._update_status.setText(
                f"Version {info.version} was skipped. Clear it to be offered again."
            )
            self._download_btn.setEnabled(False)
            return
        self._pending_update = info
        text = f"Version {info.version} is available."
        if info.notes:
            first_line = info.notes.strip().splitlines()[0][:160]
            if first_line:
                text += f" {first_line}"
        self._update_status.setText(text)
        self._download_btn.setEnabled(bool(info.url or info.page_url))

    def _open_update_url(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if self._pending_update is not None:
            url = self._pending_update.page_url or self._pending_update.url
            if url:
                QDesktopServices.openUrl(QUrl(url))

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

    # -- friends -------------------------------------------------------

    def _test_server(self) -> None:
        url = self._server_url.text().strip() or str(DEFAULTS["friends_server_url"])
        try:
            client = FriendsClient(url)
        except ValueError as e:
            self._server_status.setText(str(e))
            self._server_status.show()
            return
        self._server_test.setEnabled(False)
        self._server_status.setText("Checking…")
        self._server_status.show()
        self._friends_tasks.submit(client.ping)

    def _show_server_result(self, message: str) -> None:
        self._server_test.setEnabled(True)
        self._server_status.setText(message)

    def _confirm_delete_profile(self) -> None:
        answer = ask(
            self,
            "Delete Friends Profile",
            "Delete your friends profile?\n\nYour friends, requests and the play "
            "time you shared are removed from the server, and the launcher goes "
            "back to Offline Mode. This can't be undone.",
            default=Answer.NO,
        )
        if answer is not Answer.YES:
            return
        self._delete_profile.setEnabled(False)
        self._profile_status.setText("Deleting…")
        self._ctx.friends.delete_account(self._profile_deleted)

    def _profile_deleted(self, ok: bool, message: str) -> None:
        self._profile_status.setText(message)
        if ok:
            self._offline_radio.setChecked(True)
            self._display_name.clear()
            self._display_name.setEnabled(False)
        else:
            self._delete_profile.setEnabled(True)

    def reject(self) -> None:
        self._tasks.cancel_all()
        self._friends_tasks.cancel_all()
        self._update_tasks.cancel_all()
        if self._appearance.appearance != self._original_look:
            self._preview_look(self._original_look)
        super().reject()


def _open(path: Path) -> None:
    from launcher.services.prefix_tools import open_path

    open_path(path)


def default_for(key: str) -> object:
    """The shipped default for a preference."""
    return DEFAULTS.get(key)
