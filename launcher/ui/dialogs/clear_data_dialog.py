"""Choosing what recorded data to clear, and for which games."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from launcher.app import data_cleaner
from launcher.app.context import AppContext
from launcher.app.data_cleaner import ClearReport, DataKind
from launcher.domain.journal import format_duration
from launcher.ui.dialogs.confirm import Answer, ask

_THIS, _ALL, _REMOVED = 0, 1, 2


class ClearDataDialog(QDialog):
    """Pick a scope and what to clear; each option says what it holds."""

    def __init__(
        self,
        context: AppContext,
        game: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._game = game
        self._names = [g.name for g in context.games.list_games()]
        self._orphans = data_cleaner.orphaned_names(context)
        #: Set once data has been cleared, for the caller to act on.
        self.report: ClearReport | None = None
        self.cleared: set[DataKind] = set()
        self.cleared_names: list[str] = []

        self.setWindowTitle("Clear Data")
        self.setMinimumWidth(500)
        self._setup_ui()
        self._update()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        heading = QLabel("Clear data")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self._scope = QButtonGroup(self)
        options = []
        if self._game:
            options.append((_THIS, f"Only {self._game}"))
        options.append((_ALL, f"All {len(self._names)} games"))
        if self._orphans:
            options.append(
                (_REMOVED, f"Games no longer in the library ({len(self._orphans)})")
            )
        for scope_id, label in options:
            button = QRadioButton(label)
            self._scope.addButton(button, scope_id)
            layout.addWidget(button)
        first = self._scope.buttons()[0]
        first.setChecked(True)
        self._scope.idToggled.connect(self._on_scope)

        layout.addSpacing(6)
        self._boxes: dict[DataKind, tuple[QCheckBox, QLabel]] = {}
        for kind in DataKind:
            row = QVBoxLayout()
            row.setSpacing(0)
            box = QCheckBox(kind.label)
            box.toggled.connect(lambda _on: self._update_button())
            detail = QLabel()
            detail.setObjectName("hintLabel")
            detail.setContentsMargins(26, 0, 0, 4)
            row.addWidget(box)
            row.addWidget(detail)
            layout.addLayout(row)
            self._boxes[kind] = (box, detail)

        self._removed_note = QLabel(
            "Everything recorded about these games is removed: history, "
            "playtime, favourites and launch counts."
        )
        self._removed_note.setObjectName("hintLabel")
        self._removed_note.setWordWrap(True)
        layout.addWidget(self._removed_note)

        quick = QHBoxLayout()
        select_all = QLabel("<a href='all'>Select all</a>  ·  <a href='none'>None</a>")
        select_all.setTextFormat(Qt.TextFormat.RichText)
        select_all.linkActivated.connect(self._select)
        quick.addWidget(select_all)
        quick.addStretch()
        layout.addLayout(quick)

        note = QLabel(
            "A copy of the database is saved first, in "
            f"{self._ctx.paths.state_backups_dir}."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self._clear_btn = buttons.addButton(
            "Clear", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._clear_btn.setObjectName("dangerButton")
        buttons.accepted.connect(self._clear)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- state ---------------------------------------------------------

    def _on_scope(self, _scope_id: int, checked: bool) -> None:
        if checked:
            self._update()

    def _scope_names(self) -> list[str]:
        scope = self._scope.checkedId()
        if scope == _THIS and self._game:
            return [self._game]
        if scope == _REMOVED:
            return self._orphans
        return self._names

    def _selected(self) -> set[DataKind]:
        return {kind for kind, (box, _) in self._boxes.items() if box.isChecked()}

    def _select(self, which: str) -> None:
        for box, _ in self._boxes.values():
            if box.isEnabled():
                box.setChecked(which == "all")

    def _update(self) -> None:
        removed = self._scope.checkedId() == _REMOVED
        names = self._scope_names()
        state = self._ctx.state
        sessions = state.session_count(names)
        playtime = state.total_playtime(names)
        stats = [self._ctx.state.get(n) for n in names]
        launched = sum(1 for s in stats if s.last_played or s.launch_count)
        favourites = sum(1 for s in stats if s.favorite)
        tagged = sum(1 for s in stats if s.tags or s.notes or s.hidden)
        art = sum(len(self._ctx.artwork.files_for(n)) for n in names)
        details = {
            DataKind.HISTORY: f"{sessions} session(s) — {DataKind.HISTORY.description}",
            DataKind.PLAYTIME: f"{format_duration(playtime)} — {DataKind.PLAYTIME.description}",
            DataKind.LAUNCHES: f"{launched} game(s) — {DataKind.LAUNCHES.description}",
            DataKind.FAVORITES: f"{favourites} starred",
            DataKind.COLLECTIONS: f"{tagged} tagged, noted or hidden",
            DataKind.ARTWORK: f"{art} image(s) — {DataKind.ARTWORK.description}",
            DataKind.LOGS: DataKind.LOGS.description,
        }
        for kind, (box, detail) in self._boxes.items():
            box.setVisible(not removed)
            detail.setVisible(not removed)
            detail.setText(details[kind])
        self._removed_note.setVisible(removed)
        self._update_button()

    def _update_button(self) -> None:
        removed = self._scope.checkedId() == _REMOVED
        self._clear_btn.setEnabled(removed or bool(self._selected()))
        self._clear_btn.setText("Forget them" if removed else "Clear")

    # -- action --------------------------------------------------------

    def _clear(self) -> None:
        names = self._scope_names()
        removed = self._scope.checkedId() == _REMOVED
        kinds = self._selected()
        what = (
            "every record of the removed games"
            if removed
            else ", ".join(k.label.lower() for k in DataKind if k in kinds)
        )
        who = names[0] if len(names) == 1 else f"{len(names)} games"
        if ask(
            self,
            "Clear Data",
            f"Clear {what} for {who}?",
            default=Answer.NO,
        ) is not Answer.YES:
            return
        if removed:
            self.report = data_cleaner.forget_orphans(self._ctx)
        else:
            self.report = data_cleaner.clear(self._ctx, names, kinds)
            self.cleared = kinds
        self.cleared_names = names
        self.accept()
