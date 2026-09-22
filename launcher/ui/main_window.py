"""The main window.

A view: it renders what the controller exposes and forwards what the user
does. It never touches repositories or the filesystem directly.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QShowEvent, QTextDocument
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from launcher.app.data_cleaner import DataKind
from launcher.app.library_controller import LibraryController
from launcher.domain.models import Game, SortOrder
from launcher.ui.dialogs.artwork_cleanup import ArtworkCleanupDialog, human
from launcher.ui.dialogs.artwork_wizard import ArtworkWizard
from launcher.ui.dialogs.backups_dialog import BackupsDialog
from launcher.ui.dialogs.clear_data_dialog import ClearDataDialog
from launcher.ui.dialogs.confirm import Answer, StickyChoice, ask, warn
from launcher.ui.dialogs.game_dialog import AddGameDialog
from launcher.ui.dialogs.import_dialog import ImportGamesDialog
from launcher.ui.dialogs.saves_dialog import SavesDialog
from launcher.ui.dialogs.settings_dialog import SettingsDialog
from launcher.ui.theme import notifier
from launcher.ui.widgets import log_view
from launcher.ui.widgets.detail_panel import GameDetailPanel
from launcher.ui.widgets.friends import FriendsView
from launcher.ui.widgets.journal import JournalView
from launcher.ui.widgets.sidebar import LibrarySidebar

_LIBRARY_VIEW = 0
_JOURNAL_VIEW = 1
_FRIENDS_VIEW = 2
#: The view_mode setting for each view.
_VIEW_MODES = {_LIBRARY_VIEW: "library", _JOURNAL_VIEW: "journal", _FRIENDS_VIEW: "friends"}


class MainWindow(QMainWindow):
    """The library (sidebar and detail panel), the play Journal and Friends."""

    def __init__(self, controller: LibraryController) -> None:
        super().__init__()
        self._lib = controller
        self._ctx = controller.context
        self.setWindowTitle("Milso Launcher")
        self.setMinimumSize(1024, 700)
        self.resize(1280, 800)

        #: One log buffer per game, kept whether or not it is selected.
        self._logs: dict[str, QTextDocument] = {}
        self._artwork_sticky = StickyChoice()
        self._remove_sticky = StickyChoice()
        #: The appearance changed while the window was hidden.
        self._appearance_stale = False

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
        self._views.addWidget(self._build_friends_view())
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
        for index, label in (
            (_LIBRARY_VIEW, "Library"),
            (_JOURNAL_VIEW, "Journal"),
            (_FRIENDS_VIEW, "Friends"),
        ):
            button = QPushButton(label)
            button.setObjectName("viewToggle")
            button.setCheckable(True)
            button.setChecked(index == _LIBRARY_VIEW)
            button.setFixedHeight(32)
            self._view_group.addButton(button, index)
            layout.addWidget(button)
        self._view_group.idClicked.connect(self._switch_view)

        layout.addStretch()

        # Everything else lives in Settings, grouped by subject; saves get
        # a menu here because they are what people reach for mid-session.
        self._saves_btn = QPushButton("Saves")
        self._saves_btn.setObjectName("topMenuButton")
        self._saves_btn.setFixedHeight(32)
        self._saves_btn.setToolTip("Shared saves and backups")
        self._saves_menu = QMenu(self._saves_btn)
        self._saves_menu.addAction("Shared saves\u2026", self._open_saves)
        self._saves_menu.addAction("Backups\u2026", self._open_backups)
        self._saves_menu.addSeparator()
        self._saves_menu.addAction(
            "Back up now",
            lambda: self._lib.saves.backup_in_background("manual backup", pinned=True),
        )
        self._saves_btn.setMenu(self._saves_menu)
        self._saves_btn.setProperty("menu", "true")
        layout.addWidget(self._saves_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("topMenuButton")
        settings_btn.setFixedHeight(32)
        settings_btn.setToolTip("Settings (Ctrl+,)")
        # clicked passes `checked`, which must not land in `page`.
        settings_btn.clicked.connect(lambda _checked: self._open_settings())
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

    def _build_friends_view(self) -> QWidget:
        self._friends = FriendsView(self._ctx.friends, self._ctx.artwork)
        return self._friends

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
        side.filter_changed.connect(self._lib.set_filter)
        side.sort_changed.connect(self._on_sort_changed)
        side.favorites_first_changed.connect(self._lib.set_favorites_first)

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
        detail.backups_requested.connect(self._open_backups)
        detail.artwork_dropped.connect(self._artwork_dropped)
        detail.clear_data_requested.connect(self._clear_data)

        journal = self._journal
        journal.play_requested.connect(self._launch_game)
        journal.open_requested.connect(self._open_in_library)

        self._friends.open_requested.connect(self._open_in_library)
        self._friends.settings_requested.connect(self._open_settings)

        procs = self._ctx.processes
        procs.game_started.connect(self._on_game_started)
        procs.game_finished.connect(self._on_game_finished)
        procs.game_output.connect(self._on_game_output)
        procs.game_error.connect(self._on_game_output)

        notifier().changed.connect(self._on_appearance_changed)

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
        self._sidebar.set_filter(self._lib.filter)
        self._sidebar.set_games(visible, select=selected)
        self._sidebar.set_counts(len(visible), len(self._lib.games))
        self._sidebar.set_sort_order(self._lib.sort_order.value)
        self._sidebar.set_favorites_first(self._lib.favorites_first)
        for name in self._ctx.processes.running_games:
            self._sidebar.set_running(name, True)
        if not visible:
            self._detail.set_game(None)
        self._refresh_journal()
        self._friends.set_local_games(self._lib.games)

    def _on_appearance_changed(self) -> None:
        """Repaint what draws itself; the stylesheet covers the rest."""
        if not self.isVisible():
            # Caught up when shown; a hidden window has nothing to repaint.
            self._appearance_stale = True
            return
        self._appearance_stale = False
        self._render_library()
        self._detail.refresh_artwork()
        self._journal.refresh_artwork()
        self._journal.viewport().update()
        self._friends.refresh_artwork()

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

    def _on_sort_changed(self, value: str) -> None:
        with contextlib.suppress(ValueError):
            self._lib.set_sort_order(SortOrder(value))

    def _switch_view(self, index: int) -> None:
        self._views.setCurrentIndex(index)
        button = self._view_group.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._ctx.settings.set("view_mode", _VIEW_MODES.get(index, "library"))
        # Friends poll more often while someone is looking.
        self._ctx.friends.set_visible(index == _FRIENDS_VIEW)

    def _restore_view_mode(self) -> None:
        # "grid" is what the removed card grid was saved as; the Journal
        # took its place, so open that for anyone who preferred it.
        mode = self._ctx.settings.get_str("view_mode")
        if mode == "grid":
            mode = "journal"
        index = next((i for i, m in _VIEW_MODES.items() if m == mode), _LIBRARY_VIEW)
        button = self._view_group.button(index)
        if button is not None:
            button.setChecked(True)
        self._views.setCurrentIndex(index)
        self._ctx.friends.set_visible(index == _FRIENDS_VIEW)

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
                "Choose Artwork?",
                f"Choose artwork for '{config.name}' now?",
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
        wizard = ArtworkWizard(self._ctx, name, self)
        wizard.applied.connect(self._lib.refresh_game)
        wizard.exec()

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
        self._lib.saves.backup_in_background(f"manual backup ({name})", pinned=True)

    def _open_backups(self, name: str = "") -> None:
        BackupsDialog(self._ctx, self._lib.saves, self, game_hint=name).exec()

    def share_saves_everywhere(self) -> None:
        """Bring every prefix into the shared store, if that is the default.

        Runs after the window is shown; each prefix that still keeps its
        own saves is merged in, with one backup taken first.
        """
        if not self._ctx.settings.get_bool("share_saves_by_default"):
            return
        keeper = self._lib.saves
        if not any(keeper.needs_sharing(p) for p in keeper.all_prefixes()):
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            shared = keeper.share_everything()
        finally:
            self.unsetCursor()
        if shared:
            names = ", ".join(p.name for p, _ in shared)
            self.statusBar().showMessage(f"Now sharing saves: {names}.", 10000)

    # -- settings ------------------------------------------------------

    def _open_saves(self) -> None:
        SavesDialog(self._ctx, self._lib.saves, parent=self).exec()
        self._lib.reload()

    def _open_settings(self, page: str = "appearance") -> None:
        dialog = SettingsDialog(self._ctx, parent=self, page=page)
        dialog.clear_data_requested.connect(lambda: self._clear_data("", dialog))
        dialog.cleanup_requested.connect(self._clean_up_artwork)
        dialog.shared_saves_requested.connect(self._open_saves)
        dialog.backups_requested.connect(self._open_backups)
        dialog.exec()

    def _clear_data(self, name: str = "", parent: QWidget | None = None) -> None:
        dialog = ClearDataDialog(self._ctx, name or None, parent or self)
        if not dialog.exec() or dialog.report is None:
            return
        report = dialog.report
        if DataKind.LOGS in dialog.cleared:
            for game in dialog.cleared_names:
                if game in self._logs:
                    self._clear_log(game)
        if DataKind.ARTWORK in dialog.cleared:
            self._ctx.artwork.invalidate()
        self._lib.reload()
        if self._selected():
            self._select_game(self._selected() or "")
        parts = []
        if report.forgotten:
            parts.append(f"forgot {report.forgotten} removed game(s)")
        if report.sessions:
            parts.append(f"{report.sessions} session(s) cleared")
        if report.artwork_files:
            parts.append(f"{report.artwork_files} image(s) deleted")
        self.statusBar().showMessage(
            ("Data cleared: " + ", ".join(parts) + ".") if parts else "Data cleared.",
            8000,
        )

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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._appearance_stale:
            self._on_appearance_changed()

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
