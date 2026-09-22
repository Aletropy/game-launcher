#!/usr/bin/env python3
"""Smoke tests for the launcher.

Run with: .venv/bin/python tests/smoke.py

Dependency-free (no pytest). Every test that writes builds its own
AppContext under a temporary directory, so nothing here can touch the
real library.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
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


def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@contextmanager
def sandbox():
    """An AppContext isolated under a temporary directory."""
    from launcher.app.context import AppContext

    qt_app()
    with tempfile.TemporaryDirectory() as directory:
        context = AppContext.for_testing(Path(directory))
        try:
            yield context
        finally:
            context.close()


#: Qt objects that must outlive the widgets pointing at them.
_KEEP_ALIVE: list[object] = []


def _single_click_style():
    """A style whose item views activate on a single click.

    KDE's default. Without forcing it, a test running under Fusion
    cannot reproduce the single-click-launch bug at all.

    Built with no base style on purpose: QProxyStyle takes ownership of
    whatever it is given, and handing it the application's shared style
    makes Qt delete that style on teardown.
    """
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class Proxy(QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, data=None):
            if hint == QStyle.StyleHint.SH_ItemView_ActivateItemOnSingleClick:
                return 1
            return super().styleHint(hint, option, widget, data)

    return Proxy()


def pump(predicate, timeout: float = 5.0) -> None:
    app = qt_app()
    start = time.time()
    while not predicate() and time.time() - start < timeout:
        app.processEvents()
        time.sleep(0.01)


# --------------------------------------------------------------------------
# domain: config parsing
# --------------------------------------------------------------------------


@test
def conf_round_trip_preserves_values() -> None:
    from launcher.domain import config

    values = {
        "GAME_EXECUTABLE": "/home/g/Games/Rock & Roll/x.exe",
        "GAME_NAME": "Rock & Roll",
        "GAME_ARGS": ["-console", "-w 1920"],
        "ADDITIONAL_DLLS": ["winhttp=n,b"],
    }
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.conf"
        config.save(path, values)
        assert config.load(path) == values, config.load(path)


@test
def conf_sourced_by_bash_yields_original_values() -> None:
    import subprocess

    from launcher.domain import config

    values = {
        "GAME_EXECUTABLE": '/games/Rock & Roll "Deluxe"/x.exe',
        "GAME_ARGS": ['-w "1920"', "$(id)"],
    }
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.conf"
        config.save(path, values)
        script = (
            f'source "{path}"\n'
            'printf "%s\\n" "$GAME_EXECUTABLE"\n'
            'printf "%s\\n" "${GAME_ARGS[@]}"\n'
        )
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        )
        assert out.stdout.splitlines() == [
            values["GAME_EXECUTABLE"],
            *values["GAME_ARGS"],
        ], out.stdout


@test
def packed_extra_vars_are_normalized_on_load() -> None:
    from launcher.domain.config import normalize_env_pairs

    assert normalize_env_pairs(["A=1 B=2 C=3"]) == ["A=1", "B=2", "C=3"]
    # Not every token is a pair, so this one stays whole.
    assert normalize_env_pairs(["FOO=bar baz"]) == ["FOO=bar baz"]


@test
def real_project_confs_still_parse() -> None:
    from launcher.domain import config

    root = Path(__file__).resolve().parent.parent
    confs = list((root / "games").glob("*.conf"))
    if not confs:
        return
    for conf in confs:
        assert config.load(conf).get("GAME_EXECUTABLE"), conf.name


# --------------------------------------------------------------------------
# domain: models
# --------------------------------------------------------------------------


@test
def sorting_orders_the_library_as_advertised() -> None:
    from launcher.domain.models import (
        Game,
        GameConfig,
        GameStats,
        SortOrder,
        sort_games,
    )

    now = datetime.now()

    def make(name, playtime=0, last=None, added=None):
        return Game(
            config=GameConfig(name=name),
            conf_path=Path(f"/{name}.conf"),
            stats=GameStats(playtime_seconds=playtime, last_played=last, added=added),
        )

    games = [
        make("Celeste", 100, now - timedelta(days=10), now - timedelta(days=30)),
        make("Balatro", 9000, now, now - timedelta(days=1)),
        make("Anno", 0, None, now - timedelta(days=90)),
    ]

    assert [g.name for g in sort_games(games, SortOrder.NAME)] == [
        "Anno",
        "Balatro",
        "Celeste",
    ]
    assert [g.name for g in sort_games(games, SortOrder.PLAYTIME)][0] == "Balatro"
    assert [g.name for g in sort_games(games, SortOrder.LAST_PLAYED)][0] == "Balatro"
    # Never played sorts last rather than mixing in with the zeros.
    assert [g.name for g in sort_games(games, SortOrder.LAST_PLAYED)][-1] == "Anno"
    assert [g.name for g in sort_games(games, SortOrder.RECENTLY_ADDED)][0] == "Balatro"


@test
def playtime_and_last_played_read_naturally() -> None:
    from launcher.domain.models import format_last_played, format_playtime

    assert format_playtime(0) == ""
    assert format_playtime(45) == "45s"
    assert format_playtime(600) == "10m"
    assert format_playtime(3600 * 12 + 1440) == "12.4h"

    now = datetime(2026, 9, 20, 12, 0)
    cases = {
        0: "today",
        1: "yesterday",
        3: "3 days ago",
        7: "last week",
        14: "2 weeks ago",
        31: "last month",
        90: "3 months ago",
        400: "last year",
    }
    for days, expected in cases.items():
        got = format_last_played(now - timedelta(days=days), now=now)
        assert got == expected, f"{days}d -> {got!r}, expected {expected!r}"
    assert format_last_played(None) == ""


# --------------------------------------------------------------------------
# data: repository and state
# --------------------------------------------------------------------------


@test
def repository_round_trips_every_config_field() -> None:
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        original = GameConfig(
            name="Test Game",
            executable="/games/test.exe",
            game_args=["-console"],
            additional_dlls=["winhttp=n,b"],
            use_gamescope=True,
            gamescope_w="1920",
            prefix="prefixes/Test Game",
            extra_vars=["FOO=bar"],
            winedebug="-all",
            vkd3d_config="dxr",
        )
        ctx.games.add(original)
        loaded = ctx.games.get("Test Game")
        assert loaded is not None
        for field in (
            "executable",
            "game_args",
            "additional_dlls",
            "use_gamescope",
            "gamescope_w",
            "prefix",
            "extra_vars",
            "winedebug",
            "vkd3d_config",
        ):
            assert getattr(loaded.config, field) == getattr(original, field), field


@test
def state_survives_a_rename_and_dies_with_the_game() -> None:
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        ctx.games.add(GameConfig(name="Ds3", executable="/g/ds3.exe"))
        ctx.state.set_favorite("Ds3", True)
        ctx.state.add_playtime("Ds3", 7200)

        ctx.games.rename("Ds3", "Dark Souls III")
        moved = ctx.games.get("Dark Souls III")
        assert moved is not None
        assert moved.is_favorite and moved.playtime_seconds == 7200
        assert ctx.games.get("Ds3") is None

        ctx.games.remove("Dark Souls III")
        assert ctx.state.all_stats() == {}


@test
def legacy_favorites_migrate_exactly_once() -> None:
    from launcher.data.state_store import StateStore

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        legacy = root / "favorites.json"
        legacy.write_text('["Celeste", "Hades"]')

        store = StateStore(root / "state.db")
        assert store.import_legacy_favorites(legacy) == 2
        # Re-running must not resurrect a favourite the user has removed.
        store.set_favorite("Celeste", False)
        assert store.import_legacy_favorites(legacy) == 0
        assert store.get("Celeste").favorite is False
        store.close()


@test
def settings_persist_and_announce_changes() -> None:
    from launcher.data.settings_store import SettingsStore

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.json"
        store = SettingsStore(path)
        seen: list[tuple[str, object]] = []
        store.changed.connect(lambda k, v: seen.append((k, v)))

        store.set("log_max_lines", 1234)
        assert seen == [("log_max_lines", 1234)]
        # Setting the same value again is not a change.
        store.set("log_max_lines", 1234)
        assert len(seen) == 1

        assert SettingsStore(path).get_int("log_max_lines") == 1234
        # Unknown keys fall back to the shipped default.
        assert store.get_bool("confirm_remove") is True


# --------------------------------------------------------------------------
# domain: prefixes, and the shell that must agree with them
# --------------------------------------------------------------------------


@test
def prefix_resolution_matches_the_shell() -> None:
    import subprocess

    from launcher.data.paths import Paths
    from launcher.domain import prefixes

    paths = Paths.default()
    script = paths.launcher_script
    if not script.is_file():
        return

    conf = paths.games_dir / "__smoketest.conf"
    try:
        for raw in ("", "prefixes/Smoke Test", "~/wine/smoke", "/mnt/ssd/smoke"):
            body = 'GAME_EXECUTABLE="/games/smoke.exe"\n'
            if raw:
                body += f'GAME_PREFIX="{raw}"\n'
            conf.write_text(body, encoding="utf-8")
            out = subprocess.run(
                ["bash", str(script), "--dry-run", "__smoketest"],
                capture_output=True,
                text=True,
                check=False,
                cwd=paths.base,
            ).stdout
            line = next(
                ln for ln in out.splitlines() if ln.startswith("WINEPREFIX:")
            )
            from_shell = line.split(":", 1)[1].strip()
            from_python = str(prefixes.resolve(raw, paths))
            assert from_shell == from_python, f"{raw!r}: {from_shell} != {from_python}"
    finally:
        conf.unlink(missing_ok=True)


@test
def shell_exports_previously_dead_config_keys() -> None:
    import subprocess

    from launcher.data.paths import Paths

    paths = Paths.default()
    script = paths.launcher_script
    if not script.is_file():
        return

    conf = paths.games_dir / "__smoketest.conf"
    conf.write_text(
        'GAME_EXECUTABLE="/games/smoke.exe"\n'
        'CUSTOM_PROTON_PATH="/opt/proton-ge"\n'
        'OVERRIDE_APP_ID="987654"\n'
        'WINEDEBUG="-all"\n'
        'extra_vars=("A=1 B=2" "KEEPS=a space")\n',
        encoding="utf-8",
    )
    try:
        out = subprocess.run(
            ["bash", str(script), "--dry-run", "__smoketest"],
            capture_output=True,
            text=True,
            check=False,
            cwd=paths.base,
        ).stdout
    finally:
        conf.unlink(missing_ok=True)

    assert "PROTONPATH:  /opt/proton-ge" in out, out
    assert "GAMEID:      987654" in out, out
    for expected in ("A=1", "B=2", "WINEDEBUG=-all"):
        assert f"- {expected}" in out, f"{expected} missing from:\n{out}"
    assert "- KEEPS=a space" in out, out


@test
def prefix_inspection_warns_about_the_sandbox() -> None:
    from launcher.data.paths import Paths
    from launcher.domain import prefixes

    paths = Paths.default()
    assert prefixes.inspect("", paths).is_shared
    assert "flatpak" in prefixes.inspect("/mnt/nope/x", paths).message.lower()
    assert "will be created" in prefixes.inspect("prefixes/Nope", paths).message.lower()


# --------------------------------------------------------------------------
# services: artwork
# --------------------------------------------------------------------------


@test
def artwork_slugs_never_collide() -> None:
    from launcher.services.artwork import slug

    names = [
        "Schedule I",
        "Warhammer 40,000",
        "Warhammer 40 000",
        "Café Niño",
        "S.T.A.L.K.E.R.",
        "!!!",
        "",
    ]
    slugs = [slug(n) for n in names]
    assert len(set(slugs)) == len(slugs), dict(zip(names, slugs, strict=True))
    assert slug("Schedule I") == "schedule-i"


def _sample_image(width: int = 600, height: int = 900):
    from PySide6.QtGui import QImage

    qt_app()
    image = QImage(width, height, QImage.Format.Format_RGB32)
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            image.setPixel(x, y, (x * 31 + y * 17) & 0xFFFFFF)
    return image


@test
def artwork_store_caps_size_and_replaces_siblings() -> None:
    from PySide6.QtGui import QImage

    from launcher.services.artwork import GRID

    with sandbox() as ctx:
        dest = ctx.artwork.store("Test Game", GRID.name, _sample_image())
        assert dest.is_file()

        loaded = QImage(str(dest))
        assert loaded.width() <= GRID.max_width
        assert loaded.height() <= GRID.max_height

        ctx.artwork.store("Test Game", GRID.name, _sample_image())
        files = list(ctx.artwork.art_dir(GRID.name).iterdir())
        assert len(files) == 1, files

        assert ctx.artwork.remove("Test Game") >= 1
        assert ctx.artwork.path_for("Test Game", GRID.name) is None


@test
def artwork_reencode_shrinks_real_artwork() -> None:
    """Synthetic images compress oddly; measure against a real one.

    Only art larger than the cover box counts: art already at its native
    size has nothing to shed.
    """
    from PySide6.QtGui import QImage, QImageReader

    from launcher.services.artwork import EXTENSIONS, GRID, encode

    qt_app()
    root = Path(__file__).resolve().parent.parent / "launcher"
    candidates = [
        p
        for folder in (root / "heroes", root / "artwork" / "grid")
        if folder.is_dir()
        for p in folder.iterdir()
        if p.suffix.lower() in EXTENSIONS
        and p.stat().st_size > 100_000
        and QImageReader(str(p)).size().height() > GRID.max_height
    ]
    if not candidates:
        return
    source = candidates[0]
    data, _ = encode(QImage(str(source)), GRID)
    assert len(data) < source.stat().st_size, source.name


@test
def artwork_cache_returns_the_same_pixmap() -> None:
    from PySide6.QtCore import QSize

    from launcher.services.artwork import GRID

    with sandbox() as ctx:
        ctx.artwork.store("Cached", GRID.name, _sample_image())
        size = QSize(200, 160)
        first = ctx.artwork.pixmap("Cached", GRID.name, size, expand=True)
        second = ctx.artwork.pixmap("Cached", GRID.name, size, expand=True)
        assert first is not None
        assert first is second, "cache miss on an unchanged file"


@test
def banner_searches_ask_the_api_for_banners() -> None:
    """Regression: "Heroes".lower().rstrip("s") is "heroe", not "hero".

    Choosing Heroes therefore searched covers while the download was
    saved as a banner, so portrait art got cropped into a thin strip and
    stretched - the blurry, badly fitting banner.
    """
    from launcher.services.sgdb import ENDPOINTS, ArtQuery
    from launcher.ui.dialogs.artwork_wizard import ART_STEPS

    titles = {step.title: step.art for step in ART_STEPS}
    assert titles["Banner"] == "hero"
    assert titles["Cover"] == "grid"
    assert set(titles.values()) == set(ENDPOINTS), "every type needs an endpoint"
    assert ENDPOINTS["hero"] == "heroes"
    assert "dimensions" in ArtQuery("grid").params(), "covers must be portrait"
    assert "dimensions" not in ArtQuery("hero").params()
    assert ArtQuery("hero", style="white_logo").params().get("styles") is None


@test
def artwork_is_filed_by_its_real_shape() -> None:
    from PySide6.QtGui import QImage

    from launcher.services.artwork import GRID, HERO, classify

    assert classify(1920, 620, HERO.name) == HERO.name
    assert classify(600, 900, HERO.name) == GRID.name, "a cover is not a banner"
    assert classify(1024, 1024, HERO.name) == GRID.name
    assert classify(1920, 620, GRID.name) == HERO.name

    with sandbox() as ctx:
        cover = QImage(600, 900, QImage.Format.Format_RGB32)
        cover.fill(0x335577)
        stored = ctx.artwork.store("Game", HERO.name, cover)
        assert stored.parent.name == GRID.name, "portrait saved into the banner slot"


@test
def covers_misfiled_as_banners_are_moved_back() -> None:
    from PySide6.QtGui import QImage, QImageWriter

    from launcher.services.artwork import GRID, HERO

    with sandbox() as ctx:
        hero_dir = ctx.artwork.art_dir(HERO.name)
        hero_dir.mkdir(parents=True)
        portrait = QImage(266, 400, QImage.Format.Format_RGB32)
        portrait.fill(0x223344)
        QImageWriter(str(hero_dir / "nightreign.png"), b"png").write(portrait)
        wide = QImage(1920, 620, QImage.Format.Format_RGB32)
        wide.fill(0x445566)
        QImageWriter(str(hero_dir / "real-banner.webp"), b"webp").write(wide)

        moved = ctx.artwork.reclassify_misfiled()
        assert [t.parent.name for _, t in moved] == [GRID.name], moved
        assert (ctx.artwork.art_dir(GRID.name) / "nightreign.png").is_file()
        assert (hero_dir / "real-banner.webp").is_file(), "a real banner was moved"


@test
def stored_art_keeps_native_resolution() -> None:
    """The old 400px caps meant anything larger on screen was upscaled."""
    from PySide6.QtGui import QImage

    from launcher.services.artwork import GRID, HERO

    with sandbox() as ctx:
        for art, (w, h) in ((GRID.name, (600, 900)), (HERO.name, (1920, 620))):
            image = QImage(w, h, QImage.Format.Format_RGB32)
            image.fill(0x556677)
            path = ctx.artwork.store("Game", art, image)
            kept = QImage(str(path))
            assert (kept.width(), kept.height()) == (w, h), (art, kept.size())


@test
def the_banner_never_upscales_a_cover() -> None:
    from PySide6.QtGui import QImage

    from launcher.ui.widgets.hero_banner import fit_no_upscale

    small = QImage(266, 400, QImage.Format.Format_RGB32)
    w, h = fit_no_upscale(small, 1000, 1000)
    assert (w, h) == (266, 400), "enlarged past native size"
    w, h = fit_no_upscale(small, 1000, 200)
    assert h == 200 and w < 266


@test
def artwork_cleanup_only_does_what_was_asked() -> None:
    from PySide6.QtGui import QImageWriter

    from launcher.services.artwork import GRID

    with sandbox() as ctx:
        legacy = ctx.paths.legacy_heroes_dir
        legacy.mkdir(parents=True, exist_ok=True)
        image = _sample_image()
        for name in ("Live Game.png", "Dead Game.png"):
            QImageWriter(str(legacy / name), b"png").write(image)

        report = ctx.cleaner.scan({"Live Game"})
        assert len(report.orphans) == 1
        assert report.orphans[0].key == "Dead Game"

        # Declining every action must leave the directory untouched.
        before = sorted(p.name for p in legacy.iterdir())
        ctx.cleaner.apply(
            report,
            reencode=False,
            dedupe=False,
            delete_orphans=False,
            migrate=False,
        )
        assert sorted(p.name for p in legacy.iterdir()) == before

        report = ctx.cleaner.scan({"Live Game"})
        result = ctx.cleaner.apply(report)
        assert result.orphans_removed == 1
        assert not (legacy / "Dead Game.png").exists()
        survivor = ctx.artwork.path_for("Live Game", GRID.name)
        assert survivor is not None and survivor.is_file(), "live artwork was lost"
        assert ctx.paths.artwork_dir in survivor.parents


# --------------------------------------------------------------------------
# services: importing, tasks
# --------------------------------------------------------------------------


@test
def importer_separates_games_from_helpers() -> None:
    from launcher.services.importer import scan_folder

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        big = b"\0" * 200_000
        (root / "Hades").mkdir()
        (root / "Hades" / "Hades.exe").write_bytes(big)
        (root / "Hades" / "unins000.exe").write_bytes(big)
        (root / "Hades" / "CrashHandler.exe").write_bytes(big)
        (root / "Celeste").mkdir()
        (root / "Celeste" / "Celeste.exe").write_bytes(big)
        (root / "Celeste" / "tiny.exe").write_bytes(b"\0" * 1000)
        redist = root / "Celeste" / "_CommonRedist"
        redist.mkdir()
        (redist / "vcredist_x64.exe").write_bytes(big)

        found = scan_folder(root)
        likely = [c.name for c in found if c.likely_game]
        assert sorted(likely) == ["Celeste", "Hades"], [
            (c.name, c.likely_game, c.reason) for c in found
        ]


@test
def background_tasks_report_and_cancel() -> None:
    from launcher.services.tasks import TaskGroup

    qt_app()
    group = TaskGroup()
    done: list[object] = []
    failed: list[str] = []
    group.finished.connect(lambda _t, r: done.append(r))
    group.failed.connect(lambda _t, m: failed.append(m))

    for i in range(5):
        group.submit(lambda n=i: n * 2)
    pump(lambda: len(done) == 5)
    assert sorted(done) == [0, 2, 4, 6, 8], done

    def boom() -> None:
        raise ValueError("boom")

    group.submit(boom)
    pump(lambda: bool(failed))
    assert failed and "boom" in failed[0]

    late = TaskGroup()
    arrived: list[object] = []
    late.finished.connect(lambda _t, r: arrived.append(r))
    late.submit(lambda: (time.sleep(0.3), "late")[1])
    late.cancel_all()
    pump(lambda: False, timeout=0.8)
    assert arrived == [], arrived


@test
def task_tokens_fit_in_a_qt_int() -> None:
    """Signal(int) is a 32-bit C++ int; wider tokens overflow."""
    from launcher.services.tasks import TaskGroup

    qt_app()
    group = TaskGroup()
    for _ in range(3):
        group.cancel_all()
        assert group.submit(lambda: None) < 2**31


@test
def short_sessions_do_not_count_as_playtime() -> None:
    from launcher.services.process import MIN_SESSION_SECONDS, ProcessService, _Session

    with sandbox() as ctx:
        service = ProcessService(ctx.paths)
        recorded: list[tuple[str, int]] = []
        service.session_recorded.connect(lambda n, s: recorded.append((n, s)))

        # A launch that dies immediately is a failure, not a session.
        service._sessions["Quick"] = _Session(None, time.monotonic())
        service._on_finished("Quick", 1)
        assert recorded == [], recorded

        service._sessions["Long"] = _Session(
            None, time.monotonic() - (MIN_SESSION_SECONDS + 5)
        )
        service._on_finished("Long", 0)
        assert recorded and recorded[0][0] == "Long"
        assert recorded[0][1] >= MIN_SESSION_SECONDS


# --------------------------------------------------------------------------
# app: the controller
# --------------------------------------------------------------------------


@test
def controller_filters_sorts_and_reports_errors() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig, SortOrder

    with sandbox() as ctx:
        lib = LibraryController(ctx)
        errors: list[tuple[str, str]] = []
        lib.error.connect(lambda t, m: errors.append((t, m)))

        for name in ("Hades", "Celeste", "Balatro"):
            lib.add_game(GameConfig(name=name, executable=f"/g/{name}.exe"))

        assert [g.name for g in lib.games] == ["Balatro", "Celeste", "Hades"]

        lib.set_search("ba")
        assert [g.name for g in lib.visible_games()] == ["Balatro"]
        lib.set_search("")

        lib.toggle_favorite("Celeste")
        lib.set_favorites_only(True)
        assert [g.name for g in lib.visible_games()] == ["Celeste"]
        lib.set_favorites_only(False)

        lib.set_sort_order(SortOrder.RECENTLY_ADDED)
        assert ctx.settings.get_str("sort_order") == "added"

        assert lib.add_game(GameConfig(name="Hades", executable="/x.exe")) is False
        assert errors and errors[0][0] == "Add Game"


def _games_for_sorting():
    from launcher.domain.models import Game, GameConfig, GameStats

    def game(name, *, played=0, last=None, fav=False, launches=0, prefix="", exists=True):
        return Game(
            config=GameConfig(name=name, prefix=prefix),
            conf_path=Path(f"/g/{name}.conf"),
            stats=GameStats(
                favorite=fav,
                playtime_seconds=played,
                last_played=last,
                launch_count=launches,
            ),
            executable_exists=exists,
        )

    now = datetime(2026, 9, 1)
    return [
        game("beta", played=50, last=now - timedelta(days=3), launches=9),
        game("Alpha", played=900, last=now - timedelta(days=9), fav=True, launches=2),
        game("gamma", prefix="prefixes/gamma", exists=False),
        game("Delta", played=10, last=now, fav=True, launches=1),
    ]


@test
def every_sort_order_does_what_it_says() -> None:
    from launcher.domain.models import SortOrder, sort_games

    games = _games_for_sorting()

    def names(order, **kw):
        return [g.name for g in sort_games(games, order, **kw)]

    assert names(SortOrder.NAME) == ["Alpha", "beta", "Delta", "gamma"]
    assert names(SortOrder.NAME_DESC) == ["gamma", "Delta", "beta", "Alpha"]
    assert names(SortOrder.LAST_PLAYED) == ["Delta", "beta", "Alpha", "gamma"]
    assert names(SortOrder.PLAYTIME) == ["Alpha", "beta", "Delta", "gamma"]
    assert names(SortOrder.LEAST_PLAYED) == ["gamma", "Delta", "beta", "Alpha"]
    assert names(SortOrder.MOST_LAUNCHED) == ["beta", "Alpha", "Delta", "gamma"]
    assert names(SortOrder.NAME_DESC, favorites_first=True) == [
        "Delta", "Alpha", "gamma", "beta"
    ]


@test
def library_filters_combine_and_round_trip() -> None:
    from launcher.domain.library_filter import (
        Availability,
        LibraryFilter,
        PlayState,
        PrefixKind,
    )

    games = _games_for_sorting()

    def names(f, **kw):
        return sorted(g.name for g in games if f.matches(g, **kw))

    assert names(LibraryFilter()) == ["Alpha", "Delta", "beta", "gamma"]
    assert names(LibraryFilter(played=PlayState.UNPLAYED)) == ["gamma"]
    assert names(LibraryFilter(availability=Availability.MISSING)) == ["gamma"]
    assert names(LibraryFilter(prefix=PrefixKind.OWN)) == ["gamma"]
    both = LibraryFilter(favorites=True, played=PlayState.PLAYED, text="al")
    assert names(both) == ["Alpha"]
    assert both.active_count == 2
    assert names(LibraryFilter(running=True), running={"beta"}) == ["beta"]
    assert names(
        LibraryFilter(missing_art=True), has_art=lambda n: n != "Delta"
    ) == ["Delta"]

    stored = LibraryFilter.from_json(both.to_json())
    assert stored == both.with_(text=""), "search text is not persisted"
    assert LibraryFilter.from_json({"played": "bogus"}) == LibraryFilter()
    assert both.cleared() == LibraryFilter(text="al")


@test
def the_old_hide_missing_setting_becomes_a_filter() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.library_filter import Availability

    with sandbox() as ctx:
        ctx.settings.set("hide_missing", True)
        lib = LibraryController(ctx)
        assert lib.filter.availability is Availability.INSTALLED
        assert not ctx.settings.get_bool("hide_missing")
        assert LibraryController(ctx).filter.availability is Availability.INSTALLED


@test
def clearing_data_touches_only_what_was_asked() -> None:
    from launcher.app import data_cleaner
    from launcher.app.data_cleaner import DataKind
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        state = ctx.state
        for name in ("Alpha", "Beta"):
            ctx.games.add(GameConfig(name=name, executable="/g/x.exe"))
            state.add_playtime(name, 3600)
            state.record_session(name, datetime(2026, 9, 1), 3600)
            state.record_launch(name)
            state.set_favorite(name, True)

        report = data_cleaner.clear(ctx, ["Alpha"], {DataKind.HISTORY, DataKind.LAUNCHES})
        assert report.sessions == 1 and report.snapshot is not None
        assert report.snapshot.is_file(), "no copy of the database was kept"
        alpha, beta = state.get("Alpha"), state.get("Beta")
        assert alpha.last_played is None and alpha.launch_count == 0
        assert alpha.playtime_seconds == 3600, "playtime was not asked for"
        assert alpha.favorite
        assert beta.last_played is not None and state.session_count(["Beta"]) == 1

        data_cleaner.clear(ctx, ["Alpha", "Beta"], {DataKind.PLAYTIME, DataKind.FAVORITES})
        assert state.total_playtime() == 0
        assert not state.get("Beta").favorite
        assert data_cleaner.clear(ctx, [], {DataKind.HISTORY}).snapshot is None


@test
def removed_games_can_be_forgotten() -> None:
    from launcher.app import data_cleaner
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        ctx.games.add(GameConfig(name="Kept", executable="/g/x.exe"))
        for name in ("Kept", "Gone"):
            ctx.state.add_playtime(name, 60)
            ctx.state.record_session(name, datetime(2026, 9, 1), 60)
        assert data_cleaner.orphaned_names(ctx) == ["Gone"]
        report = data_cleaner.forget_orphans(ctx)
        assert report.forgotten == 1 and report.sessions == 1
        assert ctx.state.known_names() == {"Kept"}


@test
def the_clear_data_dialog_counts_what_it_would_clear() -> None:
    from launcher.app.data_cleaner import DataKind
    from launcher.domain.models import GameConfig
    from launcher.ui.dialogs.clear_data_dialog import ClearDataDialog

    qt_app()
    with sandbox() as ctx:
        ctx.games.add(GameConfig(name="Alpha", executable="/g/x.exe"))
        ctx.state.record_session("Alpha", datetime(2026, 9, 1), 5400)
        ctx.state.add_playtime("Alpha", 5400)
        ctx.state.record_session("Gone", datetime(2026, 9, 1), 60)
        dialog = ClearDataDialog(ctx, "Alpha")
        box, detail = dialog._boxes[DataKind.PLAYTIME]
        assert detail.text().startswith("1h 30m")
        assert not dialog._clear_btn.isEnabled(), "nothing ticked yet"
        box.setChecked(True)
        assert dialog._clear_btn.isEnabled()
        assert len(dialog._scope.buttons()) == 3, "this game, all, removed"


@test
def renaming_through_the_controller_cannot_duplicate_a_game() -> None:
    """The caller naturally mutates the game's own config; that must work."""
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        lib = LibraryController(ctx)
        lib.add_game(GameConfig(name="Hades", executable="/g/h.exe"))
        ctx.state.add_playtime("Hades", 7200)
        lib.reload()

        game = lib.game("Hades")
        assert game is not None
        config = game.config
        config.name = "Hades II"
        assert lib.update_game("Hades", config)

        assert [g.name for g in lib.games] == ["Hades II"]
        renamed = lib.game("Hades II")
        assert renamed is not None and renamed.playtime_seconds == 7200


