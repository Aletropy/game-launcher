"""Dark theme QSS styles for the game launcher."""

DARK_STYLE = """
QMainWindow {
    background-color: #0d1117;
}

QTabWidget::pane {
    border: 1px solid #30363d;
    background-color: #0d1117;
}

QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    padding: 8px 20px;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #0d1117;
    color: #e6edf3;
    border-bottom: 2px solid #238636;
}

QTabBar::tab:hover:!selected {
    background-color: #1c2128;
    color: #c9d1d9;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: #161b22;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #30363d;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #484f58;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QLineEdit, QSpinBox, QComboBox {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #238636;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    selection-background-color: #238636;
}

QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #484f58;
}

QPushButton:pressed {
    background-color: #282e33;
}

QPushButton#playButton {
    background-color: #238636;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#playButton:hover {
    background-color: #2ea043;
}

QPushButton#playButton:pressed {
    background-color: #1a7f37;
}

QPushButton#playButton:disabled {
    background-color: #21262d;
    color: #484f58;
}

QPushButton#favButton {
    background: transparent;
    border: none;
    font-size: 18px;
    padding: 2px;
}

QPushButton#favButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
    border-radius: 4px;
}

QLabel {
    color: #e6edf3;
}

QLabel#gameNameLabel {
    font-size: 13px;
    font-weight: bold;
    color: #e6edf3;
}

QLabel#subtitleLabel {
    font-size: 11px;
    color: #8b949e;
}

QLabel#placeholderLabel {
    font-size: 32px;
    font-weight: bold;
    color: #58a6ff;
}

QLabel#emptyLabel {
    font-size: 14px;
    color: #8b949e;
}

QFrame#gameCard {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
}

QFrame#gameCard:hover {
    border-color: #58a6ff;
}

QPlainTextEdit {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    font-family: 'Monospace', 'Courier New', monospace;
    font-size: 12px;
    padding: 6px;
}

QCheckBox {
    color: #c9d1d9;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background-color: #161b22;
}

QCheckBox::indicator:checked {
    background-color: #238636;
    border-color: #238636;
}

QGroupBox {
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

QDialog {
    background-color: #0d1117;
}
"""
