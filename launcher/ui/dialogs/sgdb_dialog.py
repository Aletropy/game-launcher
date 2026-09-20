"""Dialog for searching and downloading artwork from SteamGridDB."""

from __future__ import annotations

import threading
import urllib.request
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from launcher.core.settings import get_sgdb_api_key, set_sgdb_api_key
from launcher.services import artwork
from launcher.services.sgdb import (
    SGDBError,
    download_bytes,
    get_grids,
    get_heroes,
    search_games,
)
from launcher.ui.dialogs.confirm import warn

_THUMB_SIZE = (200, 120)
_GRID_SPACING = 8


class _ImageTile(QFrame):
    """Clickable thumbnail tile for an artwork result."""

    clicked = Signal(str)

    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.setObjectName("gameCard")
        self.setObjectName("thumbTile")
        self.setFixedSize(_THUMB_SIZE[0] + 8, _THUMB_SIZE[1] + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFixedSize(_THUMB_SIZE[0], _THUMB_SIZE[1])
        layout.addWidget(self._label)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            _THUMB_SIZE[0],
            _THUMB_SIZE[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.url)
        super().mousePressEvent(event)


class SGDBDialog(QDialog):
    """Dialog to search SteamGridDB and download hero/grid artwork."""

    artwork_downloaded = Signal(Path)
    _sig_search_done = Signal(list, str)
    _sig_search_error = Signal(str)
    _sig_thumb_ready = Signal(object, QPixmap)
    _sig_download_done = Signal(object)
    _sig_download_error = Signal(str)

    def __init__(
        self,
        game_name: str = "",
        steam_app_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.game_name = game_name
        self.steam_app_id = steam_app_id
        self.setWindowTitle("SteamGridDB Artwork")
        self.setMinimumSize(700, 600)
        self._selected_url: str = ""
        self._tiles: list[_ImageTile] = []
        self._setup_ui()
        self._sig_search_done.connect(self._populate_results)
        self._sig_search_error.connect(self._show_error)
        self._sig_thumb_ready.connect(self._set_thumb_pixmap)
        self._sig_download_done.connect(self._on_download_done)
        self._sig_download_error.connect(self._show_error)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        api_key = get_sgdb_api_key()
        if not api_key:
            info = QLabel(
                "Enter your SteamGridDB API key to search for artwork.\n"
                "Get one at: https://www.steamgriddb.com/profile/preferences"
            )
            info.setWordWrap(True)
            info.setObjectName("hintLabel")
            layout.addWidget(info)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self._key_edit = QLineEdit(api_key)
        self._key_edit.setPlaceholderText("Your SteamGridDB API key")
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self._key_edit)
        save_key_btn = QPushButton("Save")
        save_key_btn.setFixedWidth(60)
        save_key_btn.clicked.connect(self._save_key)
        key_row.addWidget(save_key_btn)
        layout.addLayout(key_row)

        search_row = QHBoxLayout()
        self._search_edit = QLineEdit(self.game_name)
        self._search_edit.setPlaceholderText("Search game name...")
        self._search_edit.returnPressed.connect(self._search)
        search_row.addWidget(self._search_edit)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["Heroes", "Grids"])
        self._type_combo.setFixedWidth(100)
        search_row.addWidget(self._type_combo)

        self._search_btn = QPushButton("Search")
        self._search_btn.setFixedWidth(80)
        self._search_btn.clicked.connect(self._search)
        search_row.addWidget(self._search_btn)
        layout.addLayout(search_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("hintLabel")
        layout.addWidget(self._status_label)

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._results_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._results_container = QWidget()
        self._results_layout = QGridLayout(self._results_container)
        self._results_layout.setSpacing(_GRID_SPACING)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_scroll.setWidget(self._results_container)
        layout.addWidget(self._results_scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        download_btn = QPushButton("Download & Apply")
        download_btn.setObjectName("playButton")
        download_btn.setEnabled(False)
        download_btn.clicked.connect(self._download_selected)
        self._download_btn = download_btn
        btn_row.addWidget(download_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _save_key(self) -> None:
        key = self._key_edit.text().strip()
        set_sgdb_api_key(key)
        self._status_label.setText("API key saved.")

    def _search(self) -> None:
        key = self._key_edit.text().strip()
        if not key:
            warn(self, "Missing API Key", "Please enter your SteamGridDB API key.")
            return
        query = self._search_edit.text().strip()
        if not query:
            return
        art_type = self._type_combo.currentText().lower().rstrip("s")
        self._search_btn.setEnabled(False)
        self._status_label.setText("Searching...")
        self._clear_results()
        threading.Thread(
            target=self._do_search, args=(query, key, art_type), daemon=True
        ).start()

    def _do_search(self, query: str, api_key: str, art_type: str) -> None:
        try:
            games = search_games(query, api_key)
        except SGDBError as e:
            self._sig_search_error.emit(str(e))
            return
        except Exception as e:
            self._sig_search_error.emit(f"Unexpected error: {e}")
            return
        if not games:
            self._sig_search_error.emit("No games found.")
            return
        game_id = games[0]["id"]
        try:
            if art_type == "hero":
                results = get_heroes(game_id, api_key)
            else:
                results = get_grids(game_id, api_key)
        except SGDBError as e:
            self._sig_search_error.emit(str(e))
            return
        except Exception as e:
            self._sig_search_error.emit(f"Unexpected error: {e}")
            return
        self._sig_search_done.emit(results, art_type)

    def _populate_results(self, results: list, art_type: str) -> None:
        self._search_btn.setEnabled(True)
        if not results:
            self._status_label.setText("No artwork found.")
            return
        self._status_label.setText(f"Found {len(results)} image(s). Click one to select.")
        for item in results:
            thumb_url = item.get("thumb", item.get("url", ""))
            full_url = item.get("url", thumb_url)
            if not thumb_url:
                continue
            tile = _ImageTile(full_url)
            tile.clicked.connect(self._on_tile_clicked)
            self._tiles.append(tile)
            threading.Thread(
                target=self._load_thumb, args=(thumb_url, tile), daemon=True
            ).start()
        self._relayout_grid()

    def _relayout_grid(self) -> None:
        """Recompute grid positions for all tiles based on available width."""
        while self._results_layout.count():
            self._results_layout.takeAt(0)
        available = self._results_scroll.viewport().width()
        tile_w = _THUMB_SIZE[0] + 8 + _GRID_SPACING
        cols = max(1, available // tile_w)
        for i, tile in enumerate(self._tiles):
            row, col = divmod(i, cols)
            self._results_layout.addWidget(tile, row, col)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._relayout_grid()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_grid()

    def _show_error(self, msg: str) -> None:
        self._search_btn.setEnabled(True)
        self._status_label.setText(msg)

    def _load_thumb(self, url: str, tile: _ImageTile) -> None:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            pix = QPixmap()
            pix.loadFromData(data)
            self._sig_thumb_ready.emit(tile, pix)
        except Exception:
            pass

    def _set_thumb_pixmap(self, tile: _ImageTile, pixmap: QPixmap) -> None:
        tile.set_pixmap(pixmap)

    def _on_tile_clicked(self, url: str) -> None:
        self._selected_url = url
        self._download_btn.setEnabled(True)

    def _download_selected(self) -> None:
        if not self._selected_url:
            return
        game_name = self.game_name or self._search_edit.text().strip()
        if not game_name:
            warn(self, "Missing Name", "No game name available.")
            return
        art = artwork.HERO.name if self._type_combo.currentText() == "Heroes" else artwork.GRID.name
        self._download_btn.setEnabled(False)
        self._status_label.setText("Downloading...")
        threading.Thread(
            target=self._do_download,
            args=(self._selected_url, game_name, art),
            daemon=True,
        ).start()

    def _do_download(self, url: str, game_name: str, art: str) -> None:
        try:
            # Fetch the bytes here, but store on the GUI thread: the artwork
            # service writes and invalidates the shared pixmap cache.
            data = download_bytes(url)
            self._sig_download_done.emit((game_name, art, data))
        except SGDBError as e:
            self._sig_download_error.emit(str(e))
        except Exception as e:
            self._sig_download_error.emit(f"Download failed: {e}")

    def _on_download_done(self, payload: object) -> None:
        game_name, art, data = cast("tuple[str, str, bytes]", payload)
        try:
            path = artwork.store(game_name, art, data)
        except OSError as e:
            self._show_error(f"Could not save artwork: {e}")
            return
        self._download_btn.setEnabled(True)
        self._status_label.setText("Artwork downloaded and applied!")
        self.artwork_downloaded.emit(path)

    def _clear_results(self) -> None:
        while self._results_layout.count():
            child = self._results_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._tiles.clear()
        self._selected_url = ""
        self._download_btn.setEnabled(False)
