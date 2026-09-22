"""The main window.

A view: it renders what the controller exposes and forwards what the user
does. It never touches repositories or the filesystem directly.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from launcher.app.library_controller import LibraryController
from launcher.domain.models import Game, SortOrder
from launcher.ui.dialogs.artwork_cleanup import ArtworkCleanupDialog, human
from launcher.ui.dialogs.confirm import Answer, StickyChoice, ask, warn
from launcher.ui.dialogs.game_dialog import AddGameDialog
from launcher.ui.dialogs.import_dialog import ImportGamesDialog
from launcher.ui.dialogs.restore_dialog import RestoreBackupDialog
from launcher.ui.dialogs.saves_dialog import SavesDialog
from launcher.ui.dialogs.settings_dialog import SettingsDialog
from launcher.ui.dialogs.sgdb_dialog import SGDBDialog
from launcher.ui.widgets import log_view
from launcher.ui.widgets.detail_panel import GameDetailPanel
from launcher.ui.widgets.journal import JournalView
from launcher.ui.widgets.sidebar import LibrarySidebar

_LIBRARY_VIEW = 0
_JOURNAL_VIEW = 1


class MainWindow(QMainWindow):
    """The library (sidebar and detail panel) and the play Journal."""

    def __init__(self, controller: LibraryController) -> None:
        super().__init__()
        self._lib = controller
        self._ctx = controller.context
        self.setWindowTitle("Game Launcher")
        self.setMinimumSize(1024, 700)
        self.resize(1280, 800)

        #: One log buffer per game, kept whether or not it is selected.
        self._logs: dict[str, QTextDocument] = {}
        self._artwork_sticky = StickyChoice()
        self._remove_sticky = StickyChoice()

        self._setup_ui()
        self._connect()
        self._lib.reload()

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
        self._views.addWidget(self._build_journal_view())
        root.addWidget(self._views, stretch=1)

        self.setStatusBar(QStatusBar())
        self._restore_view_mode()
        self._install_shortcuts()

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for index, label in ((_LIBRARY_VIEW, "Library"), (_JOURNAL_VIEW, "Journal")):
            button = QPushButton(label)
            button.setObjectName("viewToggle")
            button.setCheckable(True)
            button.setChecked(index == _LIBRARY_VIEW)
            button.setFixedHeight(32)
            self._view_group.addButton(button, index)
            layout.addWidget(button)
        self._view_group.idClicked.connect(self._switch_view)

        layout.addStretch()

        self._saves_btn = QPushButton("Shared Saves…")
        self._saves_btn.setFixedHeight(32)
        self._saves_btn.setToolTip("One copy of your saves, linked into every prefix")
        self._saves_btn.clicked.connect(self._open_saves)
        layout.addWidget(self._saves_btn)

        cleanup_btn = QPushButton("Clean Up Artwork…")
        cleanup_btn.setFixedHeight(32)
        cleanup_btn.clicked.connect(self._clean_up_artwork)
        layout.addWidget(cleanup_btn)

        settings_btn = QPushButton("Settings…")
        settings_btn.setFixedHeight(32)
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)
        return bar

    def _build_library_view(self) -> QWidget:
        page = QWidget()
        page.setObjectName("libraryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        self._sidebar = LibrarySidebar(self._ctx.artwork)
        self._sidebar.setMinimumWidth(240)
        self._sidebar.setMaximumWidth(460)
        splitter.addWidget(self._sidebar)

        self._detail = GameDetailPanel(
            self._ctx.artwork, self._ctx.paths, self._ctx.save_store
        )
        splitter.addWidget(self._detail)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 980])
        layout.addWidget(splitter)
        return page

    def _build_journal_view(self) -> QWidget:
        self._journal = JournalView(self._ctx.artwork)
        return self._journal

    def _connect(self) -> None:
        lib = self._lib
        lib.library_changed.connect(self._render_library)
        lib.game_changed.connect(self._on_game_changed)
        lib.error.connect(lambda title, text: warn(self, title, text))
        lib.status.connect(lambda text: self.statusBar().showMessage(text, 6000))

        side = self._sidebar
        side.selection_changed.connect(self._select_game)
        side.launch_requested.connect(self._launch_game)
        side.add_requested.connect(self._add_game)
        side.import_requested.connect(self._import_games)
        side.filters_changed.connect(self._on_filters_changed)
        side.sort_changed.connect(self._on_sort_changed)

        detail = self._detail
        detail.play_requested.connect(self._launch_game)
        detail.stop_requested.connect(self._lib.stop)
        detail.edit_requested.connect(self._edit_game)
        detail.favorite_requested.connect(self._lib.toggle_favorite)
        detail.artwork_requested.connect(self._fetch_artwork)
        detail.remove_requested.connect(self._remove_game)
        detail.clear_log_requested.connect(self._clear_log)
        detail.prefix_tool_requested.connect(self._run_prefix_tool)
        detail.backup_requested.connect(self._backup_saves)
        detail.restore_requested.connect(self._restore_saves)
        detail.artwork_dropped.connect(self._artwork_dropped)

        journal = self._journal
        journal.play_requested.connect(self._launch_game)
        journal.open_requested.connect(self._open_in_library)

        procs = self._ctx.processes
        procs.game_started.connect(self._on_game_started)
        procs.game_finished.connect(self._on_game_finished)
        procs.game_output.connect(self._on_game_output)
        procs.game_error.connect(self._on_game_output)

        tools = self._ctx.prefix_tools
        tools.tool_failed.connect(lambda label, msg: warn(self, label, msg))
        tools.tool_started.connect(
            lambda label: self.statusBar().showMessage(f"Started {label}.", 4000)
        )

    def _install_shortcuts(self) -> None:
        """Keyboard access to the things people do repeatedly."""
        shortcuts: tuple[tuple[QKeySequence | QKeySequence.StandardKey, object], ...] = (
            (QKeySequence.StandardKey.Find, self._focus_search),
            (QKeySequence("Ctrl+N"), self._add_game),
            (QKeySequence("Ctrl+I"), self._import_games),
            (QKeySequence("Ctrl+,"), self._open_settings),
            (QKeySequence("Ctrl+E"), self._edit_selected),
            (QKeySequence("Ctrl+R"), self._lib.reload),
            (QKeySequence("F5"), self._lib.reload),
            (QKeySequence("Ctrl+P"), self._play_selected),
        )
        for keys, handler in shortcuts:
            QShortcut(keys, self).activated.connect(handler)

    # -- rendering -----------------------------------------------------

    def _render_library(self) -> None:
        visible = self._lib.visible_games()
        selected = self._sidebar.selected_game()
        self._sidebar.set_games(visible, select=selected)
        self._sidebar.set_sort_order(self._lib.sort_order.value)
        for name in self._ctx.processes.running_games:
            self._sidebar.set_running(name, True)
        if not visible:
            self._detail.set_game(None)
        self._refresh_journal()

    def _refresh_journal(self) -> None:
        """Rebuild the Journal from every game, not just the filtered ones."""
        self._journal.refresh(self._lib.games, self._ctx.state.sessions())

    def _on_game_changed(self, name: str) -> None:
        game = self._lib.game(name)
        if game is None:
            return
        self._sidebar.set_games(self._lib.visible_games(), select=name)
        if self._detail_shows(name):
            self._detail.set_game(game)
            self._detail.refresh_artwork()
        self._refresh_journal()

    def _detail_shows(self, name: str) -> bool:
        return self._sidebar.selected_game() == name

    def _select_game(self, name: str) -> None:
        """Show a game's details. This never launches anything."""
        game: Game | None = self._lib.game(name) if name else None
        self._detail.set_game(game)
        if game is None:
            self._detail.attach_log(None)
            return
        self._detail.attach_log(self._logs.get(game.name))
        self._detail.set_running(self._lib.is_running(game.name))

    def _selected(self) -> str | None:
        return self._sidebar.selected_game()

    # -- filters and views ---------------------------------------------

    def _on_filters_changed(self) -> None:
        self._lib.set_search(self._sidebar.search_text())
        self._lib.set_favorites_only(self._sidebar.favorites_only())

    def _on_sort_changed(self, value: str) -> None:
        with contextlib.suppress(ValueError):
            self._lib.set_sort_order(SortOrder(value))

    def _switch_view(self, index: int) -> None:
        self._views.setCurrentIndex(index)
        button = self._view_group.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._ctx.settings.set(
            "view_mode", "journal" if index == _JOURNAL_VIEW else "library"
        )

    def _restore_view_mode(self) -> None:
        # "grid" is what the removed card grid was saved as; the Journal
        # took its place, so open that for anyone who preferred it.
        mode = self._ctx.settings.get_str("view_mode")
        index = _JOURNAL_VIEW if mode in ("journal", "grid") else _LIBRARY_VIEW
        button = self._view_group.button(index)
        if button is not None:
            button.setChecked(True)
        self._views.setCurrentIndex(index)

    def _open_in_library(self, name: str) -> None:
        """Jump from the Journal to a game's page in the library."""
        self._switch_view(_LIBRARY_VIEW)
        if not self._sidebar.select_game(name):
            # Hidden by a filter; clear it so the game can be shown.
            self._sidebar.clear_filters()
            self._sidebar.select_game(name)

    def _focus_search(self) -> None:
        if self._views.currentIndex() != _LIBRARY_VIEW:
            self._switch_view(_LIBRARY_VIEW)
        self._sidebar.focus_search()

    # -- game actions --------------------------------------------------

    def _launch_game(self, name: str) -> None:
        if not self._lib.launch(name):
            return
        # Show the library, where the running game's log is.
        self._open_in_library(name)

    def _play_selected(self) -> None:
        if (name := self._selected()) is not None:
            self._launch_game(name)

    def _edit_selected(self) -> None:
        if (name := self._selected()) is not None:
            self._edit_game(name)

    def _add_game(self) -> None:
        dialog = AddGameDialog(self._ctx.paths, parent=self)
        if not dialog.exec():
            return
        config = dialog.get_config()
        if not self._lib.add_game(config):
            return
        self._sidebar.select_game(config.name)

        if self._ctx.sgdb.configured and self._ctx.settings.get_bool(
            "fetch_artwork_on_add"
        ):
            answer = ask(
                self,
                "Fetch Artwork?",
                f"Fetch artwork from SteamGridDB for '{config.name}'?",
                buttons=(Answer.YES, Answer.NO, Answer.YES_ALL, Answer.NO_ALL),
                default=Answer.YES,
                sticky=self._artwork_sticky,
            )
            if answer in (Answer.YES, Answer.YES_ALL):
                self._fetch_artwork(config.name)

    def _import_games(self) -> None:
        dialog = ImportGamesDialog(self._ctx, parent=self)
        if dialog.exec() and dialog.added:
            self._lib.reload()
            self.statusBar().showMessage(
                f"Imported {len(dialog.added)} game(s).", 6000
            )
            self._sidebar.select_game(dialog.added[0])

    def _edit_game(self, name: str) -> None:
        game = self._lib.game(name)
        if game is None:
            return
        dialog = AddGameDialog(self._ctx.paths, game=game, parent=self)
        if not dialog.exec():
            return
        if self._lib.update_game(name, dialog.get_config()):
            self._sidebar.select_game(dialog.get_config().name)

    def _remove_game(self, name: str) -> None:
        if self._ctx.settings.get_bool("confirm_remove"):
            answer = ask(
                self,
                "Remove Game",
                f"Remove '{name}' from the launcher?\n\n"
                "Its configuration and artwork are deleted. Saved games and "
                "the Wine prefix are left alone.",
                buttons=(Answer.YES, Answer.NO, Answer.YES_ALL, Answer.NO_ALL),
                default=Answer.NO,
                sticky=self._remove_sticky,
            )
            if answer not in (Answer.YES, Answer.YES_ALL):
                return
        self._logs.pop(name, None)
        self._lib.remove_game(name)

    # -- artwork -------------------------------------------------------

    def _fetch_artwork(self, name: str) -> None:
        game = self._lib.game(name)
        dialog = SGDBDialog(
            self._ctx,
            game_name=name,
            steam_app_id=game.config.game_id if game else "",
            parent=self,
        )
        dialog.artwork_downloaded.connect(lambda _: self._lib.refresh_game(name))
        dialog.exec()

    def _artwork_dropped(self, name: str, path: str) -> None:
        answer = ask(
            self,
            "Set Artwork",
            f"Use this image as artwork for '{name}'?\n\n{Path(path).name}",
        )
        if answer is Answer.YES:
            self._lib.set_artwork_from_file(name, Path(path), "grid")

    def _clean_up_artwork(self, *, only_if_worthwhile: bool = False) -> None:
        report = self._ctx.cleaner.scan({g.name for g in self._lib.games})
        if report.is_empty:
            if not only_if_worthwhile:
                QMessageBox.information(
                    self,
                    "Clean Up Artwork",
                    f"Nothing to clean up. Artwork uses {human(report.total_bytes)}.",
                )
            return

        dialog = ArtworkCleanupDialog(self._ctx.cleaner, report, self)
        if dialog.exec() and dialog.result_summary is not None:
            summary = dialog.result_summary
            if summary.errors:
                warn(
                    self,
                    "Clean Up Artwork",
                    "Some files could not be cleaned up:\n"
                    + "\n".join(summary.errors[:10]),
                )
            self.statusBar().showMessage(
                f"Reclaimed {human(summary.freed)} of artwork.", 8000
            )
            self._lib.reload()

    def offer_artwork_cleanup(self) -> None:
        """Offer the cleanup once, the first time it would help.

        Called after the window is on screen, never from __init__: this
        opens a modal dialog, and doing so during construction blocks
        before the window is even visible.
        """
        if self._ctx.settings.get_bool("artwork_cleanup_prompted"):
            return
        self._ctx.settings.set("artwork_cleanup_prompted", True)
        self._clean_up_artwork(only_if_worthwhile=True)

    # -- prefix tools and saves ----------------------------------------

    def _run_prefix_tool(self, name: str, tool: str) -> None:
        game = self._lib.game(name)
        if game is None:
            return
        if tool == "open":
            self._ctx.prefix_tools.open_folder(game.prefix)
        else:
            self._ctx.prefix_tools.run(tool, game.prefix)

    def _backup_saves(self, name: str) -> None:
        game = self._lib.game(name)
        if game is None:
            return
        self.statusBar().showMessage(f"Backing up saves for {name}…")
        try:
            backup = self._ctx.saves.create_backup(name, game.prefix)
        except (OSError, FileNotFoundError) as e:
            self.statusBar().clearMessage()
            warn(self, "Backup Failed", str(e))
            return
        self.statusBar().showMessage(
            f"Backed up {human(backup.size)} to {backup.path.name}.", 8000
        )

    def _restore_saves(self, name: str) -> None:
        game = self._lib.game(name)
        if game is None:
            return
        backups = self._ctx.saves.list_backups(name)
        if not backups:
            QMessageBox.information(
                self,
                "Restore Saves",
                f"There are no backups for '{name}' yet.\n\n"
                "Use Saves → Back up now to make one.",
            )
            return

        dialog = RestoreBackupDialog(name, backups, self)
        outcome = dialog.exec()
        if outcome == 2 and dialog.delete_requested is not None:
            self._ctx.saves.delete_backup(dialog.delete_requested)
            self.statusBar().showMessage("Backup deleted.", 4000)
            return
        if not outcome or dialog.selected is None:
            return

        if ask(
            self,
            "Restore Saves",
            f"Restore the backup from {dialog.selected.label} into "
            f"'{name}'?\n\nFiles it contains will be overwritten.",
            default=Answer.NO,
        ) is not Answer.YES:
            return

        try:
            count = self._ctx.saves.restore(dialog.selected, game.prefix)
        except (OSError, FileNotFoundError) as e:
            warn(self, "Restore Failed", str(e))
            return
        self.statusBar().showMessage(f"Restored {count} file(s).", 8000)

    # -- settings ------------------------------------------------------

    def _open_saves(self) -> None:
        SavesDialog(self._ctx, parent=self).exec()
        self._lib.reload()

    def _open_settings(self) -> None:
        before = self._ctx.settings.get_bool("hide_missing")
        SettingsDialog(self._ctx, parent=self).exec()
        after = self._ctx.settings.get_bool("hide_missing")
        if before != after:
            self._lib.set_hide_missing(after)

    # -- process signals -----------------------------------------------

    def _log_for(self, name: str) -> QTextDocument:
        doc = self._logs.get(name)
        if doc is None:
            doc = log_view.new_document(
                self._ctx.settings.get_int("log_max_lines")
            )
            self._logs[name] = doc
        return doc

    def _clear_log(self, name: str) -> None:
        self._logs[name] = log_view.new_document(
            self._ctx.settings.get_int("log_max_lines")
        )
        if self._detail_shows(name):
            self._detail.attach_log(self._logs[name])

    def _on_game_started(self, name: str) -> None:
        self._log_for(name)
        self._sidebar.set_running(name, True)
        if self._detail_shows(name):
            self._detail.attach_log(self._logs[name])
            self._detail.set_running(True)

    def _on_game_finished(self, name: str, _exit_code: int) -> None:
        self._sidebar.set_running(name, False)
        if self._detail_shows(name):
            self._detail.set_running(False)

    def _on_game_output(self, name: str, text: str) -> None:
        # Buffers accumulate whether or not the game is on screen.
        log_view.append(self._log_for(name), text)
        if self._detail_shows(name):
            self._detail.follow_log()

    # -- lifetime ------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        running = self._ctx.processes.running_games
        if running and ask(
            self,
            "Quit",
            "These games are still running:\n  "
            + "\n  ".join(running)
            + "\n\nQuit anyway? They will keep running.",
            default=Answer.NO,
        ) is not Answer.YES:
            event.ignore()
            return
        super().closeEvent(event)
