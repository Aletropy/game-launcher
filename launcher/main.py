"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from launcher.ui.main_window import MainWindow
from launcher.ui.styles import DARK_STYLE

_BASE_DIR = Path(__file__).resolve().parent.parent
_ICON_PATH = _BASE_DIR / "icon.png"


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    if _ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))

    window = MainWindow()
    if _ICON_PATH.is_file():
        window.setWindowIcon(QIcon(str(_ICON_PATH)))
    window.show()

    sys.exit(app.exec())
