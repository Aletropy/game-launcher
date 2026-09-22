"""One consistent way to show failures.

Every error dialog offers the same three things: what happened, what to
try next, and action buttons for the useful next steps. Callers pass a
``domain.outcome.Error`` (or plain title/detail strings) plus optional
actions as ``(label, callable)`` pairs rendered as extra buttons.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QWidget,
)

from launcher.domain.outcome import Error


def show_error(
    parent: QWidget | None,
    error: Error | str,
    detail: str = "",
    *,
    hint: str = "",
    actions: Sequence[tuple[str, Callable[[], None]]] = (),
) -> None:
    """Present a failure with hint text and optional action buttons."""
    if isinstance(error, Error):
        title, body, tip = error.title, error.detail, error.hint
    else:
        title, body, tip = error, detail, hint
    text = body + (f"\n\n{tip}" if tip else "")
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text or title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    callbacks = dict(actions)
    for label in callbacks:
        box.addButton(label, QMessageBox.ButtonRole.ActionRole)

    def _on_click(button: object) -> None:
        text_of = getattr(button, "text", lambda: "")()
        callback = callbacks.get(text_of)
        if callback is not None:
            callback()

    box.buttonClicked.connect(_on_click)
    box.exec()


def copy_text(text: str) -> None:
    """Copy text to the clipboard. Best-effort outside a running app."""
    try:
        clipboard = QApplication.clipboard()
    except (AttributeError, RuntimeError):
        return
    if clipboard is not None:
        clipboard.setText(text)
