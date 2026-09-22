"""One game's play sessions, editable.

The Journal shows aggregates; this is the ledger underneath: every
session with its date, length and how it ended, with Delete, Edit
(correct the date or length) and Add (a session played elsewhere).
Totals stay consistent: deleting subtracts, editing adjusts the delta.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, Qt, QTime
from PySide6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.domain.journal import format_duration
from launcher.ui.dialogs.confirm import warn


class SessionsDialog(QDialog):
    """View, correct and add one game's sessions."""

    def __init__(
        self, context: AppContext, game_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._name = game_name
        self.setWindowTitle(f"Sessions — {game_name}")
        self.resize(520, 420)
        self._setup_ui()
        self.refresh()

    # -- layout ----------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(10)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self._list.itemDoubleClicked.connect(lambda *_: self._edit())
        outer.addWidget(self._list, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._add_btn = QPushButton("Add…")
        self._add_btn.clicked.connect(self._add)
        row.addWidget(self._add_btn)
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.clicked.connect(self._edit)
        row.addWidget(self._edit_btn)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        row.addWidget(self._delete_btn)
        row.addStretch()
        outer.addLayout(row)

        buttons = QDialogButtonBox()
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # -- data ------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the list, keeping the total in the subtitle."""
        self._list.clear()
        rows = self._ctx.state.sessions_with_ids(self._name)
        for session_id, session in sorted(rows, reverse=True):
            ended = "crashed" if session.crashed else (
                f"exit {session.exit_code}" if session.exit_code else ""
            )
            approx = " (approx.)" if session.imported else ""
            text = (
                f"{session.started:%a %d %b %Y, %H:%M} — "
                f"{format_duration(session.seconds)}{approx}"
                + (f"  ·  {ended}" if ended else "")
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, session_id)
            self._list.addItem(item)
        total = self._ctx.state.total_playtime([self._name])
        self.setWindowTitle(f"Sessions — {self._name} ({format_duration(total)})")
        self._update_buttons()

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if isinstance(value, int) else None

    def _update_buttons(self) -> None:
        has = self._selected_id() is not None
        self._edit_btn.setEnabled(has)
        self._delete_btn.setEnabled(has)

    # -- actions ---------------------------------------------------------

    def _delete(self) -> None:
        session_id = self._selected_id()
        if session_id is None:
            return
        removed = self._ctx.state.delete_session(session_id)
        if removed is None:
            warn(self, "Sessions", "That session is already gone.")
        self.refresh()

    def _edit(self) -> None:
        session_id = self._selected_id()
        if session_id is None:
            return
        rows = dict(self._ctx.state.sessions_with_ids(self._name))
        session = rows.get(session_id)
        if session is None:
            return
        dialog = _SessionEditor(
            self, started=session.started, seconds=session.seconds, title="Edit session"
        )
        if not dialog.exec():
            return
        if self._ctx.state.update_session(session_id, dialog.started(), dialog.seconds()):
            self.refresh()
        else:
            warn(self, "Sessions", "Could not update that session.")

    def _add(self) -> None:
        dialog = _SessionEditor(self, started=datetime.now(), seconds=3600, title="Add session")
        if not dialog.exec():
            return
        started, seconds = dialog.started(), dialog.seconds()
        self._ctx.state.add_playtime(self._name, seconds)
        self._ctx.state.record_session(self._name, started, seconds)
        self.refresh()


class _SessionEditor(QDialog):
    """Pick a start date and a length for one session."""
    def __init__(
        self, parent: QWidget, *, started: datetime, seconds: int, title: str
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(10)

        self._start = QDateTimeEdit()
        self._start.setDateTime(_to_qdatetime(started))
        self._start.setDisplayFormat("ddd d MMM yyyy, HH:mm")
        self._start.setCalendarPopup(True)
        form.addRow("Started", self._start)

        self._minutes = QSpinBox()
        self._minutes.setRange(1, 60 * 48)
        self._minutes.setValue(max(1, seconds // 60))
        self._minutes.setSuffix(" min")
        form.addRow("Length", self._minutes)
        outer.addLayout(form)

        note = QLabel("Totals update automatically.")
        note.setObjectName("hintLabel")
        outer.addWidget(note)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("playButton")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def started(self) -> datetime:
        value = self._start.dateTime().toPython()
        assert isinstance(value, datetime)
        return value

    def seconds(self) -> int:
        return int(self._minutes.value()) * 60

    def _validate_and_accept(self) -> None:
        if self.started() > datetime.now():
            warn(self, "Sessions", "The start cannot be in the future.")
            return
        self.accept()


def _to_qdatetime(when: datetime) -> QDateTime:
    """A naive datetime as local-time QDateTime, for the editors."""
    return QDateTime(
        QDate(when.year, when.month, when.day),
        QTime(when.hour, when.minute, when.second),
    )
