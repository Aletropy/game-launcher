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
    except Exception:  # noqa: BLE001 - a test runner must catch everything
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
# artwork service
# --------------------------------------------------------------------------


@test
def artwork_slugs_never_collide() -> None:
    from launcher.services import artwork

    names = [
        "Schedule I",
        "Warhammer 40,000",
        "Warhammer 40 000",
        "Caf\u00e9 Ni\u00f1o",
        "S.T.A.L.K.E.R.",
        "!!!",
        "",
    ]
    slugs = [artwork.slug(n) for n in names]
    assert len(set(slugs)) == len(slugs), dict(zip(names, slugs, strict=True))
    # Plain names stay readable rather than being hashed.
    assert artwork.slug("Schedule I") == "schedule-i"


@test
def artwork_store_shrinks_and_replaces() -> None:
    from PySide6.QtGui import QImage, QImageWriter
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from launcher.services import artwork

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        artwork.ARTWORK_DIR = tmp / "artwork"
        artwork.invalidate()

        # A 600x900 source, the shape SteamGridDB actually serves.
        src = tmp / "src.png"
        image = QImage(600, 900, QImage.Format.Format_RGB32)
        for y in range(900):
            for x in range(0, 600, 4):
                image.setPixel(x, y, (x * 7 + y * 13) & 0xFFFFFF)
        QImageWriter(str(src), b"png").write(image)

        dest = artwork.store("Test Game", artwork.GRID.name, src)
        assert dest.is_file()
        assert dest.stat().st_size < src.stat().st_size, "re-encode did not shrink"

        loaded = QImage(str(dest))
        assert loaded.width() <= artwork.GRID.max_width
        assert loaded.height() <= artwork.GRID.max_height

        # Storing again must not leave a second file under another extension.
        artwork.store("Test Game", artwork.GRID.name, src)
        files = list((artwork.ARTWORK_DIR / artwork.GRID.name).iterdir())
        assert len(files) == 1, files

        assert artwork.remove("Test Game") >= 1
        assert artwork.path_for("Test Game", artwork.GRID.name) is None


@test
def artwork_cache_returns_the_same_pixmap() -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from launcher.services import artwork

    key = "Schedule I"
    if artwork.path_for(key) is None:
        return  # no artwork on disk to exercise
    size = QSize(200, 160)
    first = artwork.pixmap(key, artwork.GRID.name, size, expand=True)
    second = artwork.pixmap(key, artwork.GRID.name, size, expand=True)
    assert first is not None
    assert first is second, "cache miss on an unchanged file"


# --------------------------------------------------------------------------


def main() -> int:
    print(f"\n{_PASSED} passed, {len(_FAILURES)} failed")
    for f in _FAILURES:
        print("\n" + "-" * 60 + "\n" + f)
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
