"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from launcher.core.paths import ICON_PATH
from launcher.ui.main_window import MainWindow
from launcher.ui.styles import DARK_STYLE


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    window = MainWindow()
    if ICON_PATH.is_file():
        window.setWindowIcon(QIcon(str(ICON_PATH)))
    window.show()

    sys.exit(app.exec())