@test
def playtime_accumulates_from_finished_sessions() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        lib = LibraryController(ctx)
        lib.add_game(GameConfig(name="Hades", executable="/g/h.exe"))
        lib.reload()

        ctx.processes.game_started.emit("Hades")
        ctx.processes.session_recorded.emit("Hades", 1800)
        ctx.processes.session_recorded.emit("Hades", 600)

        game = lib.game("Hades")
        assert game is not None
        assert game.playtime_seconds == 2400, game.playtime_seconds
        assert game.last_played is not None


# --------------------------------------------------------------------------
# shared save store
# --------------------------------------------------------------------------


def _make_prefix(ctx, name: str, files: dict[str, str], *, age: float = 0.0):
    """A prefix with a Proton-shaped drive_c and some save data."""
    from launcher.domain.save_layout import LINKS

    drive_c = ctx.paths.base / name / "pfx" / "drive_c"
    for spec in LINKS:
        (drive_c / spec.in_prefix).mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        path = drive_c / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if age:
            when = time.time() - age
            os.utime(path, (when, when))
    return ctx.paths.base / name


@test
def merge_keeps_the_newer_file_and_quarantines_the_other() -> None:
    from launcher.services import merge

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        source, dest, conflicts = root / "s", root / "d", root / "c"
        now = time.time()

        def write(path: Path, text: str, when: float) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            os.utime(path, (when, when))

        write(source / "new_only.txt", "s", now)
        write(source / "same.txt", "same", now - 500)
        write(dest / "same.txt", "same", now - 500)
        write(source / "newer.txt", "source", now)
        write(dest / "newer.txt", "dest", now - 1000)
        write(source / "older.txt", "source", now - 1000)
        write(dest / "older.txt", "dest", now)

        plan = merge.plan_merge(source, dest)
        assert len(plan.moves) == 1
        assert len(plan.identical) == 1
        assert len(plan.conflicts) == 2
        # Planning must not touch anything.
        assert (source / "new_only.txt").is_file()

        result = merge.apply_merge(source, dest, conflicts)
        assert result.moved == 1
        assert result.identical_removed == 1
        assert len(result.conflicts) == 2
        assert not result.errors

        assert (dest / "newer.txt").read_text() == "source"
        assert (dest / "older.txt").read_text() == "dest"
        quarantined = {p.name: p.read_text() for p in conflicts.rglob("*.txt")}
        assert quarantined == {"newer.txt": "dest", "older.txt": "source"}, quarantined
        # Everything left the source; nothing was deleted outright.
        assert not list(source.rglob("*.txt"))


