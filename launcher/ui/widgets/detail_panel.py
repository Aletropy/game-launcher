"""The detail panel for the selected game."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, SignalInstance
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QTextDocument
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.data.paths import Paths
from launcher.domain import prefixes
from launcher.domain.models import (
    Game,
    format_last_played,
    format_playtime,
)
from launcher.services.artwork import EXTENSIONS, ArtworkService
from launcher.ui.theme import restyle
from launcher.ui.widgets.collapsible import CollapsibleSection
from launcher.ui.widgets.elide import ElidingLabel
from launcher.ui.widgets.hero_banner import HeroBanner
from launcher.ui.widgets.log_view import LogView

_INFO_ROWS = ("Played", "Prefix", "Proton", "App ID", "Executable")


class GameDetailPanel(QWidget):
    """Artwork, actions, configuration summary and live log for one game."""

    play_requested = Signal(str)
    stop_requested = Signal(str)
    edit_requested = Signal(str)
    favorite_requested = Signal(str)
    artwork_requested = Signal(str)
    remove_requested = Signal(str)
    clear_log_requested = Signal(str)
    #: game name, tool key
    prefix_tool_requested = Signal(str, str)
    backup_requested = Signal(str)
    restore_requested = Signal(str)
    #: game name, dropped image path
    artwork_dropped = Signal(str, str)

    def __init__(
        self,
        artwork: ArtworkService,
        paths: Paths,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self._artwork = artwork
        self._paths = paths
        self._game: Game | None = None
        self._running = False
        self.setAcceptDrops(True)
        self._setup_ui()
        self.set_game(None)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._banner = HeroBanner(self._artwork)
        outer.addWidget(self._banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        body = QWidget()
        body.setObjectName("detailBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(14)
        scroll.setWidget(body)

        self._title = ElidingLabel("")
        self._title.setObjectName("detailTitle")
        self._title.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._title.setMinimumHeight(30)
        layout.addWidget(self._title)

        layout.addLayout(self._build_actions())

        self._warning = QLabel()
        self._warning.setObjectName("warningLabel")
        self._warning.setWordWrap(True)
        self._warning.setVisible(False)
        layout.addWidget(self._warning)

        self._info = QFormLayout()
        self._info.setContentsMargins(0, 4, 0, 4)
        self._info.setHorizontalSpacing(16)
        self._info.setVerticalSpacing(6)
        self._info_values: dict[str, ElidingLabel] = {}
        self._info_labels: dict[str, QLabel] = {}
        for label in _INFO_ROWS:
            value = ElidingLabel("")
            value.setObjectName("infoValue")
            key = QLabel(label)
            key.setObjectName("hintLabel")
            self._info.addRow(key, value)
            self._info_values[label] = value
            self._info_labels[label] = key
        layout.addLayout(self._info)

        self._log_section = CollapsibleSection("Log", expanded=True)
        self._log = LogView()
        self._log.stop_requested.connect(self._emit_stop)
        self._log.clear_requested.connect(self._emit_clear_log)
        self._log_section.set_content(self._log)
        layout.addWidget(self._log_section)

        layout.addStretch()

        self._empty = QLabel(
            "Select a game from the list, or add one to get started."
        )
        self._empty.setObjectName("emptyLabel")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._empty)

        self._content = scroll

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setObjectName("playButton")
        self._play_btn.setFixedHeight(38)
        self._play_btn.setMinimumWidth(130)
        self._play_btn.clicked.connect(self._emit_play)
        row.addWidget(self._play_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedHeight(38)
        self._stop_btn.clicked.connect(self._emit_stop)
        self._stop_btn.setVisible(False)
        row.addWidget(self._stop_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedHeight(38)
        self._edit_btn.clicked.connect(self._emit_edit)
        row.addWidget(self._edit_btn)

        self._more_btn = QToolButton()
        self._more_btn.setObjectName("moreButton")
        self._more_btn.setText("⋯")
        self._more_btn.setFixedHeight(38)
        self._more_btn.setMinimumWidth(40)
        self._more_btn.setToolTip("Artwork, prefix tools and backups")
        self._more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more_btn.setMenu(self._build_menu())
        row.addWidget(self._more_btn)

        row.addStretch()

        self._fav_btn = QPushButton("☆")
        self._fav_btn.setObjectName("favButton")
        self._fav_btn.setFixedSize(34, 34)
        self._fav_btn.setToolTip("Toggle favorite")
        self._fav_btn.clicked.connect(self._emit_favorite)
        row.addWidget(self._fav_btn)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setFixedHeight(38)
        self._remove_btn.clicked.connect(self._emit_remove)
        row.addWidget(self._remove_btn)

        return row

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(
            "Fetch artwork…", lambda: self._emit_named(self.artwork_requested)
        )
        menu.addSeparator()

        prefix_menu = menu.addMenu("Prefix")
        prefix_menu.addAction(
            "Open folder", lambda: self._emit_tool("open")
        )
        prefix_menu.addAction(
            "Wine configuration", lambda: self._emit_tool("winecfg")
        )
        prefix_menu.addAction("Winetricks", lambda: self._emit_tool("winetricks"))
        prefix_menu.addAction(
            "Wine file browser", lambda: self._emit_tool("explorer")
        )

        saves_menu = menu.addMenu("Saves")
        saves_menu.addAction(
            "Back up now", lambda: self._emit_named(self.backup_requested)
        )
        saves_menu.addAction(
            "Restore…", lambda: self._emit_named(self.restore_requested)
        )
        return menu

    # -- population ----------------------------------------------------

    def set_game(self, game: Game | None) -> None:
        self._game = game
        has_game = game is not None
        self._content.setVisible(has_game)
        self._banner.setVisible(has_game)
        self._empty.setVisible(not has_game)
        if game is None:
            self._banner.set_game(None)
            return

        self._banner.set_game(game.name, game.name)
        self._title.setText(game.name)

        self._fav_btn.setText("★" if game.is_favorite else "☆")
        self._fav_btn.setProperty(
            "favorite", "true" if game.is_favorite else "false"
        )
        restyle(self._fav_btn)

        self._set_played_row(game)
        self._info_values["Prefix"].setText(
            prefixes.describe(game.prefix, self._paths)
        )
        self._info_values["Proton"].setText(
            game.config.custom_proton_path or "Default"
        )
        self._info_values["App ID"].setText(
            game.config.override_app_id or game.config.game_id
        )
        self._info_values["Executable"].setText(game.executable)

        if not game.executable_exists:
            self._warning.setText(
                "The executable for this game was not found. It may be on a "
                "drive that is not mounted."
            )
            self._warning.setVisible(True)
        else:
            self._warning.setVisible(False)

        self._play_btn.setEnabled(game.executable_exists and not self._running)

    def _set_played_row(self, game: Game) -> None:
        """Summarise playtime, hiding the row for a game never played."""
        playtime = format_playtime(game.playtime_seconds)
        when = format_last_played(game.last_played)
        text = f"{playtime}  ·  {when}" if playtime and when else (playtime or when)
        visible = bool(text)
        self._info_values["Played"].setText(text)
        self._info_values["Played"].setVisible(visible)
        self._info_labels["Played"].setVisible(visible)

    def set_running(self, running: bool) -> None:
        self._running = running
        self._stop_btn.setVisible(running)
        self._play_btn.setText("Running…" if running else "▶  Play")
        self._play_btn.setEnabled(
            not running and self._game is not None and self._game.executable_exists
        )
        self._log.set_running(running)
        self._log_section.set_suffix("   ● running" if running else "")
        if running:
            self._log_section.set_expanded(True)

    def attach_log(self, doc: QTextDocument | None) -> None:
        self._log.attach(doc)

    def follow_log(self) -> None:
        self._log.follow()

    # -- artwork drag and drop -----------------------------------------

    @staticmethod
    def _dropped_image(event: QDragEnterEvent | QDropEvent) -> Path | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in EXTENSIONS:
                return path
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._game is not None and self._dropped_image(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        image = self._dropped_image(event)
        if self._game is None or image is None:
            return
        event.acceptProposedAction()
        self.artwork_dropped.emit(self._game.name, str(image))

    # -- signal helpers ------------------------------------------------

    def _name(self) -> str | None:
        return None if self._game is None else self._game.name

    def _emit_named(self, signal: SignalInstance) -> None:
        if (name := self._name()) is not None:
            signal.emit(name)

    def _emit_tool(self, tool: str) -> None:
        if (name := self._name()) is not None:
            self.prefix_tool_requested.emit(name, tool)

    def _emit_play(self) -> None:
        self._emit_named(self.play_requested)

    def _emit_stop(self) -> None:
        self._emit_named(self.stop_requested)

    def _emit_edit(self) -> None:
        self._emit_named(self.edit_requested)

    def _emit_favorite(self) -> None:
        self._emit_named(self.favorite_requested)

    def _emit_remove(self) -> None:
        self._emit_named(self.remove_requested)

    def _emit_clear_log(self) -> None:
        self._emit_named(self.clear_log_requested)
