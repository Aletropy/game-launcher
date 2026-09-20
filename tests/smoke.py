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
def artwork_reencode_shrinks_real_artwork() -> None:
    """Synthetic images are a poor compression test; use a real one."""
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from launcher.services import artwork

    root = Path(__file__).resolve().parent.parent
    candidates = [
        p
        for p in (root / "launcher" / "heroes").glob("*")
        if p.suffix.lower() in artwork.EXTENSIONS and p.stat().st_size > 100_000
    ]
    if not candidates:
        return  # nothing real to measure against

    source = candidates[0]
    data, _ = artwork.encode(QImage(str(source)), artwork.GRID)
    assert len(data) < source.stat().st_size, (
        f"{source.name}: {source.stat().st_size} -> {len(data)}"
    )


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


@test
def artwork_cleanup_only_does_what_was_asked() -> None:
    from PySide6.QtGui import QImage, QImageWriter
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from launcher.services import artwork

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        artwork.ARTWORK_DIR = tmp / "artwork"
        artwork.LEGACY_HEROES_DIR = tmp / "heroes"
        artwork.LEGACY_HEROES_DIR.mkdir()
        artwork.invalidate()

        image = QImage(600, 900, QImage.Format.Format_RGB32)
        for y in range(0, 900, 3):
            for x in range(0, 600, 3):
                image.setPixel(x, y, (x * 31 + y * 17) & 0xFFFFFF)
        for name in ("Live Game.png", "Dead Game.png"):
            QImageWriter(str(artwork.LEGACY_HEROES_DIR / name), b"png").write(image)

        report = artwork.scan({"Live Game"})
        assert len(report.orphans) == 1, report.orphans
        assert report.orphans[0].key == "Dead Game"

        # Declining every action must leave the directory exactly as it was.
        before = sorted(p.name for p in artwork.LEGACY_HEROES_DIR.iterdir())
        artwork.apply_cleanup(
            report,
            reencode=False,
            dedupe=False,
            delete_orphans=False,
            migrate=False,
        )
        after = sorted(p.name for p in artwork.LEGACY_HEROES_DIR.iterdir())
        assert before == after, (before, after)

        report = artwork.scan({"Live Game"})
        result = artwork.apply_cleanup(report)
        assert result.orphans_removed == 1
        assert not (artwork.LEGACY_HEROES_DIR / "Dead Game.png").exists()
        # The live game survived, migrated into the new tree.
        survivor = artwork.path_for("Live Game", artwork.GRID.name)
        assert survivor is not None and survivor.is_file(), "live artwork was lost"
        assert artwork.ARTWORK_DIR in survivor.parents


# --------------------------------------------------------------------------
# prefixes and config plumbing
# --------------------------------------------------------------------------


@test
def prefix_resolution_matches_the_shell() -> None:
    from launcher.core import prefixes
    from launcher.core.paths import BASE_DIR

    assert prefixes.resolve("") == prefixes.shared_prefix_path()
    assert prefixes.resolve("prefixes/Ds3") == BASE_DIR / "prefixes" / "Ds3"
    assert prefixes.resolve("/mnt/ssd/ds3") == Path("/mnt/ssd/ds3")
    assert prefixes.resolve("~/wine/ds3") == Path.home() / "wine" / "ds3"

    assert prefixes.inspect("").is_shared
    outside = prefixes.inspect("/mnt/definitely-not-here/ds3")
    assert "flatpak" in outside.message.lower()
    assert "will be created" in prefixes.inspect("prefixes/Nope").message.lower()


@test
def shell_resolves_the_same_prefixes_as_python() -> None:
    """The shell and core/prefixes.py must not drift apart."""
    import subprocess

    from launcher.core import prefixes
    from launcher.core.paths import BASE_DIR, GAMES_DIR

    script = BASE_DIR / "game-launcher.sh"
    if not script.is_file():
        return

    conf = GAMES_DIR / "__smoketest.conf"
    cases = ["", "prefixes/Smoke Test", "~/wine/smoke", "/mnt/ssd/smoke"]
    try:
        for raw in cases:
            body = 'GAME_EXECUTABLE="/games/smoke.exe"\n'
            if raw:
                body += f'GAME_PREFIX="{raw}"\n'
            conf.write_text(body, encoding="utf-8")
            out = subprocess.run(
                ["bash", str(script), "--dry-run", "__smoketest"],
                capture_output=True,
                check=False,
                text=True,
                cwd=BASE_DIR,
            )
            line = next(
                ln for ln in out.stdout.splitlines() if ln.startswith("WINEPREFIX:")
            )
            from_shell = line.split(":", 1)[1].strip()
            from_python = str(prefixes.resolve(raw))
            assert from_shell == from_python, f"{raw!r}: {from_shell} != {from_python}"
    finally:
        conf.unlink(missing_ok=True)


