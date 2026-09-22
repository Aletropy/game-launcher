"""Dialog for adding or editing a game configuration."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from launcher.data.paths import Paths
from launcher.domain import prefixes
from launcher.domain.models import Game, GameConfig
from launcher.ui.dialogs.confirm import warn

#: Config field, label, placeholder for the Proton and driver variables.
_ENV_FIELDS = (
    ("proton_use_wine_sync", "PROTON_USE_WINE_SYNC", "1 to use wine's own sync"),
    ("winedebug", "WINEDEBUG", "-all"),
    ("vkd3d_config", "VKD3D_CONFIG", "dxr"),
    ("radv_perftest", "RADV_PERFTEST", "gpl"),
    ("pulse_latency_msec", "PULSE_LATENCY_MSEC", "60"),
)


class AddGameDialog(QDialog):
    """Form dialog to add or edit a game's .conf configuration."""

    def __init__(
        self,
        paths: Paths,
        game: Game | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self.game = game
        self.is_edit = game is not None
        self.setWindowTitle("Edit Game" if self.is_edit else "Add Game")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 12)
        main_layout.setSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general(), "General")
        self._tabs.addTab(self._build_compatibility(), "Compatibility")
        self._tabs.addTab(self._build_display(), "Display")
        self._tabs.addTab(self._build_advanced(), "Advanced")
        main_layout.addWidget(self._tabs, stretch=1)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton(
            "Save" if self.is_edit else "Add Game", QDialogButtonBox.ButtonRole.AcceptRole
        )
        save.setObjectName("playButton")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        if self.is_edit and self.game:
            self._populate_fields()

    # -- tabs ------------------------------------------------------------

    @staticmethod
    def _page() -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(14, 16, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return page, form

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _with_browse(edit: QLineEdit, handler: Callable[[], None]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(edit, stretch=1)
        button = QPushButton("Browse\u2026")
        button.clicked.connect(handler)
        row.addWidget(button)
        return row

    def _build_general(self) -> QWidget:
        page, form = self._page()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("How it appears in the library")
        form.addRow("Name", self._name_edit)

        self._exe_edit = QLineEdit()
        self._exe_edit.setPlaceholderText("/path/to/game.exe")
        form.addRow("Executable", self._with_browse(self._exe_edit, self._browse_exe))

        self._args_edit = QLineEdit()
        self._args_edit.setPlaceholderText("-console -windowed")
        form.addRow("Arguments", self._args_edit)
        form.addRow(self._hint("Passed to the game, separated by spaces."))

        self._appid_edit = QLineEdit("480")
        self._appid_edit.setPlaceholderText("480")
        form.addRow("Steam App ID", self._appid_edit)
        form.addRow(
            self._hint(
                "Used by Proton for game-specific fixes. 480 (Spacewar) works "
                "for games that are not on Steam."
            )
        )
        return page

    def _build_compatibility(self) -> QWidget:
        page, form = self._page()

        self._proton_edit = QLineEdit()
        self._proton_edit.setPlaceholderText("Default Proton")
        form.addRow("Proton", self._with_browse(self._proton_edit, self._browse_proton))

        self._dlls_edit = QLineEdit()
        self._dlls_edit.setPlaceholderText("d3d11=n,b;dxgi=n,b")
        form.addRow("DLL overrides", self._dlls_edit)

        prefix_box = QWidget()
        prefix_layout = QVBoxLayout(prefix_box)
        prefix_layout.setContentsMargins(0, 0, 0, 0)
        prefix_layout.setSpacing(6)
        choice = QHBoxLayout()
        self._prefix_shared = QRadioButton("Shared")
        self._prefix_custom = QRadioButton("Its own")
        self._prefix_shared.setChecked(True)
        self._prefix_shared.toggled.connect(self._update_prefix_state)
        choice.addWidget(self._prefix_shared)
        choice.addWidget(self._prefix_custom)
        choice.addStretch()
        prefix_layout.addLayout(choice)

        prefix_row = QHBoxLayout()
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText(prefixes.suggest("Game"))
        self._prefix_edit.textChanged.connect(self._update_prefix_status)
        prefix_row.addWidget(self._prefix_edit, stretch=1)
        self._prefix_browse = QPushButton("Browse\u2026")
        self._prefix_browse.clicked.connect(self._browse_prefix)
        prefix_row.addWidget(self._prefix_browse)
        prefix_layout.addLayout(prefix_row)

        self._prefix_status = self._hint("")
        prefix_layout.addWidget(self._prefix_status)
        form.addRow("Wine prefix", prefix_box)
        return page

    def _build_display(self) -> QWidget:
        page, form = self._page()
        self._gs_check = QCheckBox("Run inside Gamescope")
        self._gs_check.toggled.connect(self._toggle_gamescope)
        form.addRow(self._gs_check)

        self._gs_widget = QWidget()
        gs_form = QFormLayout(self._gs_widget)
        gs_form.setContentsMargins(0, 0, 0, 0)
        gs_form.setSpacing(10)

        def resolution(w: str, h: str) -> tuple[QHBoxLayout, QLineEdit, QLineEdit]:
            row = QHBoxLayout()
            width, height = QLineEdit(w), QLineEdit(h)
            for edit in (width, height):
                edit.setMaximumWidth(90)
            row.addWidget(width)
            row.addWidget(QLabel("\u00d7"))
            row.addWidget(height)
            row.addStretch()
            return row, width, height

        row, self._gsw_edit, self._gsh_edit = resolution("1280", "720")
        gs_form.addRow("Game renders at", row)
        row, self._gswout_edit, self._gshout_edit = resolution("1920", "1080")
        gs_form.addRow("Shown at", row)
        self._gsargs_edit = QLineEdit("-f -e")
        gs_form.addRow("Extra arguments", self._gsargs_edit)
        form.addRow(self._gs_widget)
        form.addRow(
            self._hint(
                "Gamescope renders the game at one resolution and scales it to "
                "another, e.g. for older games or FSR upscaling."
            )
        )
        self._gs_widget.setVisible(self._gs_check.isChecked())
        return page

    def _build_advanced(self) -> QWidget:
        page, form = self._page()
        self._override_id_edit = QLineEdit()
        self._override_id_edit.setPlaceholderText("Same as the Steam App ID")
        form.addRow("Override App ID", self._override_id_edit)

        self._extra_vars_edit = QLineEdit()
        self._extra_vars_edit.setPlaceholderText("MY_VAR=value;OTHER=val")
        form.addRow("Environment", self._extra_vars_edit)
        form.addRow(self._hint("Extra variables, separated by semicolons."))

        section = QLabel("Proton and driver options")
        section.setObjectName("sectionTitle")
        form.addRow(section)
        self._env_edits: dict[str, QLineEdit] = {}
        for field, label, placeholder in _ENV_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            form.addRow(label, edit)
            self._env_edits[field] = edit
        form.addRow(self._hint("Leave blank to use the defaults."))
        return page

    def _populate_fields(self) -> None:
        if self.game is None:
            return
        g = self.game
        self._name_edit.setText(g.name)
        self._exe_edit.setText(g.config.executable)
        self._appid_edit.setText(g.config.game_id)
        self._args_edit.setText(" ".join(g.config.game_args))
        self._proton_edit.setText(g.config.custom_proton_path)
        self._dlls_edit.setText(";".join(g.config.additional_dlls))
        self._gs_check.setChecked(g.config.use_gamescope)
        self._gsw_edit.setText(g.config.gamescope_w)
        self._gsh_edit.setText(g.config.gamescope_h)
        self._gswout_edit.setText(g.config.gamescope_w_out)
        self._gshout_edit.setText(g.config.gamescope_h_out)
        self._gsargs_edit.setText(g.config.gamescope_args)
        self._override_id_edit.setText(g.config.override_app_id)
        self._extra_vars_edit.setText(";".join(g.config.extra_vars))
        for field, edit in self._env_edits.items():
            edit.setText(str(getattr(g.config, field)))
        if g.config.prefix:
            self._prefix_custom.setChecked(True)
            self._prefix_edit.setText(g.config.prefix)
        else:
            self._prefix_shared.setChecked(True)
        self._update_prefix_state()

    def _toggle_gamescope(self, checked: bool) -> None:
        self._gs_widget.setVisible(checked)

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Game Executable",
            self._paths.base.as_posix(),
            "Executables (*.exe);;All Files (*)",
        )
        if path:
            self._exe_edit.setText(path)

    def _update_prefix_state(self) -> None:
        custom = self._prefix_custom.isChecked()
        self._prefix_edit.setEnabled(custom)
        self._prefix_browse.setEnabled(custom)
        if custom and not self._prefix_edit.text().strip():
            name = self._name_edit.text().strip()
            if name:
                self._prefix_edit.setText(prefixes.suggest(name))
        self._update_prefix_status()

    def _update_prefix_status(self) -> None:
        raw = self._prefix_edit.text().strip() if self._prefix_custom.isChecked() else ""
        info = prefixes.inspect(raw, self._paths)
        self._prefix_status.setText(info.message)

    def _browse_prefix(self) -> None:
        start = self._prefix_edit.text().strip()
        base = str(
            prefixes.resolve(start, self._paths).parent
            if start
            else self._paths.prefixes_dir
        )
        path = QFileDialog.getExistingDirectory(self, "Select Prefix Folder", base)
        if not path:
            return
        chosen = Path(path)
        # Keep it relative when it lives under the launcher, so the
        # config stays portable.
        with contextlib.suppress(ValueError):
            chosen = chosen.relative_to(self._paths.base)
        self._prefix_edit.setText(str(chosen))

    def _browse_proton(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Proton Directory")
        if path:
            self._proton_edit.setText(path)

    def _validate_and_accept(self) -> None:
        name = self._name_edit.text().strip()
        exe = self._exe_edit.text().strip()

        if not name:
            warn(self, "Validation Error", "Game name is required.")
            return
        if not exe:
            warn(self, "Validation Error", "Executable path is required.")
            return
        if not self.is_edit:
            conf = self._paths.games_dir / f"{name}.conf"
            if conf.is_file():
                warn(self, "Validation Error", f"A game named '{name}' already exists.")
                return

        self.accept()

    def get_config(self) -> GameConfig:
        """Build a GameConfig from the form fields."""
        name = self._name_edit.text().strip()
        args_text = self._args_edit.text().strip()
        game_args = args_text.split() if args_text else []

        dlls_text = self._dlls_edit.text().strip()
        additional_dlls = [d.strip() for d in dlls_text.split(";") if d.strip()]

        extra_text = self._extra_vars_edit.text().strip()
        extra_vars = [v.strip() for v in extra_text.split(";") if v.strip()]

        prefix = (
            self._prefix_edit.text().strip() if self._prefix_custom.isChecked() else ""
        )

        edited: dict[str, Any] = {
            "name": name,
            "executable": self._exe_edit.text().strip(),
            "game_id": self._appid_edit.text().strip() or "480",
            "game_args": game_args,
            "custom_proton_path": self._proton_edit.text().strip(),
            "additional_dlls": additional_dlls,
            "use_gamescope": self._gs_check.isChecked(),
            "gamescope_w": self._gsw_edit.text().strip() or "1280",
            "gamescope_h": self._gsh_edit.text().strip() or "720",
            "gamescope_w_out": self._gswout_edit.text().strip() or "1920",
            "gamescope_h_out": self._gshout_edit.text().strip() or "1080",
            "gamescope_args": self._gsargs_edit.text().strip() or "-f -e",
            "override_app_id": self._override_id_edit.text().strip(),
            "prefix": prefix,
            "extra_vars": extra_vars,
        }
        edited.update(
            {field: edit.text().strip() for field, edit in self._env_edits.items()}
        )

        if self.is_edit and self.game is not None:
            # replace() on the existing config rather than a fresh one:
            # the form does not expose every field, and rebuilding
            # silently dropped the ones it does not show (winedebug,
            # vkd3d_config and friends).
            return replace(self.game.config, **edited)
        return GameConfig(**edited)