@test
def adopting_a_prefix_moves_saves_and_links_them_back() -> None:
    with sandbox() as ctx:
        prefix = _make_prefix(
            ctx,
            "Prefix",
            {
                "users/steamuser/Documents/My Games/save.sav": "A save",
                "users/steamuser/AppData/Roaming/Balatro/profile": "A profile",
                "ProgramData/Ubisoft/cfg": "A cfg",
            },
        )
        store = ctx.save_store
        assert store.reachable, "store must sit inside the launcher folder"

        plan = store.plan_adopt(prefix)
        assert plan.can_run
        assert plan.total_moves == 3
        # A dry run writes nothing.
        assert not store.root.exists() or not any(store.root.rglob("*.sav"))

        result = store.adopt(prefix)
        assert result.ok, result.errors
        assert len(result.linked) == 6
        assert store.status(prefix).fully_linked

        save = prefix / "pfx/drive_c/users/steamuser/Documents/My Games/save.sav"
        assert save.read_text() == "A save", "not readable through the link"
        assert (store.root / "Documents/My Games/save.sav").is_file()
        assert save.parent.parent.is_symlink() or save.parent.parent.parent.is_symlink()


@test
def two_prefixes_share_one_copy_of_the_saves() -> None:
    with sandbox() as ctx:
        first = _make_prefix(
            ctx, "Prefix", {"users/steamuser/Documents/shared.txt": "from A"}
        )
        second = _make_prefix(
            ctx,
            "prefixes/Lies-of-P",
            {"users/steamuser/Documents/only_b.txt": "B only"},
        )
        store = ctx.save_store
        store.adopt(first)
        store.adopt(second)

        assert store.status(first).fully_linked
        assert store.status(second).fully_linked

        # A file written through one prefix is visible through the other.
        (first / "pfx/drive_c/users/steamuser/Documents/new.txt").write_text("hi")
        via_second = second / "pfx/drive_c/users/steamuser/Documents/new.txt"
        assert via_second.read_text() == "hi"
        assert (store.root / "Documents/only_b.txt").read_text() == "B only"