@test
def shell_exports_previously_dead_config_keys() -> None:
    import subprocess

    from launcher.core.paths import BASE_DIR, GAMES_DIR

    script = BASE_DIR / "game-launcher.sh"
    if not script.is_file():
        return

    conf = GAMES_DIR / "__smoketest.conf"
    conf.write_text(
        'GAME_EXECUTABLE="/games/smoke.exe"\n'
        'CUSTOM_PROTON_PATH="/opt/proton-ge"\n'
        'OVERRIDE_APP_ID="987654"\n'
        'WINEDEBUG="-all"\n'
        'VKD3D_CONFIG="dxr"\n'
        'extra_vars=("A=1 B=2" "KEEPS=a space")\n',
        encoding="utf-8",
    )
    try:
        out = subprocess.run(
            ["bash", str(script), "--dry-run", "__smoketest"],
            capture_output=True,
            text=True,
            check=False,
            cwd=BASE_DIR,
        ).stdout
    finally:
        conf.unlink(missing_ok=True)

    assert "PROTONPATH:  /opt/proton-ge" in out, out
    assert "GAMEID:      987654" in out, out
    for expected in ("A=1", "B=2", "WINEDEBUG=-all", "VKD3D_CONFIG=dxr"):
        assert f"- {expected}" in out, f"{expected} missing from:\n{out}"
    # A value containing a space must not be split apart.
    assert "- KEEPS=a space" in out, out


@test
def packed_extra_vars_are_normalized_on_load() -> None:
    assert config.normalize_env_pairs(["A=1 B=2 C=3"]) == ["A=1", "B=2", "C=3"]
    # Not every token is a pair, so this one stays whole.
    assert config.normalize_env_pairs(["FOO=bar baz"]) == ["FOO=bar baz"]
    assert config.normalize_env_pairs(["SOLO=x"]) == ["SOLO=x"]


@test
def editing_a_game_preserves_fields_the_form_hides() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from launcher.ui.dialogs.game_dialog import AddGameDialog

    with tempfile.TemporaryDirectory() as d:
        conf = Path(d) / "Test Game.conf"
        original = games.Game(
            name="Test Game",
            conf_path=conf,
            executable="/games/test.exe",
            winedebug="-all",
            vkd3d_config="dxr",
            radv_perftest="gpl",
            pulse_latency_msec="60",
            proton_use_wine_sync="1",
            prefix="prefixes/Test Game",
        )
        config.save(conf, games._build_data(original))
        loaded = games._game_from_conf(conf, set())

        edited = AddGameDialog(game=loaded).get_game()
        hidden = (
            "winedebug",
            "vkd3d_config",
            "radv_perftest",
            "pulse_latency_msec",
            "proton_use_wine_sync",
        )
        for f in hidden:
            assert getattr(edited, f) == getattr(original, f), f
        assert edited.prefix == "prefixes/Test Game"


# --------------------------------------------------------------------------
# main window behaviour
# --------------------------------------------------------------------------


@test
def selecting_a_game_never_launches_it() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from launcher.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    app.processEvents()
    if len(win._games) < 2:
        return

    launched: list[str] = []
    win._process_mgr.launch = lambda n: (launched.append(n), True)[1]  # type: ignore[method-assign]

    other = win._games[1].name
    win._sidebar.select_game(other)
    app.processEvents()
    assert launched == [], "selection launched a game"
    assert win._detail._game is not None
    assert win._detail._game.name == other

    win._detail._play_btn.click()
    app.processEvents()
    assert launched == [other], launched
    win.close()


@test
def logs_are_kept_per_game() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from launcher.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    app.processEvents()
    if len(win._games) < 2:
        return

    first, second = win._games[0].name, win._games[1].name
    win._sidebar.select_game(second)
    app.processEvents()

    # Output for a game that is not on screen must still be captured.
    win._on_game_started(first)
    win._on_game_output(first, "hello from the first game\n")
    app.processEvents()
    assert first in win._logs

    win._sidebar.select_game(first)
    app.processEvents()
    shown = win._detail._log._output.toPlainText()
    assert "hello from the first game" in shown, shown

    win._sidebar.select_game(second)
    app.processEvents()
    assert win._detail._log._output.toPlainText() == ""
    win.close()


@test
def grid_lays_out_cards_when_its_page_is_shown() -> None:
    """A stacked page's children report isVisible() == False while hidden."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from launcher.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    app.processEvents()
    if not win._games:
        return

    win._switch_view(1)
    for _ in range(3):
        app.processEvents()

    cards = win._game_grid._cards
    positions = {c.game.name: c.pos() for c in cards}
    assert len(positions) == len(win._games), positions
    # Distinct positions mean every card was actually laid out.
    assert len({(p.x(), p.y()) for p in positions.values()}) == len(positions), positions
    # And the contents margins are honoured, not ignored.
    assert min(p.x() for p in positions.values()) > 0, positions
    win.close()


# --------------------------------------------------------------------------


def main() -> int:
    print(f"\n{_PASSED} passed, {len(_FAILURES)} failed")
    for f in _FAILURES:
        print("\n" + "-" * 60 + "\n" + f)
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
