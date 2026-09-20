"""Game card widget with hero image, name, and play button."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.game_manager import Game

_HERO_DIR = Path(__file__).resolve().parent.parent.parent / "launcher" / "heroes"


class GameCard(QFrame):
    """A card widget representing a single game."""

    play_clicked = Signal(str)
    favorite_clicked = Signal(str)
    edit_clicked = Signal(str)
    remove_clicked = Signal(str)
    fetch_artwork_clicked = Signal(str)

    CARD_WIDTH = 200
    CARD_HEIGHT = 280
    HERO_HEIGHT = 160

    def __init__(self, game: Game, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game = game
        self.setObjectName("gameCard")
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        # Hero image area
        hero_container = QWidget()
        hero_container.setFixedHeight(self.HERO_HEIGHT)
        hero_layout = QVBoxLayout(hero_container)
        hero_layout.setContentsMargins(0, 0, 0, 0)

        self._hero_label = QLabel()
        self._hero_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hero_label.setFixedHeight(self.HERO_HEIGHT)
        self._hero_label.setStyleSheet("background-color: #21262d; border-top-left-radius: 10px; border-top-right-radius: 10px;")

        hero_path = self.game.hero_path
        if hero_path and hero_path.is_file():
            pixmap = QPixmap(str(hero_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.CARD_WIDTH,
                    self.HERO_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._hero_label.setPixmap(scaled)
            else:
                self._set_placeholder()
        else:
            self._set_placeholder()

        hero_layout.addWidget(self._hero_label)
        layout.addWidget(hero_container)

        # Info area
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(10, 6, 10, 0)
        info_layout.setSpacing(4)

        name_row = QHBoxLayout()
        name_row.setSpacing(4)

        self._name_label = QLabel(self.game.name)
        self._name_label.setObjectName("gameNameLabel")
        self._name_label.setMaximumWidth(self.CARD_WIDTH - 50)
        name_row.addWidget(self._name_label)

        self._fav_button = QPushButton()
        self._fav_button.setObjectName("favButton")
        self._fav_button.setFixedSize(24, 24)
        self._fav_button.clicked.connect(lambda: self.favorite_clicked.emit(self.game.name))
        self._update_fav_icon()
        name_row.addWidget(self._fav_button)
        name_row.addStretch()

        info_layout.addLayout(name_row)

        # Running indicator
        self._status_label = QLabel("")
        self._status_label.setObjectName("subtitleLabel")
        self._status_label.setVisible(False)
        info_layout.addWidget(self._status_label)

        # Play button
        self._play_button = QPushButton("Play")
        self._play_button.setObjectName("playButton")
        self._play_button.clicked.connect(lambda: self.play_clicked.emit(self.game.name))
        info_layout.addWidget(self._play_button)

        layout.addWidget(info_widget)

    def _set_placeholder(self) -> None:
        initials = "".join(w[0] for w in self.game.name.split()[:2]).upper()
        self._hero_label.setText(initials)
        self._hero_label.setObjectName("placeholderLabel")
        self._hero_label.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #1a1e2e, stop:1 #0f1923); "
            "border-top-left-radius: 10px; border-top-right-radius: 10px;"
        )

    def _update_fav_icon(self) -> None:
        self._fav_button.setText("\u2605" if self.game.is_favorite else "\u2606")
        self._fav_button.setStyleSheet(
            f"color: {'#f0c040' if self.game.is_favorite else '#8b949e'}; background: transparent; border: none; font-size: 18px;"
        )

    def set_running(self, running: bool) -> None:
        self._status_label.setVisible(running)
        self._status_label.setText("Running..." if running else "")
        self._play_button.setEnabled(not running)

    def update_favorite(self, is_fav: bool) -> None:
        self.game.is_favorite = is_fav
        self._update_fav_icon()

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Fetch Hero Image", lambda: self.fetch_artwork_clicked.emit(self.game.name))
        menu.addSeparator()
        menu.addAction("Edit", lambda: self.edit_clicked.emit(self.game.name))
        menu.addAction("Remove", lambda: self.remove_clicked.emit(self.game.name))
        menu.exec(self.mapToGlobal(pos))
