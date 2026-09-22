"""Scan a folder and add several games at once."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.domain.models import GameConfig
from launcher.services.importer import Candidate, scan_folder
from launcher.services.tasks import TaskGroup


def _human_size(size: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}"
    return f"{size} B"


class ImportGamesDialog(QDialog):
    """Pick a folder, review what was found, add the ones you want."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._candidates: list[Candidate] = []
        self._tasks = TaskGroup(self)
        self._tasks.finished.connect(lambda _t, r: self._show_results(r))
        self._tasks.failed.connect(lambda _t, m: self._status.setText(m))
        self.added: list[str] = []

        self.setWindowTitle("Import Games")
        self.setMinimumSize(720, 520)
        self._setup_ui()

        last = context.settings.get_str("last_import_folder")
        if last:
            self._folder.setText(last)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("Folder"))
        self._folder = QLineEdit()
        self._folder.setPlaceholderText("~/Games")
        self._folder.returnPressed.connect(self._scan)
        row.addWidget(self._folder, stretch=1)
        browse = QPushButton("Browse")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.setFixedWidth(80)
        self._scan_btn.clicked.connect(self._scan)
        row.addWidget(self._scan_btn)
        self._steam_btn = QPushButton("Steam")
        self._steam_btn.setFixedWidth(80)
        self._steam_btn.setToolTip("Find installed Steam games")
        self._steam_btn.clicked.connect(self._scan_steam)
        row.addWidget(self._steam_btn)
        layout.addLayout(row)

        self._tree = QTreeWidget()
        self._tree.setObjectName("importTree")
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Game", "Executable", "Size"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(False)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemChanged.connect(lambda *_: self._update_button())
        layout.addWidget(self._tree, stretch=1)

        self._status = QLabel("Choose a folder to scan for games.")
        self._status.setObjectName("hintLabel")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        selection_row = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._set_all(True))
        selection_row.addWidget(select_all)
        select_none = QPushButton("Select none")
        select_none.clicked.connect(lambda: self._set_all(False))
        selection_row.addWidget(select_none)
        selection_row.addStretch()
        layout.addLayout(selection_row)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self._import_btn = buttons.addButton(
            "Import", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._import_btn.setObjectName("playButton")
        self._import_btn.setEnabled(False)
        buttons.accepted.connect(self._import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- scanning ------------------------------------------------------

    def _browse(self) -> None:
        start = self._folder.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select Games Folder", start)
        if chosen:
            self._folder.setText(chosen)
            self._scan()

    def _scan(self) -> None:
        raw = self._folder.text().strip()
        if not raw:
            return
        folder = Path(raw).expanduser()
        if not folder.is_dir():
            self._status.setText(f"Not a folder: {folder}")
            return
        self._ctx.settings.set("last_import_folder", str(folder))
        self._scan_btn.setEnabled(False)
        self._status.setText("Scanning…")
        self._tree.clear()
        self._tasks.submit(scan_folder, folder)

    def _show_results(self, result: object) -> None:
        self._scan_btn.setEnabled(True)
        self._steam_btn.setEnabled(True)
        if isinstance(result, list) and result and hasattr(result[0], "best"):
            self._show_steam(result)
            return
        candidates = result if isinstance(result, list) else []
        self._populate(candidates, origin="")
        likely = sum(1 for c in candidates if c.likely_game)
        message = f"Found {len(candidates)} executable(s); {likely} look like games."
        skipped = self._skipped_count()
        if skipped:
            message += f" {skipped} already in your library."
        self._status.setText(message)
        self._update_button()

    def _show_steam(self, games: object) -> None:
        """Show Steam library results: one ticked row per found .exe."""
        from launcher.services.steam_import import SteamGame, already_known

        self._scan_btn.setEnabled(True)
        self._steam_btn.setEnabled(True)
        library = self._ctx.games.list_games()
        known_names = {g.name for g in library}
        known_exes = {g.executable for g in library if g.executable}
        candidates: list[Candidate] = []
        without_exe = 0
        if isinstance(games, list):
            for game in games:
                if not isinstance(game, SteamGame):
                    continue
                if game.best is None:
                    without_exe += 1
                    continue
                best = game.best
                if already_known(game, known_names, known_exes):
                    candidates.append(
                        Candidate(
                            name=game.name,
                            executable=best.executable,
                            size=best.size,
                            likely_game=False,
                            reason="already in your library",
                        )
                    )
                else:
                    candidates.append(
                        Candidate(
                            name=game.name,
                            executable=best.executable,
                            size=best.size,
                            likely_game=best.likely_game,
                            reason=best.reason or f"Steam app {game.app_id}",
                        )
                    )
        self._populate(candidates, origin="Steam")
        message = f"Found {len(candidates)} Steam game(s) with an executable."
        if without_exe:
            message += f" {without_exe} had no .exe found."
        skipped = self._skipped_count()
        if skipped:
            message += f" {skipped} already in your library."
        self._status.setText(message)
        self._update_button()

    def _skipped_count(self) -> int:
        count = 0
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is not None and "(already added)" in item.text(0):
                count += 1
        return count

    def _populate(self, candidates: list[Candidate], *, origin: str) -> None:
        self._candidates = candidates
        self._tree.blockSignals(True)
        existing = {g.name for g in self._ctx.games.list_games()}
        for candidate in candidates:
            item = QTreeWidgetItem(
                [candidate.name, str(candidate.executable), _human_size(candidate.size)]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, candidate)
            already = candidate.name in existing
            tick = candidate.likely_game and not already
            item.setCheckState(
                0, Qt.CheckState.Checked if tick else Qt.CheckState.Unchecked
            )
            label = candidate.name
            if already:
                label += "  (already added)"
            else:
                notes = []
                if origin:
                    notes.append(origin)
                if candidate.reason:
                    notes.append(candidate.reason)
                if notes:
                    label += f"  ({'; '.join(notes)})"
            item.setText(0, label)
            if candidate.reason:
                item.setToolTip(0, candidate.reason)
            self._tree.addTopLevelItem(item)
        self._tree.blockSignals(False)

    def _scan_steam(self) -> None:
        from launcher.services.steam_import import scan_steam_libraries

        self._scan_btn.setEnabled(False)
        self._steam_btn.setEnabled(False)
        self._status.setText("Reading the Steam library…")
        self._tree.clear()
        # Results arrive in _show_results, which dispatches Steam games
        # to _show_steam by shape.
        self._tasks.submit(scan_steam_libraries)

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._tree.blockSignals(True)
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is not None:
                item.setCheckState(0, state)
        self._tree.blockSignals(False)
        self._update_button()

    def _checked(self) -> list[Candidate]:
        chosen: list[Candidate] = []
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is not None and item.checkState(0) == Qt.CheckState.Checked:
                chosen.append(item.data(0, Qt.ItemDataRole.UserRole))
        return chosen

    def _update_button(self) -> None:
        count = len(self._checked())
        self._import_btn.setEnabled(count > 0)
        self._import_btn.setText(
            f"Import {count} game{'s' if count != 1 else ''}" if count else "Import"
        )

    # -- adding --------------------------------------------------------

    def _import(self) -> None:
        repo = self._ctx.games
        failures: list[str] = []
        for candidate in self._checked():
            name = _unique_name(candidate.name, repo.exists)
            try:
                repo.add(
                    GameConfig(name=name, executable=str(candidate.executable))
                )
            except OSError as e:
                failures.append(f"{name}: {e}")
            else:
                self.added.append(name)

        if failures:
            self._status.setText(
                f"Added {len(self.added)}; {len(failures)} failed. "
                + "; ".join(failures[:3])
            )
            if not self.added:
                return
        self.accept()

    def reject(self) -> None:
        self._tasks.cancel_all()
        super().reject()


def _unique_name(name: str, exists) -> str:
    """Append a counter if a game of this name already exists."""
    if not exists(name):
        return name
    for suffix in range(2, 100):
        candidate = f"{name} ({suffix})"
        if not exists(candidate):
            return candidate
    return f"{name} ({id(name)})"
