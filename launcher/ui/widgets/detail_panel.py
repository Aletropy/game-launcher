"""The detail panel for the selected game."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from launcher.core import prefixes
from launcher.core.games import Game
from launcher.ui.theme import restyle
from launcher.ui.widgets.collapsible import CollapsibleSection
from launcher.ui.widgets.elide import ElidingLabel
from launcher.ui.widgets.hero_banner import HeroBanner
from launcher.ui.widgets.log_view import LogView


class GameDetailPanel(QWidget):
    """Artwork, actions, configuration summary and live log for one game."""

    play_requested = Signal(str)
    stop_requested = Signal(str)
    edit_requested = Signal(str)
    favorite_requested = Signal(str)
    artwork_requested = Signal(str)
    remove_requested = Signal(str)
    clear_log_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self._game: Game | None = None
        self._running = False
        self._setup_ui()
        self.set_game(None)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._banner = HeroBanner()
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
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        for label in ("Prefix", "Proton", "App ID", "Executable"):
            value = ElidingLabel("")
            value.setObjectName("infoValue")
            key = QLabel(label)
            key.setObjectName("hintLabel")
            self._info.addRow(key, value)
            self._info_values[label] = value
        layout.addLayout(self._info)

        self._log_section = CollapsibleSection("Log", expanded=True)
        self._log = LogView()
        self._log.stop_requested.connect(self._emit_stop)
        self._log.clear_requested.connect(self._emit_clear_log)
        self._log_section.set_content(self._log)
        layout.addWidget(self._log_section)

        layout.addStretch()

        self._empty = QLabel("Select a game from the list.")
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

        self._art_btn = QPushButton("Artwork…")
        self._art_btn.setFixedHeight(38)
        self._art_btn.clicked.connect(self._emit_artwork)
        row.addWidget(self._art_btn)

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
        self._fav_btn.setProperty("favorite", "true" if game.is_favorite else "false")
        restyle(self._fav_btn)

        self._info_values["Prefix"].setText(prefixes.describe(game.prefix))
        self._info_values["Proton"].setText(game.custom_proton_path or "Default")
        self._info_values["App ID"].setText(game.override_app_id or game.game_id)
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

    # -- signal helpers ------------------------------------------------

    def _name(self) -> str | None:
        return None if self._game is None else self._game.name

    def _emit_play(self) -> None:
        if (name := self._name()) is not None:
            self.play_requested.emit(name)

    def _emit_stop(self) -> None:
        if (name := self._name()) is not None:
            self.stop_requested.emit(name)

    def _emit_edit(self) -> None:
        if (name := self._name()) is not None:
            self.edit_requested.emit(name)

    def _emit_favorite(self) -> None:
        if (name := self._name()) is not None:
            self.favorite_requested.emit(name)

    def _emit_artwork(self) -> None:
        if (name := self._name()) is not None:
            self.artwork_requested.emit(name)

    def _emit_remove(self) -> None:
        if (name := self._name()) is not None:
            self.remove_requested.emit(name)

    def _emit_clear_log(self) -> None:
        if (name := self._name()) is not None:
            self.clear_log_requested.emit(name)