@test
def repair_recovers_saves_proton_wrote_into_a_replaced_link() -> None:
    """wineboot replaces the symlink with a real directory on update."""
    with sandbox() as ctx:
        prefix = _make_prefix(
            ctx, "Prefix", {"users/steamuser/Documents/old.sav": "old"}
        )
        store = ctx.save_store
        store.adopt(prefix)

        documents = prefix / "pfx/drive_c/users/steamuser/Documents"
        documents.unlink()
        documents.mkdir(parents=True)
        (documents / "written_by_proton.sav").write_text("new save")

        assert store.verify(prefix), "the broken link was not noticed"

        result = store.repair(prefix)
        assert result.repaired == ["Documents"], result.repaired
        assert result.recovered_files == 1
        assert not result.errors
        assert store.status(prefix).fully_linked
        # Both the old and the newly written save survive.
        names = sorted(p.name for p in (store.root / "Documents").iterdir())
        assert names == ["old.sav", "written_by_proton.sav"], names


@test
def releasing_a_prefix_gives_it_its_own_copy_again() -> None:
    with sandbox() as ctx:
        prefix = _make_prefix(
            ctx, "Prefix", {"users/steamuser/Documents/save.sav": "data"}
        )
        store = ctx.save_store
        store.adopt(prefix)

        result = store.release(prefix)
        assert not result.errors, result.errors
        assert store.status(prefix).unlinked

        documents = prefix / "pfx/drive_c/users/steamuser/Documents"
        assert documents.is_dir() and not documents.is_symlink()
        assert (documents / "save.sav").read_text() == "data"
        # The store keeps its copy too; releasing is not a move back.
        assert (store.root / "Documents/save.sav").read_text() == "data"


@test
def backups_of_a_linked_prefix_hold_real_data() -> None:
    """A backup must follow the links, not archive dangling symlinks."""
    with sandbox() as ctx:
        prefix = _make_prefix(
            ctx, "Prefix", {"users/steamuser/Documents/save.sav": "REAL DATA"}
        )
        ctx.save_store.adopt(prefix)
        assert ctx.save_store.status(prefix).fully_linked

        backup = ctx.backups.create("test")
        found = list(backup.data.rglob("save.sav"))
        assert found, "the save did not make it into the backup"
        assert not found[0].is_symlink(), "backed up a symlink, not the data"
        assert found[0].read_text() == "REAL DATA"


@test
def backup_exclusions_cover_whole_cache_folders() -> None:
    from launcher.domain.backup_policy import Exclusions

    rules = Exclusions.with_extra("Documents/Big Game/mods  # downloaded\n\n")
    assert rules.excludes("AppData/Local/dxvk/game.dxvk-cache")
    assert rules.excludes("AppData/Local/Temp")
    assert rules.excludes("AppData/Roaming/Some Game/Cache/blob.bin")
    assert rules.excludes("Documents/big game/MODS/x.scs"), "user rule, any case"
    assert not rules.excludes("AppData/Roaming/Some Game/save.sav")
    assert not rules.excludes("AppData/Roaming/Cachet/save.sav"), "prefix, not word"
    assert not Exclusions(()).excludes("anything"), "no rules excludes nothing"


@test
def retention_keeps_recent_daily_weekly_and_pinned() -> None:
    from datetime import date

    from launcher.domain.backup_policy import Retention, SnapshotAge, to_prune

    today = date(2026, 9, 22)  # a Tuesday
    base = datetime(2026, 9, 22, 20, 0)
    snaps = [SnapshotAge(f"h{i}", base - timedelta(hours=i)) for i in range(8)]
    snaps += [SnapshotAge(f"d{i}", base - timedelta(days=i, hours=1)) for i in range(1, 40)]
    snaps.append(SnapshotAge("old-pinned", base - timedelta(days=300), pinned=True))
    doomed = set(to_prune(snaps, Retention(recent=3, daily=7, weekly=4), today))

    assert {"h0", "h1", "h2"}.isdisjoint(doomed), "the latest are kept"
    assert "h3" in doomed, "extra ones from today go"
    assert {f"d{i}" for i in range(1, 7)}.isdisjoint(doomed), "one per day"
    assert "old-pinned" not in doomed
    assert "d30" in doomed, "older than the weekly window"
    kept_old_weeks = {f"d{i}" for i in range(7, 40)} - doomed
    assert 1 <= len(kept_old_weeks) <= 3, kept_old_weeks


