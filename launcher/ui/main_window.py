"""Main application window: sidebar, detail panel and an alternate grid view."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from launcher.core.games import (
    Game,
    add_game,
    remove_game,
    rename_game,
    scan_games,
    toggle_favorite,
    update_game,
)
from launcher.core.settings import get_flag, get_sgdb_api_key, set_flag
from launcher.services import artwork
from launcher.services.process import ProcessManager
from launcher.ui.dialogs.artwork_cleanup import ArtworkCleanupDialog, human
from launcher.ui.dialogs.confirm import Answer, StickyChoice, ask, warn
from launcher.ui.dialogs.game_dialog import AddGameDialog
from launcher.ui.dialogs.sgdb_dialog import SGDBDialog
from launcher.ui.widgets import log_view
from launcher.ui.widgets.detail_panel import GameDetailPanel
from launcher.ui.widgets.game_grid import GameGrid
from launcher.ui.widgets.sidebar import LibrarySidebar

_LIST_VIEW = 0
_GRID_VIEW = 1


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Game Launcher")
        self.setMinimumSize(1024, 700)
        self.resize(1280, 800)

        self._games: list[Game] = []
        #: One log buffer per game, kept whether or not that game is selected.
        self._logs: dict[str, QTextDocument] = {}

        self._process_mgr = ProcessManager(self)
        self._process_mgr.game_started.connect(self._on_game_started)
        self._process_mgr.game_finished.connect(self._on_game_finished)
        self._process_mgr.game_output.connect(self._on_game_output)
        self._process_mgr.game_error.connect(self._on_game_output)

        self._artwork_sticky = StickyChoice()
        self._remove_sticky = StickyChoice()

        self._setup_ui()
        self._load_games()

    # -- construction --------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        self._views = QStackedWidget()
        self._views.addWidget(self._build_library_view())
        self._views.addWidget(self._build_grid_view())
        root.addWidget(self._views, stretch=1)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for index, label in ((_LIST_VIEW, "List"), (_GRID_VIEW, "Grid")):
            button = QPushButton(label)
            button.setObjectName("viewToggle")
            button.setCheckable(True)
            button.setChecked(index == _LIST_VIEW)
            button.setFixedHeight(32)
            self._view_group.addButton(button, index)
            layout.addWidget(button)
        self._view_group.idClicked.connect(self._switch_view)

        layout.addStretch()

        cleanup_btn = QPushButton("Clean Up Artwork…")
        cleanup_btn.setFixedHeight(32)
        cleanup_btn.clicked.connect(self._clean_up_artwork)
        layout.addWidget(cleanup_btn)

        return bar

    def _build_library_view(self) -> QWidget:
        page = QWidget()
        page.setObjectName("libraryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        self._sidebar = LibrarySidebar()
        self._sidebar.setMinimumWidth(240)
        self._sidebar.setMaximumWidth(420)
        self._sidebar.selection_changed.connect(self._select_game)
        self._sidebar.launch_requested.connect(self._launch_game)
        self._sidebar.add_requested.connect(self._add_game)
        self._sidebar.filters_changed.connect(self._apply_filter)
        splitter.addWidget(self._sidebar)

        self._detail = GameDetailPanel()
        self._detail.play_requested.connect(self._launch_game)
        self._detail.stop_requested.connect(self._on_stop_game)
        self._detail.edit_requested.connect(self._edit_game)
        self._detail.favorite_requested.connect(self._toggle_favorite)
        self._detail.artwork_requested.connect(self._fetch_artwork)
        self._detail.remove_requested.connect(self._remove_game)
        self._detail.clear_log_requested.connect(self._clear_log)
        splitter.addWidget(self._detail)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1000])
        layout.addWidget(splitter)
        return page

    def _build_grid_view(self) -> QWidget:
        page = QWidget()
        page.setObjectName("gridPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self._game_grid = GameGrid()
        self._game_grid.play_requested.connect(self._launch_game)
        self._game_grid.favorite_requested.connect(self._toggle_favorite)
        self._game_grid.edit_requested.connect(self._edit_game)
        self._game_grid.remove_requested.connect(self._remove_game)
        self._game_grid.fetch_artwork_requested.connect(self._fetch_artwork)
        layout.addWidget(self._game_grid)
        return page

    def _switch_view(self, index: int) -> None:
        self._views.setCurrentIndex(index)
        self._apply_filter()

    # -- data ----------------------------------------------------------

    def _load_games(self, *, select: str | None = None) -> None:
        self._games = scan_games()
        missing = [g for g in self._games if not g.executable_exists]
        if missing and not get_flag("skip_missing_check"):
            removed = self._handle_missing_executables(missing)
            if removed:
                self._games = [g for g in self._games if g.name not in removed]

        self._sidebar.set_games(self._games, select=select)
        self._game_grid.set_games(self._games)
        for name in self._process_mgr.running_games:
            self._sidebar.set_running(name, True)
        self._apply_filter()

    def _handle_missing_executables(self, missing: list[Game]) -> set[str]:
        """Ask about each game whose executable is gone.

        Only configurations the user actually confirmed are deleted; the names
        of those are returned. Everything else stays on disk and in the library
        so that a game on an unplugged drive is not silently lost.
        """
        removed: set[str] = set()
        sticky = StickyChoice()
        for game in missing:
            answer = ask(
                self,
                "Game Not Found",
                f"Game executable not found:\n{game.executable}\n({game.name})\n\n"
                "Remove this configuration?",
                buttons=(Answer.YES, Answer.NO, Answer.YES_ALL, Answer.DONT_ASK),
                default=Answer.NO,
                icon=QMessageBox.Icon.Warning,
                sticky=sticky,
                persist_key="skip_missing_check",
            )
            if answer is Answer.DONT_ASK:
                # Silences the prompt; it does not delete anything.
                break
            if answer in (Answer.YES, Answer.YES_ALL) and remove_game(game.name):
                removed.add(game.name)
        return removed

    def _apply_filter(self) -> None:
        text = self._sidebar.search_text()
        favs_only = self._sidebar.favorites_only()
        fav_names = {g.name for g in self._games if g.is_favorite}
        self._sidebar.apply_filter(text, favs_only, fav_names)
        self._game_grid.filter_cards(text, favs_only, fav_names)

    def _game(self, game_name: str) -> Game | None:
        return next((g for g in self._games if g.name == game_name), None)

    def _select_game(self, game_name: str) -> None:
        """Show a game's details. This never launches anything."""
        game = self._game(game_name) if game_name else None
        self._detail.set_game(game)
        if game is None:
            self._detail.attach_log(None)
            return
        self._detail.attach_log(self._logs.get(game.name))
        self._detail.set_running(self._process_mgr.is_running(game.name))

    def _detail_shows(self, game_name: str) -> bool:
        return self._sidebar.selected_game() == game_name

    # -- actions -------------------------------------------------------

    def _launch_game(self, game_name: str) -> None:
        if not self._process_mgr.launch(game_name):
            return
        if self._views.currentIndex() == _GRID_VIEW:
            button = self._view_group.button(_LIST_VIEW)
            if button is not None:
                button.setChecked(True)
            self._switch_view(_LIST_VIEW)
        self._sidebar.select_game(game_name)

    def _on_stop_game(self, game_name: str) -> None:
        self._process_mgr.stop(game_name)

    def _toggle_favorite(self, game_name: str) -> None:
        new_state = toggle_favorite(game_name)
        self._game_grid.set_favorite(game_name, new_state)
        for g in self._games:
            if g.name == game_name:
                g.is_favorite = new_state
                break
        self._sidebar.set_games(self._games, select=game_name)
        self._apply_filter()
        if self._detail_shows(game_name):
            self._detail.set_game(self._game(game_name))

    def _add_game(self) -> None:
        dialog = AddGameDialog(parent=self)
        if not dialog.exec():
            return
        game = dialog.get_game()
        add_game(game)
        self._load_games(select=game.name)

        if get_sgdb_api_key():
            answer = ask(
                self,
                "Fetch Artwork?",
                f"Fetch hero/grid artwork from SteamGridDB for '{game.name}'?",
                buttons=(Answer.YES, Answer.NO, Answer.YES_ALL, Answer.NO_ALL),
                default=Answer.YES,
                sticky=self._artwork_sticky,
            )
            if answer in (Answer.YES, Answer.YES_ALL):
                self._fetch_artwork(game.name)

    def _edit_game(self, game_name: str) -> None:
        game = self._game(game_name)
        if game is None:
            return
        dialog = AddGameDialog(game=game, parent=self)
        if not dialog.exec():
            return

        updated = dialog.get_game()
        if updated.name != game.name:
            # The conf stem is the game's identity, so a rename has to move
            # the conf, the artwork and the favourite together.
            try:
                updated.conf_path = rename_game(game.name, updated.name)
            except FileExistsError:
                warn(
                    self,
                    "Rename Failed",
                    f"A game named '{updated.name}' already exists.",
                )
                return
            except OSError as e:
                warn(self, "Rename Failed", str(e))
                return
            if game.name in self._logs:
                self._logs[updated.name] = self._logs.pop(game.name)
        else:
            updated.conf_path = game.conf_path

        update_game(updated)
        self._load_games(select=updated.name)

    def _remove_game(self, game_name: str) -> None:
        answer = ask(
            self,
            "Remove Game",
            f"Remove '{game_name}' from the launcher?\n\n"
            "Its configuration and artwork are deleted. Saved games and the "
            "Wine prefix are left alone.",
            buttons=(Answer.YES, Answer.NO, Answer.YES_ALL, Answer.NO_ALL),
            default=Answer.NO,
            sticky=self._remove_sticky,
        )
        if answer in (Answer.YES, Answer.YES_ALL):
            remove_game(game_name)
            self._logs.pop(game_name, None)
            self._load_games()

    def _fetch_artwork(self, game_name: str) -> None:
        game = self._game(game_name)
        steam_id = game.game_id if game else ""
        dlg = SGDBDialog(game_name=game_name, steam_app_id=steam_id, parent=self)
        dlg.artwork_downloaded.connect(lambda _: self._load_games(select=game_name))
        dlg.exec()

    def _clean_up_artwork(self, *, only_if_worthwhile: bool = False) -> None:
        """Scan stored artwork and offer to tidy it up."""
        report = artwork.scan({g.name for g in self._games})
        if report.is_empty:
            if not only_if_worthwhile:
                QMessageBox.information(
                    self,
                    "Clean Up Artwork",
                    f"Nothing to clean up. Artwork uses {human(report.total_bytes)}.",
                )
            return

        dialog = ArtworkCleanupDialog(report, self)
        if dialog.exec() and dialog.result_summary is not None:
            summary = dialog.result_summary
            if summary.errors:
                warn(
                    self,
                    "Clean Up Artwork",
                    "Some files could not be cleaned up:\n"
                    + "\n".join(summary.errors[:10]),
                )
            self._load_games(select=self._sidebar.selected_game())

    def offer_artwork_cleanup(self) -> None:
        """Offer the cleanup once, the first time it would help.

        Called after the window is on screen, never from __init__: this
        opens a modal dialog, and doing so during construction blocks
        before the window is even visible.
        """
        if get_flag("artwork_cleanup_prompted"):
            return
        set_flag("artwork_cleanup_prompted", True)
        self._clean_up_artwork(only_if_worthwhile=True)

    # -- process signals -----------------------------------------------

    def _log_for(self, game_name: str) -> QTextDocument:
        doc = self._logs.get(game_name)
        if doc is None:
            doc = log_view.new_document()
            self._logs[game_name] = doc
        return doc

    def _clear_log(self, game_name: str) -> None:
        self._logs[game_name] = log_view.new_document()
        if self._detail_shows(game_name):
            self._detail.attach_log(self._logs[game_name])

    def _on_game_started(self, game_name: str) -> None:
        self._log_for(game_name)
        self._game_grid.set_running(game_name, True)
        self._sidebar.set_running(game_name, True)
        if self._detail_shows(game_name):
            self._detail.attach_log(self._logs[game_name])
            self._detail.set_running(True)

    def _on_game_finished(self, game_name: str, _exit_code: int) -> None:
        self._game_grid.set_running(game_name, False)
        self._sidebar.set_running(game_name, False)
        if self._detail_shows(game_name):
            self._detail.set_running(False)

    def _on_game_output(self, game_name: str, text: str) -> None:
        # Buffers accumulate whether or not the game is on screen.
        log_view.append(self._log_for(game_name), text)
        if self._detail_shows(game_name):
            self._detail.follow_log()
