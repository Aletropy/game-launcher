"""Game card widget with hero image, name, and play button."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from launcher.domain.models import Game
from launcher.services.artwork import GRID, ArtworkService
from launcher.ui.theme import restyle
from launcher.ui.widgets.elide import ElidingLabel


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

    def __init__(
        self,
        game: Game,
        artwork: ArtworkService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.game = game
        self._artwork = artwork
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
        self._hero_label.setObjectName("heroLabel")

        art = self._artwork.pixmap(
            self.game.name,
            GRID.name,
            QSize(self.CARD_WIDTH, self.HERO_HEIGHT),
            expand=True,
        )
        if art is None:
            self._set_placeholder()
        else:
            self._hero_label.setPixmap(art)

        hero_layout.addWidget(self._hero_label)
        layout.addWidget(hero_container)

        # Info area
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(10, 6, 10, 0)
        info_layout.setSpacing(4)

        name_row = QHBoxLayout()
        name_row.setSpacing(4)

        self._name_label = ElidingLabel(self.game.name)
        self._name_label.setObjectName("gameNameLabel")
        self._name_label.setFixedWidth(self.CARD_WIDTH - 50)
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
        restyle(self._hero_label)

    def _update_fav_icon(self) -> None:
        self._fav_button.setText("\u2605" if self.game.is_favorite else "\u2606")
        self._fav_button.setProperty("favorite", "true" if self.game.is_favorite else "false")
        restyle(self._fav_button)

    def set_running(self, running: bool) -> None:
        self._status_label.setVisible(running)
        self._status_label.setText("Running..." if running else "")
        self._play_button.setEnabled(not running)

    def update_favorite(self, is_fav: bool) -> None:
        self.game.stats.favorite = is_fav
        self._update_fav_icon()

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Fetch Hero Image", lambda: self.fetch_artwork_clicked.emit(self.game.name))
        menu.addSeparator()
        menu.addAction("Edit", lambda: self.edit_clicked.emit(self.game.name))
        menu.addAction("Remove", lambda: self.remove_clicked.emit(self.game.name))
        menu.exec(self.mapToGlobal(pos))
