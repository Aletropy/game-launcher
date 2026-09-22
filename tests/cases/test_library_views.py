"""Desktop shortcuts, covers view and the sessions ledger."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path


def register(*, test, qt_app, sandbox, pump):
    @test
    def desktop_shortcuts_create_remove_and_rename() -> None:
        from launcher.services import shortcuts

        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            path = shortcuts.create("Hades II", directory=directory)
            assert path.is_file()
            text = path.read_text(encoding="utf-8")
            assert "[Desktop Entry]" in text and "--play" in text and "Hades II" in text
            assert shortcuts.exists("Hades II", directory)
            assert shortcuts.remove("Hades II", directory)
            assert not shortcuts.exists("Hades II", directory)
            assert not shortcuts.remove("Hades II", directory)
            assert shortcuts.slug("Warhammer 40,000!") == "warhammer-40-000"

    @test
    def covers_view_toggles_layout() -> None:
        from launcher.app.main import build_window
        from launcher.domain.models import GameConfig

        qt_app()
        with sandbox() as ctx:
            ctx.games.add(GameConfig(name="Alpha", executable="/g/a.exe"))
            window = build_window(ctx)
            sidebar = window._sidebar
            assert not sidebar.covers
            sidebar.set_covers(True)
            assert sidebar.covers
            assert "Alpha" in (sidebar.selected_game() or "")
            sidebar.set_covers(False)
            assert not sidebar.covers
            window.close()

    @test
    def sessions_dialog_lists_edits_and_adds() -> None:
        from launcher.domain.models import GameConfig
        from launcher.ui.dialogs.sessions_dialog import SessionsDialog

        qt_app()
        with sandbox() as ctx:
            ctx.games.add(GameConfig(name="Alpha", executable="/g/a.exe"))
            ctx.state.add_playtime("Alpha", 3600)
            first = ctx.state.record_session("Alpha", datetime(2026, 9, 1, 20, 0), 3600)
            dialog = SessionsDialog(ctx, "Alpha")
            assert dialog._list.count() == 1
            dialog._list.setCurrentRow(0)
            assert dialog._selected_id() == first
            dialog.reject()
            assert ctx.state.delete_session(first) == ("Alpha", 3600)
            assert ctx.state.total_playtime(["Alpha"]) == 0

    @test
    def steam_library_parses_manifests() -> None:
        from launcher.services.steam_import import already_known, scan_steam_libraries

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            steamapps = root / "steamapps"
            common = steamapps / "common" / "Hades"
            common.mkdir(parents=True)
            exe = common / "Hades.exe"
            exe.write_bytes(b"\0" * 200_000)
            (steamapps / "appmanifest_123.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"123"\n\t"name"\t\t"Hades"\n'
                '\t"installdir"\t\t"Hades"\n}\n'
            )
            (steamapps / "libraryfolders.vdf").write_text(
                '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                + str(root)
                + '"\n\t}\n}\n'
            )
            games = scan_steam_libraries([root])
            assert len(games) == 1, games
            assert games[0].name == "Hades" and games[0].app_id == "123"
            assert games[0].best is not None
            assert already_known(games[0], {"hades"}, set())
            assert not already_known(games[0], {"Other"}, set())

    @test
    def organize_dialog_returns_tags_and_notes() -> None:
        from launcher.ui.dialogs.organize_dialog import OrganizeDialog

        qt_app()
        dialog = OrganizeDialog("Alpha", ("rpg",), "old", parent=None)
        assert dialog.get_tags() == "rpg"
        assert dialog.get_notes() == "old"
        dialog.reject()