def _store_with(ctx, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = ctx.paths.saves_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return ctx.paths.saves_dir


@test
def snapshots_share_unchanged_files_and_restore_exactly() -> None:
    with sandbox() as ctx:
        store = _store_with(ctx, {
            "AppData/Roaming/Game/save.sav": "v1",
            "AppData/Roaming/Game/settings.ini": "same",
            "AppData/Local/dxvk/big.cache": "cache",
            "Documents/Other/keep.sav": "other",
        })
        first = ctx.backups.create("first")
        assert not (first.data / "AppData/Local/dxvk").exists(), "cache backed up"
        assert (first.data / "AppData/Roaming/Game/save.sav").read_text() == "v1"

        save = store / "AppData/Roaming/Game/save.sav"
        save.write_text("v2 longer")
        os.utime(save, (time.time() + 5, time.time() + 5))
        (store / "AppData/Roaming/Game/new.sav").write_text("new")
        second = ctx.backups.create("second")
        unchanged = "AppData/Roaming/Game/settings.ini"
        assert (first.data / unchanged).stat().st_ino == (
            second.data / unchanged
        ).stat().st_ino, "an unchanged file was copied instead of linked"
        assert second.new_bytes == len("v2 longer") + len("new")

        # A game rewriting its save in place must not reach the backup.
        save.write_text("v3")
        assert (second.data / "AppData/Roaming/Game/save.sav").read_text() == "v2 longer"

        result = ctx.backups.restore(first)
        assert save.read_text() == "v1"
        assert not (store / "AppData/Roaming/Game/new.sav").exists()
        assert (store / "AppData/Local/dxvk/big.cache").exists(), "cache touched"
        assert result.safety is not None
        assert (result.safety.data / "AppData/Roaming/Game/save.sav").read_text() == "v3"
        for spec_dir in ("AppData/Local", "Documents", "Saved Games"):
            assert (store / spec_dir).is_dir() or spec_dir == "Saved Games"


@test
def restoring_one_folder_leaves_the_rest_alone() -> None:
    with sandbox() as ctx:
        store = _store_with(ctx, {
            "AppData/Roaming/A/save.sav": "a1",
            "AppData/Roaming/B/save.sav": "b1",
        })
        snap = ctx.backups.create("snap")
        (store / "AppData/Roaming/A/save.sav").write_text("a2!")
        (store / "AppData/Roaming/B/save.sav").write_text("b2!")
        ctx.backups.restore(snap, "AppData/Roaming/A", safety_snapshot=False)
        assert (store / "AppData/Roaming/A/save.sav").read_text() == "a1"
        assert (store / "AppData/Roaming/B/save.sav").read_text() == "b2!"


@test
def an_interrupted_snapshot_is_never_listed_and_is_cleared() -> None:
    with sandbox() as ctx:
        _store_with(ctx, {"Documents/x.sav": "x"})
        partial = ctx.backups.root / "2026-01-01_000000.partial"
        (partial / "data").mkdir(parents=True)
        assert ctx.backups.snapshots() == []
        ctx.backups.create("real")
        assert not partial.exists()
        assert len(ctx.backups.snapshots()) == 1


@test
def launching_shares_the_prefix_after_backing_up_the_store() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        exe = ctx.paths.base / "game.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"MZ")
        ctx.games.add(GameConfig(name="Alpha", executable=str(exe)))
        _store_with(ctx, {"Documents/Older/save.sav": "old"})
        prefix = _make_prefix(
            ctx, "Prefix", {"users/steamuser/Documents/Alpha/save.sav": "alpha"}
        )
        library = LibraryController(ctx)
        keeper = library.saves
        game = ctx.games.get("Alpha")
        assert game is not None and keeper.needs_sharing(prefix)

        keeper.before_launch(game)
        assert ctx.save_store.status(prefix).fully_linked
        assert (ctx.paths.saves_dir / "Documents/Alpha/save.sav").read_text() == "alpha"
        snaps = ctx.backups.snapshots()
        assert len(snaps) == 1 and "before sharing" in snaps[0].reason
        assert (snaps[0].data / "Documents/Older/save.sav").exists()

        # Already shared: launching again does nothing and takes no backup.
        keeper.before_launch(game)
        assert len(ctx.backups.snapshots()) == 1


@test
def sharing_by_default_can_be_turned_off() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        ctx.settings.set("share_saves_by_default", False)
        ctx.games.add(GameConfig(name="Alpha", executable="/g/a.exe"))
        prefix = _make_prefix(ctx, "Prefix", {"users/steamuser/Documents/a.sav": "a"})
        library = LibraryController(ctx)
        keeper = library.saves
        game = ctx.games.get("Alpha")
        assert game is not None
        keeper.before_launch(game)
        assert ctx.save_store.status(prefix).unlinked


@test
def share_everything_takes_one_backup_for_all_prefixes() -> None:
    from launcher.app.library_controller import LibraryController

    with sandbox() as ctx:
        _store_with(ctx, {"Documents/x.sav": "x"})
        first = _make_prefix(ctx, "Prefix", {"users/steamuser/Documents/a/1.sav": "1"})
        second = _make_prefix(
            ctx, "prefixes/Beta", {"users/steamuser/Documents/b/2.sav": "2"}
        )
        library = LibraryController(ctx)
        keeper = library.saves
        shared = keeper.share_everything()
        assert {p for p, _ in shared} == {first, second}
        assert len(ctx.backups.snapshots()) == 1
        assert keeper.share_everything() == []


@test
def backups_point_at_a_games_own_folder() -> None:
    from launcher.ui.dialogs.backups_dialog import _starts_word, hint_tokens

    tokens = hint_tokens("Elden Ring Nightreign")
    assert tokens == ["elden", "ring", "nightreign"]
    assert _starts_word("nightreign", "nightreign")
    assert _starts_word("elden ring", "elden")
    assert not _starts_word("helden", "elden"), "matched inside a word"


@test
def automatic_backups_wait_for_the_interval() -> None:
    from launcher.app.library_controller import LibraryController

    with sandbox() as ctx:
        _store_with(ctx, {"Documents/x.sav": "x"})
        library = LibraryController(ctx)
        keeper = library.saves
        assert keeper.backup_due(), "no backup yet"
        snap = ctx.backups.create("t")
        assert not keeper.backup_due()
        assert keeper.backup_due(snap.created + timedelta(minutes=31))
        ctx.settings.set("backup_auto", False)
        assert not keeper.backup_due(snap.created + timedelta(days=9))


@test
def a_store_outside_the_launcher_folder_is_refused() -> None:
    """Games resolve these links inside the Steam Flatpak container.

    A store the container cannot see would leave every save folder
    looking empty in-game, so it is rejected rather than half-built.
    """
    from launcher.domain.save_layout import store_is_reachable

    with sandbox() as ctx:
        assert store_is_reachable(ctx.paths.saves_dir, ctx.paths.base)
        assert not store_is_reachable(Path.home() / "elsewhere", ctx.paths.base)


@test
def launching_repairs_broken_save_links_first() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        prefix = _make_prefix(
            ctx,
            "prefixes/Alpha",
            {"users/steamuser/Documents/save.sav": "data"},
        )
        ctx.save_store.adopt(prefix)

        exe = ctx.paths.base / "alpha.exe"
        exe.write_bytes(b"\0")
        lib = LibraryController(ctx)
        lib.add_game(
            GameConfig(name="Alpha", executable=str(exe), prefix="prefixes/Alpha")
        )
        lib.reload()

        documents = prefix / "pfx/drive_c/users/steamuser/Documents"
        documents.unlink()
        documents.mkdir(parents=True)
        (documents / "after_update.sav").write_text("written by proton")

        launched: list[str] = []
        ctx.processes.launch = lambda n: (launched.append(n), True)[1]
        assert lib.launch("Alpha")

        assert launched == ["Alpha"]
        assert ctx.save_store.status(prefix).fully_linked, "link was not repaired"
        assert (
            ctx.save_store.root / "Documents/after_update.sav"
        ).read_text() == "written by proton"


# --------------------------------------------------------------------------
# ui
# --------------------------------------------------------------------------


@test
def window_builds_and_selecting_never_launches() -> None:
    from launcher.app.main import build_window
    from launcher.domain.models import GameConfig

    app = qt_app()
    with sandbox() as ctx:
        # Real files: the controller refuses to launch a game whose
        # executable is missing, and the Play button stays disabled.
        exe_dir = ctx.paths.base / "exes"
        exe_dir.mkdir(parents=True, exist_ok=True)
        for name in ("Alpha", "Beta"):
            exe = exe_dir / f"{name}.exe"
            exe.write_bytes(b"\0")
            ctx.games.add(GameConfig(name=name, executable=str(exe)))

        window = build_window(ctx)
        window.show()
        app.processEvents()

        launched: list[str] = []
        ctx.processes.launch = lambda n: (launched.append(n), True)[1]

        window._sidebar.select_game("Beta")
        app.processEvents()
        assert launched == [], "selection launched a game"
        assert window._detail._game is not None
        assert window._detail._game.name == "Beta"

        window._detail._play_btn.click()
        app.processEvents()
        assert launched == ["Beta"], launched
        window.close()


@test
def a_single_click_selects_but_never_launches() -> None:
    """Clicking a row must only select it.

    Regression: the list used itemActivated, which Qt fires on a SINGLE
    click when the desktop activates items on single click (KDE's
    default), so selecting a game launched it.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from launcher.app.main import build_window
    from launcher.domain.models import GameConfig

    app = qt_app()
    with sandbox() as ctx:
        exe_dir = ctx.paths.base / "exes"
        exe_dir.mkdir(parents=True, exist_ok=True)
        for name in ("Alpha", "Beta"):
            exe = exe_dir / f"{name}.exe"
            exe.write_bytes(b"\0")
            ctx.games.add(GameConfig(name=name, executable=str(exe)))

        window = build_window(ctx)
        window.resize(1280, 800)
        window.show()
        app.processEvents()

        launched: list[str] = []
        ctx.processes.launch = lambda n: (launched.append(n), True)[1]

        listing = window._sidebar._list
        row = listing.item(1)
        assert row is not None
        centre = listing.visualItemRect(row).center()

        # Force single-click activation, so this reproduces the bug
        # regardless of the style the test machine happens to use.
        # setStyle does not take ownership, so the proxy has to outlive
        # the widget or Qt follows a dangling pointer on teardown.
        proxy = _single_click_style()
        _KEEP_ALIVE.append(proxy)
        listing.setStyle(proxy)
        QTest.mouseClick(
            listing.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(centre.x(), centre.y())
        )
        app.processEvents()

        assert listing.currentRow() == 1, "the click did not select the row"
        assert launched == [], f"a single click launched {launched}"

        # A double-click is the deliberate gesture, and does launch.
        QTest.mouseDClick(
            listing.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(centre.x(), centre.y())
        )
        app.processEvents()
        assert launched, "a double click should launch"
        window.close()


@test
def a_missing_executable_cannot_be_launched() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig

    with sandbox() as ctx:
        lib = LibraryController(ctx)
        lib.add_game(GameConfig(name="Gone", executable="/nowhere/gone.exe"))
        lib.reload()

        errors: list[tuple[str, str]] = []
        lib.error.connect(lambda t, m: errors.append((t, m)))
        launched: list[str] = []
        ctx.processes.launch = lambda n: (launched.append(n), True)[1]

        assert lib.launch("Gone") is False
        assert launched == [], "launched a game with no executable"
        assert errors and errors[0][0] == "Cannot Launch"


@test
def logs_are_kept_per_game() -> None:
    from launcher.app.main import build_window
    from launcher.domain.models import GameConfig

    app = qt_app()
    with sandbox() as ctx:
        for name in ("Alpha", "Beta"):
            ctx.games.add(GameConfig(name=name, executable=f"/g/{name}.exe"))
        window = build_window(ctx)
        window.show()
        app.processEvents()

        window._sidebar.select_game("Beta")
        app.processEvents()

        # Output for a game that is not on screen must still be captured.
        window._on_game_started("Alpha")
        window._on_game_output("Alpha", "hello from alpha\n")
        app.processEvents()

        window._sidebar.select_game("Alpha")
        app.processEvents()
        assert "hello from alpha" in window._detail._log._output.toPlainText()

        window._sidebar.select_game("Beta")
        app.processEvents()
        assert window._detail._log._output.toPlainText() == ""
        window.close()


@test
def the_journal_replaces_the_grid() -> None:
    """The card grid is gone; the second view is the play Journal."""
    from PySide6.QtWidgets import QPushButton

    from launcher.app.main import build_window
    from launcher.domain.models import GameConfig

    app = qt_app()
    with sandbox() as ctx:
        exe = ctx.paths.base / "a.exe"
        exe.write_bytes(b"\0")
        for name in ("Alpha", "Beta"):
            ctx.games.add(GameConfig(name=name, executable=str(exe)))
        ctx.state.add_playtime("Alpha", 5400)
        ctx.state.record_launch("Alpha")
        ctx.state.record_session("Alpha", datetime.now(), 5400)

        window = build_window(ctx)
        window.resize(1280, 800)
        window.show()
        app.processEvents()

        labels = {b.text() for b in window.findChildren(QPushButton)}
        assert "Grid" not in labels and "Journal" in labels, sorted(labels)
        assert not hasattr(window, "_game_grid")

        window._switch_view(1)
        app.processEvents()
        journal = window._journal
        assert journal._continue_name == "Alpha", "last played game not offered"
        assert journal._total_tile._value.text() == "1h 30m"
        assert journal._streak_tile._value.text() == "1 day"

        launched: list[str] = []
        ctx.processes.launch = lambda n: (launched.append(n), True)[1]
        journal._continue_btn.click()
        app.processEvents()
        assert launched == ["Alpha"], "Continue did not play the game"
        # Launching switches to the library, where the log lives.
        assert window._views.currentIndex() == 0
        window.close()


@test
def detail_menu_submenus_survive_garbage_collection() -> None:
    """Regression: QMenu.addMenu(title) hands the submenu to Python.

    Letting it fall out of scope destroyed the C++ object while the
    parent menu still referenced it, so the Prefix and Saves entries
    opened empty and none of the tools could be reached.
    """
    import gc

    from launcher.app.main import build_window
    from launcher.domain.models import GameConfig

    app = qt_app()
    with sandbox() as ctx:
        ctx.games.add(GameConfig(name="Alpha", executable="/g/a.exe"))
        window = build_window(ctx)
        window.show()
        app.processEvents()
        window._sidebar.select_game("Alpha")
        app.processEvents()
        gc.collect()

        emitted: list[tuple[str, str]] = []
        window._detail.prefix_tool_requested.connect(
            lambda n, t: emitted.append((n, t))
        )
        # The window's own handler would really try to run the tool, fail
        # on a prefix that does not exist, and open a modal warning that
        # blocks the suite. Only the menu wiring is under test here.
        ctx.prefix_tools.run = lambda *_: True
        ctx.prefix_tools.open_folder = lambda *_: True

        menu = window._detail._more_btn.menu()
        assert menu is not None
        submenus = {
            a.text(): a.menu() for a in menu.actions() if a.menu() is not None
        }
        assert set(submenus) == {"Prefix", "Saves"}, sorted(submenus)

        prefix_menu = submenus["Prefix"]
        labels = [a.text() for a in prefix_menu.actions()]
        assert labels == [
            "Open folder",
            "Wine configuration",
            "Winetricks",
            "Wine file browser",
        ], labels

        for action in prefix_menu.actions():
            action.trigger()
        app.processEvents()
        assert [t for _, t in emitted] == [
            "open",
            "winecfg",
            "winetricks",
            "explorer",
        ], emitted
        window.close()


@test
def proton_prefixes_run_tools_through_the_launcher_script() -> None:
    """A Proton prefix can only be opened by the Proton that built it.

    That Proton lives inside the Steam Flatpak, so the tool has to go
    through milso-launcher.sh rather than the host's wine.
    """
    from launcher.services import prefix_tools as pt

    with sandbox() as ctx:
        prefix = ctx.paths.base / "Prefix"
        drive_c = prefix / "pfx" / "drive_c"
        (drive_c / "windows" / "system32").mkdir(parents=True)
        # Proton links these into the Flatpak, so on the host they are
        # dangling symlinks that only resolve inside the container.
        (drive_c / "windows" / "system32" / "winecfg.exe").symlink_to(
            "/app/share/steam/nowhere/winecfg.exe"
        )
        ctx.paths.launcher_script.write_text("#!/usr/bin/env bash\n")
        assert pt.is_proton_prefix(prefix)

        pt.steam_flatpak_running = lambda: True
        command = ctx.prefix_tools._proton_command(
            pt.TOOLS_BY_KEY["winecfg"], prefix
        )
        assert command is not None, "fell back to host wine for a Proton prefix"
        program, args = command
        assert program == "bash"
        assert str(ctx.paths.launcher_script) in args
        assert "-exec" in args
        assert args[-1].endswith("winecfg.exe")

        # Without Steam the script exits at once, so the user must be told
        # rather than left watching nothing happen.
        pt.steam_flatpak_running = lambda: False
        failures: list[tuple[str, str]] = []
        ctx.prefix_tools.tool_failed.connect(lambda label, msg: failures.append((label, msg)))
        assert (
            ctx.prefix_tools._proton_command(pt.TOOLS_BY_KEY["winecfg"], prefix)
            is None
        )
        assert failures and "Steam is not running" in failures[0][1]


@test
def a_missing_prefix_reports_instead_of_failing_silently() -> None:
    from launcher.services import prefix_tools as pt

    with sandbox() as ctx:
        failures: list[tuple[str, str]] = []
        ctx.prefix_tools.tool_failed.connect(lambda label, msg: failures.append((label, msg)))
        assert ctx.prefix_tools.run("winecfg", "prefixes/Nope") is False
        assert failures and "does not exist" in failures[0][1]

        assert ctx.prefix_tools.open_folder("prefixes/Nope") is False
        assert any("does not exist" in m for _, m in failures)
        assert pt.TOOLS_BY_KEY["winecfg"].verb == "winecfg"


@test
def every_feature_dialog_is_reachable_from_the_window() -> None:
    """Regression: the Shared Saves dialog shipped with no button.

    The dialog and its handler existed, but the edit adding the toolbar
    button silently matched nothing, and tests that built the dialog
    directly could not notice. Click through the real window instead.
    """
    from PySide6.QtWidgets import QPushButton

    from launcher.app.main import build_window
    from launcher.ui.dialogs import saves_dialog

    app = qt_app()
    with sandbox() as ctx:
        window = build_window(ctx)
        window.show()
        app.processEvents()

        buttons = {b.text(): b for b in window.findChildren(QPushButton)}
        for wanted in ("Saves", "Settings"):
            assert wanted in buttons, f"no {wanted!r} button; found {sorted(buttons)}"
        menu = buttons["Saves"].menu()
        assert menu is not None, "the Saves button has no menu"
        actions = {a.text(): a for a in menu.actions()}
        for wanted in ("Shared saves\u2026", "Backups\u2026", "Back up now"):
            assert wanted in actions, f"no {wanted!r} in the Saves menu"

        opened: list[str] = []
        original = saves_dialog.SavesDialog.exec
        saves_dialog.SavesDialog.exec = lambda self: opened.append("saves") or 0
        try:
            actions["Shared saves\u2026"].trigger()
            app.processEvents()
        finally:
            saves_dialog.SavesDialog.exec = original

        assert opened == ["saves"], "clicking Shared Saves did not open it"
        window.close()


@test
def settings_pages_reach_every_tool() -> None:
    """Tools moved off the toolbar must still open, from their page."""
    from PySide6.QtWidgets import QPushButton

    from launcher.ui.dialogs.settings_dialog import SettingsDialog

    qt_app()
    with sandbox() as ctx:
        dialog = SettingsDialog(ctx, page="saves")
        titles = [dialog._nav.item(i).text() for i in range(dialog._nav.count())]
        assert titles[:3] == ["Appearance", "Library", "Artwork"], titles
        assert dialog._nav.currentItem().text() == "Saves & backups"

        fired: list[str] = []
        for signal, name in (
            (dialog.cleanup_requested, "cleanup"),
            (dialog.shared_saves_requested, "saves"),
            (dialog.backups_requested, "backups"),
            (dialog.clear_data_requested, "clear"),
        ):
            signal.connect(lambda n=name: fired.append(n))
        for button in dialog.findChildren(QPushButton):
            if button.text() in (
                "Clean up artwork\u2026", "Shared saves\u2026", "Backups\u2026",
                "Clear data\u2026",
            ):
                button.click()
        assert sorted(fired) == ["backups", "cleanup", "clear", "saves"], fired


class _FakeSgdb:
    """SteamGridDB without the network: every image is a solid colour."""

    configured = True

    def __init__(self) -> None:
        self.queries: list = []

    def find_games(self, query):
        from launcher.services.sgdb import GameMatch

        return [GameMatch(7, "Other Game"), GameMatch(1, query, 2024, True)]

    def find_art(self, game_id, query):
        from launcher.services.sgdb import ArtResult

        self.queries.append((game_id, query))
        w, h = {"grid": (600, 900), "hero": (1920, 620), "logo": (800, 300),
                "icon": (256, 256)}[query.art]
        return [
            ArtResult(id=i, url=f"full:{query.art}:{w}x{h}", thumb=f"thumb:{query.art}",
                      width=w, height=h, author="someone")
            for i in (1, 2)
        ]

    def download(self, url):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QColor, QImage

        size = url.rsplit(":", 1)[-1]
        w, h = (int(v) for v in size.split("x")) if "x" in size else (60, 90)
        image = QImage(w, h, QImage.Format.Format_RGB32)
        image.fill(QColor("#3366aa"))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(data.data())


def _pump(until, timeout: float = 10.0) -> None:
    from PySide6.QtCore import QThreadPool

    app = qt_app()
    deadline = time.monotonic() + timeout
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for background work")
        QThreadPool.globalInstance().waitForDone(20)
        app.processEvents()


@test
def the_artwork_wizard_previews_then_applies() -> None:
    from launcher.domain.models import GameConfig
    from launcher.services.artwork import GRID, HERO
    from launcher.ui.dialogs.artwork_wizard import ArtworkWizard

    qt_app()
    with sandbox() as ctx:
        ctx.games.add(GameConfig(name="Alpha", executable="/g/a.exe"))
        fake = _FakeSgdb()
        wizard = ArtworkWizard(ctx, "Alpha", client=fake)
        applied: list[str] = []
        wizard.applied.connect(applied.append)

        _pump(lambda: wizard._match is not None)
        assert wizard._match.id == 1, "the exact name match should be picked"

        wizard._go(1)  # Cover
        page = wizard._art_pages[GRID.name]
        _pump(lambda: page.grid.count() == 2)
        assert fake.queries[-1][0] == 1
        assert not wizard._apply.isEnabled(), "nothing chosen yet"

        page.result_chosen.emit(page.grid.item(0).data(0x0100))
        _pump(lambda: wizard._choices[GRID.name].data is not None)
        preview = wizard._art.image("Alpha", GRID.name)
        assert preview is not None and preview.height() == 900, "full image not previewed"
        assert ctx.artwork.path_for("Alpha", GRID.name) is None, "saved before Apply"
        assert wizard._apply.isEnabled()

        wizard._set_choice(HERO.name, wizard._choices[HERO.name].__class__(kind="remove"))
        assert wizard._art.image("Alpha", HERO.name) is None

        wizard._go(5)
        wizard._apply_choices()
        assert applied == ["Alpha"]
        assert ctx.artwork.path_for("Alpha", GRID.name) is not None


@test
def the_artwork_wizard_works_without_an_api_key() -> None:
    from launcher.services.artwork import ICON
    from launcher.ui.dialogs.artwork_wizard import ArtworkWizard

    qt_app()
    with sandbox() as ctx, tempfile.TemporaryDirectory() as d:
        fake = _FakeSgdb()
        fake.configured = False
        wizard = ArtworkWizard(ctx, "Beta", client=fake)
        assert not wizard._find.search_btn.isEnabled()
        icon = Path(d) / "icon.png"
        icon.write_bytes(fake.download("x:256x256"))
        wizard._choose_file(ICON.name, str(icon))
        assert wizard._apply.isEnabled()
        wizard._apply_choices()
        assert ctx.artwork.path_for("Beta", ICON.name) is not None


@test
def every_theme_builds_a_complete_stylesheet() -> None:
    from launcher.ui.theme import THEMES, Appearance, build_stylesheet
    from launcher.ui.theme.appearance import CORNERS, DENSITIES, indicator_icons

    qt_app()
    for theme_id in THEMES:
        for corners in CORNERS:
            look = Appearance(theme=theme_id, corners=corners, density="compact")
            colours = look.palette()
            sheet = build_stylesheet(colours, look.metrics(), icons=indicator_icons(colours))
            assert "$" not in sheet, f"{theme_id}: unfilled placeholder"
            assert colours.selection, "selection colour not derived"
    assert set(DENSITIES) == {"compact", "comfortable", "spacious"}


@test
def a_custom_accent_stays_readable() -> None:
    from launcher.ui.theme import Appearance

    qt_app()
    light = Appearance(theme="midnight", accent="#eab308").palette()
    assert light.accent == "#eab308"
    assert light.on_accent != "#ffffff", "white text on yellow"
    dark = Appearance(theme="paper", accent="#1e3a8a").palette()
    assert dark.on_accent == "#ffffff"
    assert Appearance(text_scale=125).metrics().font_md > Appearance().metrics().font_md
    assert Appearance(density="spacious").metrics().row_height > 46


@test
def bad_appearance_settings_fall_back() -> None:
    from launcher.ui.theme import Appearance

    with sandbox() as ctx:
        ctx.settings.update(
            {"theme": "nope", "accent": "not a colour", "density": "huge", "text_scale": 7}
        )
        assert Appearance.from_settings(ctx.settings) == Appearance()
        ctx.settings.update({"theme": "paper", "accent": "#ff0000", "text_scale": 110})
        look = Appearance.from_settings(ctx.settings)
        assert (look.theme, look.accent, look.text_scale) == ("paper", "#ff0000", 110)


@test
def cancelling_settings_puts_the_old_look_back() -> None:
    from launcher.ui.dialogs.settings_dialog import SettingsDialog
    from launcher.ui.theme import Appearance, apply_theme, palette

    app = qt_app()
    with sandbox() as ctx:
        apply_theme(app, Appearance())
        before = palette().bg
        dialog = SettingsDialog(ctx)
        dialog._appearance._change(theme="paper")
        assert palette().bg != before, "no live preview"
        dialog.reject()
        assert palette().bg == before
        dialog = SettingsDialog(ctx)
        dialog._appearance._change(theme="ember")
        dialog._save()
        assert ctx.settings.get_str("theme") == "ember"
        apply_theme(app, Appearance())


@test
def generated_themes_read_well() -> None:
    from launcher.ui.theme.custom import check, generate

    qt_app()
    for background, accent in (
        ("#101820", "#ff6b35"), ("#f5f1e8", "#0f766e"), ("#2d0a31", "#f472b6"),
        ("#000000", "#ffff00"), ("#ffffff", "#1d4ed8"),
    ):
        colours = generate(background, accent)
        failing = [(label, round(r, 2)) for label, r, need in check(colours) if r < need]
        assert not failing, f"{background}/{accent}: {failing}"
    assert generate("#f5f1e8", "#0f766e").is_light
    assert not generate("#101820", "#ff6b35").is_light


@test
def custom_themes_round_trip_and_reject_junk() -> None:
    from launcher.ui.theme.custom import CustomThemeStore, generate
    from launcher.ui.theme.themes import Theme, all_themes, set_custom

    qt_app()
    with tempfile.TemporaryDirectory() as d:
        store = CustomThemeStore(Path(d) / "themes")
        try:
            theme_id = store.new_id("Sunset Drive")
            assert theme_id == "custom-sunset-drive"
            saved = store.save(Theme(theme_id, "Sunset Drive", generate("#1a0f1f", "#ff7a59")))
            assert saved.custom and theme_id in all_themes()
            assert store.new_id("Sunset Drive") == "custom-sunset-drive-2"

            set_custom([])
            loaded = store.load_all()
            assert [t.id for t in loaded] == [theme_id]
            assert loaded[0].palette.accent == "#ff7a59"

            exported = Path(d) / "shared.json"
            store.export(loaded[0], exported)
            copy = store.import_file(exported)
            assert copy.id != theme_id and copy.palette == loaded[0].palette

            (store.directory / "broken.json").write_text("{not json")
            (store.directory / "empty.json").write_text('{"name": "x", "colours": {}}')
            assert len(store.load_all()) == 2, "junk files must be skipped"
            bad = Path(d) / "bad.json"
            bad.write_text('{"name": "Bad", "colours": {"bg": "nope"}}')
            try:
                store.import_file(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("a theme without valid colours was imported")

            store.delete(copy.id)
            assert copy.id not in all_themes()
        finally:
            set_custom([])


@test
def the_theme_wizard_creates_and_edits_a_theme() -> None:
    from launcher.ui.dialogs.theme_wizard import ThemeWizard
    from launcher.ui.theme.custom import CustomThemeStore
    from launcher.ui.theme.themes import get_theme, set_custom

    qt_app()
    with tempfile.TemporaryDirectory() as d:
        store = CustomThemeStore(Path(d))
        try:
            wizard = ThemeWizard(store, start_from="frost")
            assert wizard.colours.accent == get_theme("frost").palette.accent
            wizard._bg_button.set_colour("#20122a")
            wizard._accent_button.set_colour("#ffb000")
            wizard._choose_generate()
            assert wizard.colours.bg == "#20122a"
            assert not wizard._save_btn.isEnabled(), "cannot save unnamed"

            wizard._rows["danger"].changed.emit("danger", "#ff0055")
            assert wizard.colours.danger == "#ff0055"
            assert "#20122a" in wizard._preview.styleSheet(), "preview not restyled"

            wizard._name.setText("Night Market")
            wizard._save()
            saved = wizard.saved
            assert saved is not None and saved.palette.danger == "#ff0055"
            assert (Path(d) / f"{saved.id}.json").is_file()

            editor = ThemeWizard(store, editing=saved)
            assert editor._pages.currentIndex() == 1, "editing starts at the colours"
            editor._rows["accent"].changed.emit("accent", "#00c2a8")
            editor._save()
            assert editor.saved is not None and editor.saved.id == saved.id
            assert get_theme(saved.id).palette.accent == "#00c2a8"
        finally:
            set_custom([])


@test
def dialogs_all_construct() -> None:
    from launcher.app.library_controller import LibraryController
    from launcher.domain.models import GameConfig
    from launcher.ui.dialogs.artwork_wizard import ArtworkWizard
    from launcher.ui.dialogs.backups_dialog import BackupsDialog
    from launcher.ui.dialogs.game_dialog import AddGameDialog
    from launcher.ui.dialogs.import_dialog import ImportGamesDialog
    from launcher.ui.dialogs.saves_dialog import SavesDialog
    from launcher.ui.dialogs.settings_dialog import SettingsDialog

    app = qt_app()
    with sandbox() as ctx:
        ctx.games.add(GameConfig(name="Alpha", executable="/g/a.exe"))
        game = ctx.games.get("Alpha")
        library = LibraryController(ctx)

        for dialog in (
            AddGameDialog(ctx.paths),
            AddGameDialog(ctx.paths, game=game),
            SettingsDialog(ctx),
            ImportGamesDialog(ctx),
            ArtworkWizard(ctx, "Alpha"),
            BackupsDialog(ctx, library.saves, game_hint="Alpha"),
            SavesDialog(ctx, library.saves),
        ):
            dialog.show()
            app.processEvents()
            dialog.close()


@test
def editing_a_game_preserves_fields_the_form_hides() -> None:
    from launcher.domain.models import GameConfig
    from launcher.ui.dialogs.game_dialog import AddGameDialog

    qt_app()
    with sandbox() as ctx:
        original = GameConfig(
            name="Test Game",
            executable="/games/test.exe",
            winedebug="-all",
            vkd3d_config="dxr",
            radv_perftest="gpl",
            pulse_latency_msec="60",
            proton_use_wine_sync="1",
            prefix="prefixes/Test Game",
        )
        ctx.games.add(original)
        game = ctx.games.get("Test Game")
        assert game is not None

        edited = AddGameDialog(ctx.paths, game=game).get_config()
        for field in (
            "winedebug",
            "vkd3d_config",
            "radv_perftest",
            "pulse_latency_msec",
            "proton_use_wine_sync",
        ):
            assert getattr(edited, field) == getattr(original, field), field
        assert edited.prefix == "prefixes/Test Game"


@test
def stylesheet_covers_the_new_widgets() -> None:
    from launcher.ui.theme.qss import build_stylesheet

    sheet = build_stylesheet()
    for selector in ("QMainWindow", "#sidebar", "#detailPanel", "#gameList"):
        assert selector in sheet, selector


@test
def qt_can_write_the_artwork_formats() -> None:
    from PySide6.QtGui import QImageWriter

    qt_app()
    supported = {bytes(f).decode() for f in QImageWriter.supportedImageFormats()}
    for fmt in ("png", "jpg", "webp"):
        assert fmt in supported, f"{fmt} unsupported; artwork re-encode would fail"


# --------------------------------------------------------------------------
# friends
# --------------------------------------------------------------------------


@contextmanager
def friends_server():
    """A friends server on a free port, with an in-memory database."""
    import threading

    from server.api import make_server
    from server.db import Store

    store = Store(":memory:")
    server = make_server(store, "127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        store.close()


def _friends_pair(url: str):
    """Two registered users who are friends: (ana, bo) clients."""
    from launcher.services.friends_client import FriendsClient

    ana = FriendsClient(url)
    ana.token = ana.register("Ana")["token"]
    bo = FriendsClient(url)
    bo_profile = bo.register("Bo")
    bo.token = bo_profile["token"]
    ana.send_request(bo_profile["friend_code"].lower().replace("-", " "))
    incoming = bo.requests()["incoming"]
    assert [r["display_name"] for r in incoming] == ["Ana"], incoming
    bo.answer(incoming[0]["id"], True)
    return ana, bo


@test
def friends_game_key_matches_the_same_game() -> None:
    from launcher.domain.friends import game_key
    from launcher.domain.models import GameConfig

    assert game_key(GameConfig(name="ELDEN RING")) == game_key(GameConfig(name="Elden Ring"))
    assert game_key(GameConfig(name="Hades", game_id="1145360")) == "steam:1145360"
    # An override beats the launch id; the placeholder id means nothing.
    assert game_key(GameConfig(name="X", game_id="1", override_app_id="42")) == "steam:42"
    assert game_key(GameConfig(name="X", game_id="480")).startswith("name:")


@test
def friends_server_friendship_presence_and_leaderboards() -> None:
    import time as _time

    with friends_server() as url:
        ana, bo = _friends_pair(url)
        now = int(_time.time())
        long_ago = now - 60 * 86400
        bo.upload_sessions(
            [
                {"id": "b:1", "game_key": "name:hades", "game_name": "Hades",
                 "started": now - 100, "seconds": 3600},
                {"id": "b:2", "game_key": "name:celeste", "game_name": "Celeste",
                 "started": long_ago, "seconds": 7200},
            ]
        )
        ana.upload_sessions(
            [{"id": "a:1", "game_key": "name:hades", "game_name": "Hades",
              "started": now - 50, "seconds": 600}]
        )
        bo.set_presence("name:hades", "Hades")

        overview = ana.overview(now - 3600)
        (friend,) = overview["friends"]
        assert friend["display_name"] == "Bo"
        assert friend["presence"]["game_name"] == "Hades"
        assert friend["week_seconds"] == 3600
        assert friend["total_seconds"] == 10800
        assert [g["game_name"] for g in friend["top_games"]] == ["Celeste", "Hades"]
        shared = {g["game_key"]: g["players"] for g in overview["games"]}
        assert shared == {"name:hades": 2, "name:celeste": 1}, shared

        week = ana.leaderboard(now - 3600, None)
        assert [(r["display_name"], r["rank"]) for r in week] == [("Bo", 1), ("Ana", 2)]
        assert [r["is_me"] for r in week] == [False, True]
        all_time = ana.leaderboard(None, None)
        assert all_time[0]["seconds"] == 10800
        # Per game: only people who played it.
        celeste = ana.leaderboard(None, "name:celeste")
        assert [r["display_name"] for r in celeste] == ["Bo"]

        bo.clear_presence()
        assert ana.overview(None)["friends"][0]["presence"] is None


@test
def friends_server_shows_strangers_nothing() -> None:
    from launcher.services.friends_client import AuthError, FriendsClient

    with friends_server() as url:
        ana, bo = _friends_pair(url)
        eve = FriendsClient(url)
        eve.token = eve.register("Eve")["token"]
        bo.upload_sessions(
            [{"id": "b:1", "game_key": "k", "game_name": "G", "started": 1, "seconds": 60}]
        )
        assert eve.overview(None)["friends"] == []
        assert [r["display_name"] for r in eve.leaderboard(None, None)] == ["Eve"]
        # Unfriending hides each from the other.
        ana.unfriend(bo.me()["user_id"])
        assert ana.overview(None)["friends"] == []
        assert bo.overview(None)["friends"] == []
        # A request to a code that does not exist looks like any other.
        eve.send_request("ZZZZ-ZZZZ")
        try:
            FriendsClient(url, "not-a-token").overview(None)
        except AuthError:
            pass
        else:
            raise AssertionError("a bad token was accepted")


@test
def friends_uploads_are_idempotent_and_clearable() -> None:
    with friends_server() as url:
        ana, _bo = _friends_pair(url)
        batch = [
            {"id": "a:1", "game_key": "k1", "game_name": "One", "started": 1, "seconds": 60},
            {"id": "a:2", "game_key": "k2", "game_name": "Two", "started": 2, "seconds": 30},
        ]
        ana.upload_sessions(batch)
        ana.upload_sessions(batch)
        assert ana.overview(None)["me"]["total_seconds"] == 90
        ana.delete_sessions(["k1"])
        assert ana.overview(None)["me"]["total_seconds"] == 30
        ana.delete_sessions(None)
        assert ana.overview(None)["me"]["total_seconds"] == 0


@test
def friends_offline_mode_makes_no_calls() -> None:
    from launcher.domain.friends import FriendsState

    made: list[str] = []
    with sandbox() as ctx:
        service = ctx.friends
        service._client_factory = lambda url, token: made.append(url)  # type: ignore[assignment]
        assert ctx.settings.get_str("friends_mode") == "offline"
        service.start()
        ctx.state.record_session("Game", datetime.now(), 120)
        ctx.processes.game_started.emit("Game")
        ctx.processes.session_recorded.emit("Game", 120)
        service.refresh()
        service.sync_history()
        pump(lambda: False, timeout=0.2)
        assert made == [], made
        assert service.state is FriendsState.OFFLINE
        assert not ctx.paths.friends_file.exists()


@test
def friends_service_registers_uploads_and_shares_presence() -> None:
    from launcher.domain.friends import FriendsState, name_key
    from launcher.services.friends_client import FriendsClient

    with friends_server() as url, sandbox() as ctx:
        # History from before going online is uploaded too.
        ctx.state.record_session("Hades", datetime.now() - timedelta(days=40), 3600)
        ctx.settings.update({"friends_mode": "online", "friends_server_url": url})
        service = ctx.friends
        service.start()
        assert service.state is FriendsState.UNREGISTERED
        service.register("  Ana  ")
        pump(lambda: service.state is FriendsState.ONLINE)
        assert service.state is FriendsState.ONLINE, service.state
        assert service.account.display_name == "Ana"
        assert ctx.paths.friends_file.stat().st_mode & 0o077 == 0, "token file is readable"

        pump(lambda: service.account.uploaded_through > 0)
        bo = FriendsClient(url)
        bo_profile = bo.register("Bo")
        bo.token = bo_profile["token"]
        bo.send_request(service.account.friend_code)
        service.refresh()
        pump(lambda: service.snapshot is not None and bool(service.snapshot.incoming))
        snap = service.snapshot
        assert snap is not None and snap.me.total_seconds == 3600, snap
        service.answer(snap.incoming[0].id, True)
        pump(lambda: service.snapshot is not None and bool(service.snapshot.friends))

        # Presence: a game running from the launcher shows up for Bo.
        ctx.processes._sessions["Hades"] = object()  # type: ignore[assignment]
        ctx.processes.game_started.emit("Hades")
        playing: list = []

        def bo_sees_it() -> bool:
            playing[:] = [f["presence"] for f in bo.overview(None)["friends"]]
            return playing[0] is not None

        pump(bo_sees_it, timeout=3)
        assert playing[0]["game_key"] == name_key("Hades"), playing

        # Turning sharing off clears it.
        ctx.settings.set("friends_share_presence", False)
        pump(lambda: not bo_sees_it(), timeout=3)
        assert playing[0] is None
        ctx.processes._sessions.clear()

        # A local history clear reaches the server.
        from launcher.app import data_cleaner

        data_cleaner.clear(ctx, ["Hades"], {data_cleaner.DataKind.HISTORY})
        pump(lambda: bo.overview(None)["friends"][0]["total_seconds"] == 0, timeout=3)
        assert bo.overview(None)["friends"][0]["total_seconds"] == 0

        # Going offline stops everything.
        ctx.settings.set("friends_mode", "offline")
        assert service.state is FriendsState.OFFLINE
        assert not service._poll.isActive()


@test
def friends_service_survives_an_unreachable_server() -> None:
    from launcher.domain.friends import FriendsState
    from launcher.services.friends import Account

    with sandbox() as ctx:
        # A port nothing listens on.
        url = "http://127.0.0.1:9"
        ctx.friends._account = Account(server=url, token="t")  # noqa: S106
        ctx.settings.update({"friends_mode": "online", "friends_server_url": url})
        ctx.friends.start()
        pump(lambda: ctx.friends.state is FriendsState.UNREACHABLE)
        assert ctx.friends.state is FriendsState.UNREACHABLE
        assert ctx.friends._poll.isActive(), "no retry scheduled"


@test
def friends_tab_is_a_view_and_remembered() -> None:
    from launcher.app.main import build_window
    from launcher.domain.friends import FriendsSnapshot
    from launcher.ui.main_window import _FRIENDS_VIEW, _LIBRARY_VIEW

    app = qt_app()
    with sandbox() as ctx:
        window = build_window(ctx)
        window.show()
        app.processEvents()
        # Offline: the explainer, and no network.
        assert window._friends._pages.currentIndex() == 0
        window._switch_view(_FRIENDS_VIEW)
        assert ctx.settings.get_str("view_mode") == "friends"
        assert ctx.friends._visible
        window._switch_view(_LIBRARY_VIEW)
        window._switch_view(_FRIENDS_VIEW)
        window._restore_view_mode()
        assert window._views.currentIndex() == _FRIENDS_VIEW

        # Drawing a full snapshot must not fail.
        snap = FriendsSnapshot.parse(
            {
                "me": {"user_id": 1, "display_name": "Ana", "friend_code": "AAAA-BBBB"},
                "friends": [
                    {"user_id": 2, "display_name": "Bo", "last_seen": 1,
                     "presence": {"game_key": "k", "game_name": "Hades", "since": 1},
                     "week_seconds": 60, "total_seconds": 120,
                     "top_games": [{"game_key": "k", "game_name": "Hades", "seconds": 120}]},
                ],
                "games": [{"game_key": "k", "game_name": "Hades", "players": 2}],
            },
            {"incoming": [{"id": 3, "display_name": "Cy"}], "outgoing": []},
            [{"rank": 1, "user_id": 2, "display_name": "Bo", "seconds": 60}],
        )
        window._friends._render(snap)
        window._friends._show_page(3)
        window._friends.grab()
        assert window._friends._requests_card.isVisibleTo(window._friends)
        window.close()


# --------------------------------------------------------------------------


def main() -> int:
    print(f"\n{_PASSED} passed, {len(_FAILURES)} failed")
    for failure in _FAILURES:
        print("\n" + "-" * 60 + "\n" + failure)
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
