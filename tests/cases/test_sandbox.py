"""Dev sandbox: ./run.sh stays inside the project, never in ~/.local."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def sandbox_paths_stay_inside_the_project() -> None:
        from launcher.data.paths import PROJECT_ROOT, Paths

        box = Paths.sandbox()
        assert box.base == PROJECT_ROOT
        assert PROJECT_ROOT in box.config.parents
        assert PROJECT_ROOT in box.data.parents
        assert box.config != box.data

        prod = Paths.production()
        assert box.config != prod.config
        assert box.data != prod.data

    @test
    def default_honours_the_sandbox_env() -> None:
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from launcher.data.paths import PROJECT_ROOT, Paths

        with tempfile.TemporaryDirectory() as d:
            fake_cfg = str(Path(d) / "cfg")
            fake_data = str(Path(d) / "data")
            with mock.patch.dict(
                os.environ,
                {
                    "MILSO_SANDBOX": "1",
                    "XDG_CONFIG_HOME": fake_cfg,
                    "XDG_DATA_HOME": fake_data,
                },
                clear=False,
            ):
                box = Paths.default()
                # XDG is ignored: everything stays under the project.
                assert box.config.parent == PROJECT_ROOT / ".sandbox"
                assert box.data.parent == PROJECT_ROOT / ".sandbox"
            with mock.patch.dict(
                os.environ,
                {
                    "MILSO_SANDBOX": "0",
                    "XDG_CONFIG_HOME": fake_cfg,
                    "XDG_DATA_HOME": fake_data,
                },
                clear=False,
            ):
                prod = Paths.default()
                assert prod.config == Path(fake_cfg) / "milso-launcher"
                assert prod.data == Path(fake_data) / "milso-launcher"

    @test
    def sandbox_seed_copies_settings_and_state_but_not_identity() -> None:
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from launcher.data.paths import seed_sandbox_from_production

        with tempfile.TemporaryDirectory() as d:
            box_root = Path(d) / "box"
            # Production paths append milso-launcher; lay the fakes out so.
            fake_prod_cfg = Path(d) / "cfgbase" / "milso-launcher"
            fake_prod_data = Path(d) / "database" / "milso-launcher"
            fake_prod_cfg.mkdir(parents=True)
            (fake_prod_cfg / "themes").mkdir(exist_ok=True)
            (fake_prod_cfg / "settings.json").write_text('{"theme": "ember"}')
            (fake_prod_cfg / "themes" / "mine.json").write_text("{}")
            (fake_prod_cfg / "friends.json").write_text('{"token": "secret"}')
            fake_prod_data.mkdir(parents=True)
            (fake_prod_data / "state.db").write_bytes(b"sqlite")
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(Path(d) / "cfgbase"),
                    "XDG_DATA_HOME": str(Path(d) / "database"),
                    "MILSO_SANDBOX_DIR": str(box_root),
                },
                clear=False,
            ):
                copied = seed_sandbox_from_production()
                assert "config/settings.json" in copied
                assert "config/themes/mine.json" in copied
                assert "data/state.db" in copied
                assert (box_root / "config" / "settings.json").is_file()
                assert (box_root / "data" / "state.db").is_file()
                # The server identity must not follow into the sandbox.
                assert not (box_root / "config" / "friends.json").exists()
                # Second run is a no-op.
                assert seed_sandbox_from_production() == []

    @test
    def update_cache_and_single_instance_follow_the_sandbox() -> None:
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from launcher.app.single_instance import _default_names
        from launcher.services import updates

        with tempfile.TemporaryDirectory() as d:
            box_root = str(Path(d) / "box")
            with mock.patch.dict(
                os.environ,
                {"MILSO_SANDBOX": "1", "MILSO_SANDBOX_DIR": box_root},
                clear=False,
            ):
                assert str(updates.update_cache_dir()).startswith(box_root)
                assert updates.update_cache_dir().name == "updates"
                _, server = _default_names()
                assert "dev" in server
            with mock.patch.dict(os.environ, {"MILSO_SANDBOX": "0"}, clear=False):
                _, server = _default_names()
                assert "dev" not in server

    @test
    def run_argv_flags_toggle_sandbox_and_strip() -> None:
        import os
        from unittest import mock

        import run

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MILSO_SANDBOX", None)
            argv = ["run.py", "--sandbox", "--play", "Hades"]
            assert run.apply_sandbox_argv(argv) is False
            assert argv == ["run.py", "--play", "Hades"]
            assert os.environ["MILSO_SANDBOX"] == "1"

            argv = ["run.py", "--seed", "--no-sandbox"]
            assert run.apply_sandbox_argv(argv) is True
            assert argv == ["run.py"]
            assert os.environ["MILSO_SANDBOX"] == "0"
