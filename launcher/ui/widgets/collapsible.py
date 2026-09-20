"""A section with a header that folds its content away."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A titled section whose body can be hidden."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        expanded: bool = True,
    ) -> None:
        super().__init__(parent)
        self._title = title

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._toggle = QToolButton()
        self._toggle.setObjectName("sectionToggle")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setText(title)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(self._arrow(expanded))
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body.setVisible(expanded)
        layout.addWidget(self._body)

    @staticmethod
    def _arrow(expanded: bool) -> Qt.ArrowType:
        return Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow

    def _on_toggled(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._toggle.setArrowType(self._arrow(checked))

    def set_content(self, widget: QWidget) -> None:
        """Put a widget inside the section."""
        self._body_layout.addWidget(widget)

    def set_suffix(self, text: str) -> None:
        """Extra detail shown beside the title, e.g. a running indicator."""
        self._toggle.setText(f"{self._title}{text}")

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)
