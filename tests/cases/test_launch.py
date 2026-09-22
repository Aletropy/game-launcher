"""Launch checks, crash assessment and the close decision."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

from launcher.app.launch_checks import check_launch
from launcher.domain.crash_signatures import assess
from launcher.domain.models import Game, GameConfig
from launcher.ui.close_policy import decide
from launcher.ui.tray import TrayController


def register(*, test, qt_app, sandbox, pump):
    @test
    def launch_checks_block_and_warn() -> None:
        with sandbox() as ctx:
            empty = Game(config=GameConfig(name="E"), conf_path=Path("/e.conf"))
            blocks, _ = check_launch(empty, ctx.paths, steam_running=True)
            assert any(b.kind == "missing-executable" for b in blocks)

            missing = Game(
                config=GameConfig(name="M", executable="/nope/x.exe"),
                conf_path=Path("/m.conf"),
            )
            blocks, _ = check_launch(missing, ctx.paths, steam_running=True)
            assert any(b.kind == "missing-executable" for b in blocks)

            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
                exe = tmp.name
            present = Game(
                config=GameConfig(name="P", executable=exe),
                conf_path=Path("/p.conf"),
                executable_exists=True,
            )
            blocks, warnings = check_launch(
                present, ctx.paths, steam_running=False, free_bytes=10**12
            )
            assert not blocks, [b.title for b in blocks]
            assert any(w.kind == "steam-not-running" for w in warnings)
            blocks, _ = check_launch(
                present, ctx.paths, steam_running=True, free_bytes=10
            )
            assert any(b.kind == "no-space" for b in blocks)

    @test
    def crash_assessment_tells_quits_from_crashes() -> None:
        assert not assess("", 0, 3600).crashed
        assert assess("Steam Flatpak is not running.", 1, 2).crashed
        assert assess("", 3, 5).crashed
        assert not assess("", 3, 900).crashed
        assert "Steam" in assess("Steam Flatpak is not running.", 1, 2).summary

    @test
    def close_policy_decides_without_qt() -> None:
        assert decide(True, True, ["X"]).action == "accept"
        assert decide(False, True, ["X"]).action == "hide"
        assert decide(False, False, ["X"]).action == "confirm"
        assert decide(False, False, []).action == "accept"

    @test
    def tray_formats_elapsed_and_starts_idle() -> None:
        assert TrayController.format_elapsed(45) == "45s"
        assert TrayController.format_elapsed(125) == "2m 05s"
        assert TrayController.format_elapsed(3700) == "1h 01m"
        qt_app()
        tray = TrayController(QIcon(), lambda: [], lambda _n: 0)
        assert not tray.active
        tray.sync(False, True)
        assert not tray.active
