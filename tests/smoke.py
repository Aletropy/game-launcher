#!/usr/bin/env python3
"""Smoke tests for the launcher.

Run with: QT_QPA_PLATFORM=offscreen .venv/bin/python tests/smoke.py

Deliberately dependency-free (no pytest) and safe to run against the real
project: every test that writes does so in a temporary directory.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_FAILURES: list[str] = []
_PASSED = 0


def test(fn):
    """Register and immediately run a test function."""
    global _PASSED
    try:
        fn()
    except Exception:
        _FAILURES.append(f"{fn.__name__}\n{traceback.format_exc()}")
        print(f"  FAIL  {fn.__name__}")
    else:
        _PASSED += 1
        print(f"  ok    {fn.__name__}")
    return fn


def _import(*names: str):
    """Import the first module path that exists, so tests survive the move."""
    last: Exception | None = None
    for name in names:
        try:
            mod = __import__(name, fromlist=["*"])
        except ImportError as e:
            last = e
            continue
        return mod
    raise AssertionError(f"none of {names} importable: {last}")


config = _import("launcher.core.config", "launcher.config_parser")
games = _import("launcher.core.games", "launcher.game_manager")


# --------------------------------------------------------------------------
# config round-trip
# --------------------------------------------------------------------------


@test
def conf_round_trip_preserves_values() -> None:
    values = {
        "GAME_EXECUTABLE": "/home/g/Games/Rock & Roll/x.exe",
        "GAME_NAME": "Rock & Roll",
        "GAME_ARGS": ["-console", "-w 1920"],
        "ADDITIONAL_DLLS": ["winhttp=n,b"],
    }
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.conf"
        config.save(p, values)
        assert config.load(p) == values, config.load(p)


@test
def conf_escapes_shell_metacharacters() -> None:
    evil = '$(touch /tmp/pwned) `id` " \\ $HOME'
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.conf"
        config.save(p, {"EVIL": evil})
        assert config.load(p)["EVIL"] == evil
        raw = p.read_text()
        for ch in ("$", "`", '"'):
            assert f"\\{ch}" in raw, f"{ch} not escaped in {raw!r}"


@test
def conf_sourced_by_bash_yields_original_values() -> None:
    import subprocess

    values = {
        "GAME_EXECUTABLE": '/games/Rock & Roll "Deluxe"/x.exe',
        "GAME_ARGS": ["-w \"1920\"", "$(id)"],
    }
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.conf"
        config.save(p, values)
        script = (
            f'source "{p}"\n'
            'printf "%s\\n" "$GAME_EXECUTABLE"\n'
            'printf "%s\\n" "${GAME_ARGS[@]}"\n'
        )
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        )
        expected = [values["GAME_EXECUTABLE"], *values["GAME_ARGS"]]
        assert out.stdout.splitlines() == expected, out.stdout


@test
def real_project_confs_still_parse() -> None:
    root = Path(__file__).resolve().parent.parent
    confs = list((root / "games").glob("*.conf"))
    assert confs, "no game confs found"
    for conf in confs:
        data = config.load(conf)
        assert data.get("GAME_EXECUTABLE"), f"{conf.name} has no executable"


# --------------------------------------------------------------------------
# game model
# --------------------------------------------------------------------------


@test
def scan_games_returns_known_games() -> None:
    found = {g.name for g in games.scan_games()}
    assert "Schedule I" in found, found


@test
def game_fields_round_trip_through_conf() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Test Game.conf"
        game = games.Game(
            name="Test Game",
            conf_path=p,
            executable="/games/test.exe",
            winedebug="-all",
            vkd3d_config="dxr",
            extra_vars=["FOO=bar"],
        )
        config.save(p, games._build_data(game))
        back = games._game_from_conf(p, set())
        for field in ("executable", "winedebug", "vkd3d_config", "extra_vars"):
            assert getattr(back, field) == getattr(game, field), field


# --------------------------------------------------------------------------
# Qt / UI construction
# --------------------------------------------------------------------------


@test
def main_window_constructs_headless() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window_mod = _import("launcher.ui.main_window")
    win = window_mod.MainWindow()
    win.show()
    app.processEvents()
    assert win.isVisible()
    win.close()


@test
def stylesheet_is_non_empty() -> None:
    try:
        from launcher.ui.theme.qss import build_stylesheet

        sheet = build_stylesheet()
    except ImportError:
        from launcher.ui.styles import DARK_STYLE

        sheet = DARK_STYLE
    assert "QMainWindow" in sheet and len(sheet) > 500


@test
def qt_can_write_the_artwork_formats() -> None:
    from PySide6.QtGui import QImageWriter

    supported = {bytes(f).decode() for f in QImageWriter.supportedImageFormats()}
    for fmt in ("png", "jpg", "webp"):
        assert fmt in supported, f"{fmt} unsupported; artwork re-encode would fail"


# --------------------------------------------------------------------------


def main() -> int:
    print(f"\n{_PASSED} passed, {len(_FAILURES)} failed")
    for f in _FAILURES:
        print("\n" + "-" * 60 + "\n" + f)
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
