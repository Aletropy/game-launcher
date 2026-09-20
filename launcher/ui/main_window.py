"""Main application window with Library and Debug tabs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
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
from launcher.ui.debug_tab import DebugTab
from launcher.ui.dialogs.artwork_cleanup import ArtworkCleanupDialog, human
from launcher.ui.dialogs.confirm import Answer, StickyChoice, ask, warn
from launcher.ui.dialogs.game_dialog import AddGameDialog
from launcher.ui.dialogs.sgdb_dialog import SGDBDialog
from launcher.ui.widgets.game_grid import GameGrid


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Game Launcher")
        self.setMinimumSize(1024, 700)
        self.resize(1280, 800)

        self._games: list[Game] = []
        self._process_mgr = ProcessManager(self)
        self._process_mgr.game_started.connect(self._on_game_started)
        self._process_mgr.game_finished.connect(self._on_game_finished)
        self._process_mgr.game_output.connect(self._on_game_output)
        self._process_mgr.game_error.connect(self._on_game_output)

        self._artwork_sticky = StickyChoice()
        self._remove_sticky = StickyChoice()

        self._setup_ui()
        self._load_games()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._tabs = QTabWidget()
        root_layout.addWidget(self._tabs)

        # Library tab
        self._library_tab = self._build_library_tab()
        self._tabs.addTab(self._library_tab, "Library")

        # Debug tab
        self._debug_tab = DebugTab()
        self._debug_tab.stop_requested.connect(self._on_stop_game)
        self._tabs.addTab(self._debug_tab, "Debug")

    def _build_library_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(24, 10, 24, 10)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search games...")
        self._search_edit.setFixedWidth(280)
        self._search_edit.textChanged.connect(self._apply_filter)
        top_layout.addWidget(self._search_edit)

        top_layout.addStretch()

        self._fav_filter = QCheckBox("Favorites only")
        self._fav_filter.toggled.connect(self._apply_filter)
        top_layout.addWidget(self._fav_filter)

        cleanup_btn = QPushButton("Clean Up Artwork…")
        cleanup_btn.setFixedHeight(34)
        cleanup_btn.clicked.connect(self._clean_up_artwork)
        top_layout.addWidget(cleanup_btn)

        add_btn = QPushButton("+ Add Game")
        add_btn.setFixedHeight(34)
        add_btn.clicked.connect(self._add_game)
        top_layout.addWidget(add_btn)

        layout.addWidget(top_bar)

        # Game grid
        self._game_grid = GameGrid()
        self._game_grid.play_requested.connect(self._launch_game)
        self._game_grid.favorite_requested.connect(self._toggle_favorite)
        self._game_grid.edit_requested.connect(self._edit_game)
        self._game_grid.remove_requested.connect(self._remove_game)
        self._game_grid.fetch_artwork_requested.connect(self._fetch_artwork)
        layout.addWidget(self._game_grid)

        return tab

    def _load_games(self) -> None:
        self._games = scan_games()
        missing = [g for g in self._games if not g.executable_exists]
        if missing and not get_flag("skip_missing_check"):
            removed = self._handle_missing_executables(missing)
            if removed:
                self._games = [g for g in self._games if g.name not in removed]

        self._game_grid.set_games(self._games)
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
                QMessageBox.warning(
                    self,
                    "Clean Up Artwork",
                    "Some files could not be cleaned up:\n"
                    + "\n".join(summary.errors[:10]),
                )
            self._load_games()

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

    def _apply_filter(self) -> None:
        text = self._search_edit.text()
        favs_only = self._fav_filter.isChecked()
        fav_names = {g.name for g in self._games if g.is_favorite}
        self._game_grid.filter_cards(text, favs_only, fav_names)

    def _launch_game(self, game_name: str) -> None:
        if not self._process_mgr.launch(game_name):
            return
        # _on_game_started has already marked the card and opened the tab.
        self._tabs.setCurrentWidget(self._debug_tab)

    def _toggle_favorite(self, game_name: str) -> None:
        new_state = toggle_favorite(game_name)
        self._game_grid.set_favorite(game_name, new_state)
        # Update local game data
        for g in self._games:
            if g.name == game_name:
                g.is_favorite = new_state
                break
        self._apply_filter()

    def _add_game(self) -> None:
        dialog = AddGameDialog(parent=self)
        if dialog.exec():
            game = dialog.get_game()
            add_game(game)
            self._load_games()
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
        game = next((g for g in self._games if g.name == game_name), None)
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
        else:
            updated.conf_path = game.conf_path

        update_game(updated)
        self._load_games()

    def _remove_game(self, game_name: str) -> None:
        answer = ask(
            self,
            "Remove Game",
            f"Remove '{game_name}' from the launcher?",
            buttons=(Answer.YES, Answer.NO, Answer.YES_ALL, Answer.NO_ALL),
            default=Answer.NO,
            sticky=self._remove_sticky,
        )
        if answer in (Answer.YES, Answer.YES_ALL):
            remove_game(game_name)
            self._load_games()

    def _fetch_artwork(self, game_name: str) -> None:
        game = next((g for g in self._games if g.name == game_name), None)
        steam_id = game.game_id if game else ""
        dlg = SGDBDialog(game_name=game_name, steam_app_id=steam_id, parent=self)
        dlg.artwork_downloaded.connect(lambda _: self._load_games())
        dlg.exec()

    def _on_game_started(self, game_name: str) -> None:
        self._game_grid.set_running(game_name, True)
        self._debug_tab.add_game(game_name)

    def _on_game_finished(self, game_name: str, exit_code: int) -> None:
        self._game_grid.set_running(game_name, False)
        self._debug_tab.remove_game(game_name)

    def _on_game_output(self, game_name: str, text: str) -> None:
        self._debug_tab.append_output(game_name, text)

    def _on_stop_game(self, game_name: str) -> None:
        self._process_mgr.stop(game_name)
