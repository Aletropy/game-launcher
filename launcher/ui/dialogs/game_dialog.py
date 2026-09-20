"""Dialog for adding or editing a game configuration."""

from __future__ import annotations

import contextlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from launcher.data.paths import Paths
from launcher.domain import prefixes
from launcher.domain.models import Game, GameConfig
from launcher.ui.dialogs.confirm import warn


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
        self.setMinimumWidth(500)
        self.setMinimumHeight(600)
        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(12)

        # Basic info
        basic_group = QGroupBox("Basic Information")
        basic_layout = QVBoxLayout(basic_group)

        basic_layout.addWidget(QLabel("Game Name"))
        self._name_edit = QLineEdit()
        basic_layout.addWidget(self._name_edit)

        exe_row = QHBoxLayout()
        exe_row.addWidget(QLabel("Executable Path"))
        self._exe_edit = QLineEdit()
        self._exe_edit.setPlaceholderText("/path/to/game.exe")
        exe_row.addWidget(self._exe_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_exe)
        exe_row.addWidget(browse_btn)
        basic_layout.addLayout(exe_row)

        basic_layout.addWidget(QLabel("Steam Game ID"))
        self._appid_edit = QLineEdit("480")
        self._appid_edit.setPlaceholderText("480 (default)")
        basic_layout.addWidget(self._appid_edit)

        basic_layout.addWidget(QLabel("Game Arguments (space-separated)"))
        self._args_edit = QLineEdit()
        self._args_edit.setPlaceholderText("-console -windowed")
        basic_layout.addWidget(self._args_edit)

        form_layout.addWidget(basic_group)

        # Proton settings
        proton_group = QGroupBox("Proton Settings")
        proton_layout = QVBoxLayout(proton_group)

        proton_row = QHBoxLayout()
        proton_row.addWidget(QLabel("Custom Proton Path"))
        self._proton_edit = QLineEdit()
        self._proton_edit.setPlaceholderText("/usr/bin/proton-ge (optional)")
        proton_row.addWidget(self._proton_edit)
        proton_browse = QPushButton("Browse")
        proton_browse.setFixedWidth(80)
        proton_browse.clicked.connect(self._browse_proton)
        proton_row.addWidget(proton_browse)
        proton_layout.addLayout(proton_row)

        dll_row = QHBoxLayout()
        dll_row.addWidget(QLabel("Additional DLLs"))
        self._dlls_edit = QLineEdit()
        self._dlls_edit.setPlaceholderText("d3d11=n,b;dxgi=n,b")
        dll_row.addWidget(self._dlls_edit)
        proton_layout.addLayout(dll_row)

        form_layout.addWidget(proton_group)

        # Wine prefix
        prefix_group = QGroupBox("Wine Prefix")
        prefix_layout = QVBoxLayout(prefix_group)

        self._prefix_shared = QRadioButton("Shared prefix")
        self._prefix_custom = QRadioButton("Custom prefix")
        self._prefix_shared.setChecked(True)
        self._prefix_shared.toggled.connect(self._update_prefix_state)
        prefix_layout.addWidget(self._prefix_shared)
        prefix_layout.addWidget(self._prefix_custom)

        prefix_row = QHBoxLayout()
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText(prefixes.suggest("Game"))
        self._prefix_edit.textChanged.connect(self._update_prefix_status)
        prefix_row.addWidget(self._prefix_edit)
        self._prefix_browse = QPushButton("Browse")
        self._prefix_browse.setFixedWidth(80)
        self._prefix_browse.clicked.connect(self._browse_prefix)
        prefix_row.addWidget(self._prefix_browse)
        prefix_layout.addLayout(prefix_row)

        self._prefix_status = QLabel()
        self._prefix_status.setObjectName("hintLabel")
        self._prefix_status.setWordWrap(True)
        prefix_layout.addWidget(self._prefix_status)

        form_layout.addWidget(prefix_group)

        # Gamescope settings
        gs_group = QGroupBox("Gamescope Settings")
        gs_layout = QVBoxLayout(gs_group)

        self._gs_check = QCheckBox("Enable Gamescope")
        self._gs_check.toggled.connect(self._toggle_gamescope)
        gs_layout.addWidget(self._gs_check)

        self._gs_widget = QWidget()
        gs_form = QVBoxLayout(self._gs_widget)
        gs_form.setContentsMargins(0, 0, 0, 0)

        gs_res_row = QHBoxLayout()
        gs_res_row.addWidget(QLabel("Internal Resolution"))
        self._gsw_edit = QLineEdit("1280")
        self._gsw_edit.setMaximumWidth(80)
        gs_res_row.addWidget(self._gsw_edit)
        gs_res_row.addWidget(QLabel("x"))
        self._gsh_edit = QLineEdit("720")
        self._gsh_edit.setMaximumWidth(80)
        gs_res_row.addWidget(self._gsh_edit)
        gs_res_row.addStretch()
        gs_form.addLayout(gs_res_row)

        gs_out_row = QHBoxLayout()
        gs_out_row.addWidget(QLabel("Output Resolution"))
        self._gswout_edit = QLineEdit("1920")
        self._gswout_edit.setMaximumWidth(80)
        gs_out_row.addWidget(self._gswout_edit)
        gs_out_row.addWidget(QLabel("x"))
        self._gshout_edit = QLineEdit("1080")
        self._gshout_edit.setMaximumWidth(80)
        gs_out_row.addWidget(self._gshout_edit)
        gs_out_row.addStretch()
        gs_form.addLayout(gs_out_row)

        gs_form.addWidget(QLabel("Gamescope Args"))
        self._gsargs_edit = QLineEdit("-f -e")
        gs_form.addWidget(self._gsargs_edit)

        gs_layout.addWidget(self._gs_widget)
        self._gs_widget.setVisible(self._gs_check.isChecked())

        form_layout.addWidget(gs_group)

        # Advanced settings
        adv_group = QGroupBox("Advanced Settings (optional)")
        adv_layout = QVBoxLayout(adv_group)

        adv_layout.addWidget(QLabel("Override App ID"))
        self._override_id_edit = QLineEdit()
        adv_layout.addWidget(self._override_id_edit)

        adv_layout.addWidget(QLabel("Extra Env Vars (one per line)"))
        self._extra_vars_edit = QLineEdit()
        self._extra_vars_edit.setPlaceholderText("MY_VAR=value;OTHER=val")
        adv_layout.addWidget(self._extra_vars_edit)

        form_layout.addWidget(adv_group)
        form_layout.addStretch()

        scroll.setWidget(form_widget)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        # Populate fields if editing
        if self.is_edit and self.game:
            self._populate_fields()

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

        if self.is_edit and self.game is not None:
            # replace() on the existing config rather than a fresh one:
            # the form does not expose every field, and rebuilding
            # silently dropped the ones it does not show (winedebug,
            # vkd3d_config and friends).
            return replace(self.game.config, **edited)
        return GameConfig(**edited)
