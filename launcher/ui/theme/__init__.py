"""Design tokens, themes and the generated stylesheet."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from launcher.ui.theme import appearance
from launcher.ui.theme.appearance import Appearance, metrics, notifier, palette
from launcher.ui.theme.qss import build_stylesheet
from launcher.ui.theme.themes import ACCENTS, THEMES, Theme
from launcher.ui.theme.tokens import DARK, METRICS, Metrics, Palette

__all__ = [
    "ACCENTS",
    "DARK",
    "METRICS",
    "THEMES",
    "Appearance",
    "Metrics",
    "Palette",
    "Theme",
    "apply_theme",
    "build_stylesheet",
    "metrics",
    "notifier",
    "palette",
    "restyle",
]


def apply_theme(app: QApplication, look: Appearance | None = None) -> None:
    """Apply an appearance (default: the current one) to the application."""
    appearance.apply(app, look)


def restyle(widget: QWidget) -> None:
    """Re-evaluate a widget's style after a dynamic property changed.

    Qt does not re-run selectors like ``[favorite="true"]`` on its own.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
