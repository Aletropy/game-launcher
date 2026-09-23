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

    @test
    def win_default_paths_do_not_raise_and_migrate_siblings() -> None:
        """Regression: Paths.default() crashed on Windows (UnboundLocalError)."""
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from launcher import platform as _platform
        from launcher.data.paths import Paths

        with tempfile.TemporaryDirectory() as d:
            roaming = Path(d) / "Roaming"
            local = Path(d) / "Local"
            (roaming / "launcher").mkdir(parents=True)
            (roaming / "launcher" / "settings.json").write_text("{}")
            (local / "launcher").mkdir(parents=True)
            (local / "launcher" / "state.db").write_bytes(b"db")
            env = {
                "APPDATA": str(roaming),
                "LOCALAPPDATA": str(local),
                "XDG_CONFIG_HOME": "",
                "XDG_DATA_HOME": "",
                "XDG_CACHE_HOME": "",
            }
            with mock.patch.object(
                _platform, "is_windows", return_value=True
            ), mock.patch.dict(os.environ, env, clear=False):
                # Blank XDG vars must not shadow the Windows locations.
                os.environ.pop("XDG_CONFIG_HOME", None)
                os.environ.pop("XDG_DATA_HOME", None)
                os.environ.pop("XDG_CACHE_HOME", None)
                paths = Paths.default()
            assert paths.config == roaming / "milso-launcher"
            assert paths.data == local / "milso-launcher"
            assert (paths.config / "settings.json").is_file()
            assert (paths.data / "state.db").is_file()

    @test
    def win_xdg_overrides_keep_the_app_suffix() -> None:
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from launcher import platform as _platform

        with tempfile.TemporaryDirectory() as d, mock.patch.object(
            _platform, "is_windows", return_value=True
        ), mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(Path(d) / "cfg"),
                "XDG_DATA_HOME": str(Path(d) / "data"),
                "XDG_CACHE_HOME": str(Path(d) / "cache"),
            },
            clear=False,
        ):
                assert _platform.config_home().name == "milso-launcher"
                assert _platform.data_home().name == "milso-launcher"
                assert _platform.cache_home().parent.name == "milso-launcher"

    @test
    def win_update_cache_dir_is_not_doubled() -> None:
        from unittest import mock

        from launcher import platform as _platform
        from launcher.services import updates

        with mock.patch.object(_platform, "is_windows", return_value=True):
            parts = updates.update_cache_dir().parts
            assert parts.count("milso-launcher") == 1, updates.update_cache_dir()
            assert updates.update_cache_dir().name == "updates"

    @test
    def win_zip_ships_a_top_level_installer() -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        assert (root / "installer" / "setup-win.bat").is_file()
        assert (root / "installer" / "setup-win.ps1").is_file()
        # Both entry points must resolve the payload dir instead of
        # assuming the script folder is the payload root.
        bat = (root / "installer" / "setup-win.bat").read_text(encoding="utf-8")
        assert "..\\requirements.txt" in bat or ".." in bat
        assert "requirements.txt" in bat
        ps1 = (root / "installer" / "setup-win.ps1").read_text(encoding="utf-8")
        assert 'Join-Path $src ".."' in ps1 or "requirements.txt" in ps1
        # package.sh must promote the installers to the zip root.
        pkg = (root / "package.sh").read_text(encoding="utf-8")
        assert "setup-win.bat\" \"$win_staging/setup-win.bat\"" in pkg or (
            "setup-win.bat" in pkg and "$win_staging/setup-win" in pkg
        )
