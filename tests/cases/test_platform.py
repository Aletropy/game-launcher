"""Windows sub-app vs Linux main: platform gating, save discovery, assets."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def platform_gate_is_centralised() -> None:
        from launcher import platform

        assert platform.app_platform() in ("linux", "windows", "unknown")
        # On this CI box we are on Linux; the gate itself is what matters.
        if not platform.is_windows():
            assert platform.is_linux()
            assert not platform.is_windows()

    @test
    def win_save_discovery_matches_names_only() -> None:
        import tempfile
        from pathlib import Path

        from launcher.services import win_saves

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Elden Ring").mkdir()
            (root / "Elden Ring" / "save.sav").write_text("data")
            (root / "Unrelated").mkdir()

            hits = win_saves.discover("Elden Ring", roots_override=[root])
            names = [h.path.name for h in hits]
            assert "Elden Ring" in names
            assert "Unrelated" not in names

            store = root / "store"
            conflicts = root / "conflicts"
            stats = win_saves.mirror_game(
                "Elden Ring", [root / "Elden Ring"], store, conflicts
            )
            # Copy-only: the native folder keeps its files.
            assert (root / "Elden Ring" / "save.sav").read_text() == "data"
            assert (store / "Elden-Ring" / "Elden Ring" / "save.sav").is_file()
            assert stats["mirrored"] >= 1
            assert stats["errors"] == 0

    @test
    def win_save_mirror_never_escapes_the_store() -> None:
        import tempfile
        from pathlib import Path

        from launcher.services import win_saves

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Game").mkdir()
            (root / "Game" / "s.sav").write_text("live")
            win_saves.mirror_game("../../evil", [root / "Game"], root / "store", root / "conf")
            assert not (root / "evil").exists()
            # The hostile name is slugified to a single directory inside the store.
            subdirs = [p for p in (root / "store").iterdir() if p.is_dir()]
            assert len(subdirs) == 1
            assert subdirs[0].resolve().parent == (root / "store").resolve()

    @test
    def update_assets_are_per_platform() -> None:
        from launcher.services.updates import installer_dest, parse_release, pick_asset

        payload = {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/x/y",
            "body": "notes",
            "assets": [
                {
                    "name": "milso-launcher-9.9.9.run",
                    "browser_download_url": "https://github.com/x/milso-launcher-9.9.9.run",
                    "size": 1,
                },
                {
                    "name": "milso-launcher-9.9.9-win.zip",
                    "browser_download_url": "https://github.com/x/milso-launcher-9.9.9-win.zip",
                    "size": 2,
                },
            ],
        }
        url, _size, asset = pick_asset(payload, "9.9.9", "linux")
        assert asset.endswith(".run") and url.endswith(".run")
        url, _size, asset = pick_asset(payload, "9.9.9", "windows")
        assert asset.endswith("-win.zip") and url.endswith("-win.zip")

        assert parse_release(payload, "1.0.0", "linux").asset.endswith(".run")
        assert parse_release(payload, "1.0.0", "windows").asset.endswith("-win.zip")
        assert installer_dest("9.9.9", "windows").name.endswith("-win.zip")
        assert installer_dest("9.9.9", "linux").name.endswith(".run")

        try:
            pick_asset({"assets": []}, "9.9.9", "windows")
        except ValueError:
            pass
        else:
            raise AssertionError("empty assets accepted")

    @test
    def server_platform_labels_are_allowlisted() -> None:
        from server.db import normalise_platform

        assert normalise_platform("Windows") == "windows"
        assert normalise_platform("linux") == "linux"
        assert normalise_platform("evil-os") == "unknown"
        assert normalise_platform("") == "unknown"
        assert normalise_platform(None) == "unknown"
