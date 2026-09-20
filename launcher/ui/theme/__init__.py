"""Design tokens and the generated stylesheet."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from launcher.ui.theme.qss import build_stylesheet
from launcher.ui.theme.tokens import DARK, METRICS, Metrics, Palette

__all__ = [
    "DARK",
    "METRICS",
    "Metrics",
    "Palette",
    "apply_theme",
    "build_stylesheet",
    "restyle",
]


def apply_theme(app: QApplication, palette: Palette = DARK, metrics: Metrics = METRICS) -> None:
    """Apply the stylesheet to the whole application."""
    app.setStyleSheet(build_stylesheet(palette, metrics))


def restyle(widget: QWidget) -> None:
    """Re-evaluate a widget's style after a dynamic property changed.

    Qt does not re-run selectors like ``[favorite="true"]`` on its own.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
