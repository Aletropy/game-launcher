"""Shared confirmation prompts.

The launcher asks the same shape of question in several places: yes/no
with optional "to all" variants and a sticky answer that suppresses
further prompts. This centralises that, and returns an enum instead of
requiring callers to compare button label text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtWidgets import QAbstractButton, QMessageBox, QWidget

from launcher.data.settings_store import SettingsStore


class Answer(Enum):
    """What the user chose."""

    YES = auto()
    NO = auto()
    YES_ALL = auto()
    NO_ALL = auto()
    DONT_ASK = auto()
    #: The dialog was dismissed without choosing (e.g. the window close button).
    CANCEL = auto()


_LABELS: dict[Answer, str] = {
    Answer.YES: "Yes",
    Answer.NO: "No",
    Answer.YES_ALL: "Yes to All",
    Answer.NO_ALL: "No to All",
    Answer.DONT_ASK: "Don't Ask Again",
}

_ROLES: dict[Answer, QMessageBox.ButtonRole] = {
    Answer.YES: QMessageBox.ButtonRole.AcceptRole,
    Answer.NO: QMessageBox.ButtonRole.RejectRole,
    Answer.YES_ALL: QMessageBox.ButtonRole.AcceptRole,
    Answer.NO_ALL: QMessageBox.ButtonRole.RejectRole,
    Answer.DONT_ASK: QMessageBox.ButtonRole.RejectRole,
}


@dataclass
class StickyChoice:
    """Remembers a "to all" answer for the rest of a run of prompts."""

    value: Answer | None = None

    def resolved(self) -> Answer | None:
        """The answer to reuse, or None to ask again."""
        if self.value is Answer.YES_ALL:
            return Answer.YES
        if self.value is Answer.NO_ALL:
            return Answer.NO
        return None

    def reset(self) -> None:
        self.value = None


def ask(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    buttons: Sequence[Answer] = (Answer.YES, Answer.NO),
    default: Answer = Answer.NO,
    icon: QMessageBox.Icon = QMessageBox.Icon.Question,
    sticky: StickyChoice | None = None,
    persist_key: str | None = None,
    settings: SettingsStore | None = None,
) -> Answer:
    """Ask a question, honouring sticky and persisted answers.

    Returns CANCEL if the dialog was dismissed without a choice.
    """
    if persist_key is not None and settings is not None and settings.get_bool(
        persist_key
    ):
        return Answer.DONT_ASK
    if sticky is not None:
        remembered = sticky.resolved()
        if remembered is not None:
            return remembered

    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon)

    mapping: dict[QAbstractButton, Answer] = {}
    for answer in buttons:
        button = msg.addButton(_LABELS[answer], _ROLES[answer])
        mapping[button] = answer
        if answer is default:
            msg.setDefaultButton(button)

    msg.exec()

    chosen = mapping.get(msg.clickedButton(), Answer.CANCEL)

    if sticky is not None and chosen in (Answer.YES_ALL, Answer.NO_ALL):
        sticky.value = chosen
    if persist_key is not None and settings is not None and chosen is Answer.DONT_ASK:
        settings.set(persist_key, True)

    return chosen


def confirm(parent: QWidget | None, title: str, text: str) -> bool:
    """A plain yes/no question. True only on an explicit Yes."""
    return ask(parent, title, text) is Answer.YES


def warn(parent: QWidget | None, title: str, text: str) -> None:
    """Show a warning the user can only acknowledge."""
    QMessageBox.warning(parent, title, text)
