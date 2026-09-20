"""Dialog for adding or editing a game configuration."""

from __future__ import annotations

from pathlib import Path

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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from launcher.core.games import Game


class AddGameDialog(QDialog):
    """Form dialog to add or edit a game's .conf configuration."""

    def __init__(self, game: Game | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self._exe_edit.setText(g.executable)
        self._appid_edit.setText(g.game_id)
        self._args_edit.setText(" ".join(g.game_args))
        self._proton_edit.setText(g.custom_proton_path)
        self._dlls_edit.setText(";".join(g.additional_dlls))
        self._gs_check.setChecked(g.use_gamescope)
        self._gsw_edit.setText(g.gamescope_w)
        self._gsh_edit.setText(g.gamescope_h)
        self._gswout_edit.setText(g.gamescope_w_out)
        self._gshout_edit.setText(g.gamescope_h_out)
        self._gsargs_edit.setText(g.gamescope_args)
        self._override_id_edit.setText(g.override_app_id)
        self._extra_vars_edit.setText(";".join(g.extra_vars))

    def _toggle_gamescope(self, checked: bool) -> None:
        self._gs_widget.setVisible(checked)

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Game Executable", "", "Executables (*.exe);;All Files (*)")
        if path:
            self._exe_edit.setText(path)

    def _browse_proton(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Proton Directory")
        if path:
            self._proton_edit.setText(path)

    def _validate_and_accept(self) -> None:
        name = self._name_edit.text().strip()
        exe = self._exe_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation Error", "Game name is required.")
            return
        if not exe:
            QMessageBox.warning(self, "Validation Error", "Executable path is required.")
            return
        if not self.is_edit:
            # Check for duplicate name
            from pathlib import Path
            conf = Path(__file__).resolve().parent.parent.parent / "games" / f"{name}.conf"
            if conf.is_file():
                QMessageBox.warning(self, "Validation Error", f"A game named '{name}' already exists.")
                return

        self.accept()

    def get_game(self) -> Game:
        """Build and return a Game from the form fields."""
        name = self._name_edit.text().strip()
        args_text = self._args_edit.text().strip()
        game_args = args_text.split() if args_text else []

        dlls_text = self._dlls_edit.text().strip()
        additional_dlls = [d.strip() for d in dlls_text.split(";") if d.strip()]

        extra_text = self._extra_vars_edit.text().strip()
        extra_vars = [v.strip() for v in extra_text.split(";") if v.strip()]

        conf_path = Path("") if not self.is_edit or self.game is None else self.game.conf_path

        return Game(
            name=name,
            conf_path=conf_path,
            executable=self._exe_edit.text().strip(),
            game_id=self._appid_edit.text().strip() or "480",
            game_args=game_args,
            custom_proton_path=self._proton_edit.text().strip(),
            additional_dlls=additional_dlls,
            use_gamescope=self._gs_check.isChecked(),
            gamescope_w=self._gsw_edit.text().strip() or "1280",
            gamescope_h=self._gsh_edit.text().strip() or "720",
            gamescope_w_out=self._gswout_edit.text().strip() or "1920",
            gamescope_h_out=self._gshout_edit.text().strip() or "1080",
            gamescope_args=self._gsargs_edit.text().strip() or "-f -e",
            override_app_id=self._override_id_edit.text().strip(),
            extra_vars=extra_vars,
        )
