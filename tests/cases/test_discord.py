"""Discord Rich Presence and the game-folder shortcut."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def discord_templates_render_every_variable() -> None:
        from launcher.services.discord import format_elapsed, format_template, game_key

        assert game_key("Elden Ring: Nightreign!") == "elden_ring_nightreign"
        assert game_key("!!!") == "game"
        assert format_elapsed(45) == "45s"
        assert format_elapsed(600) == "10m"
        assert format_elapsed(3723) == "1h 02m"
        rendered = format_template(
            "Playing {game} [{game_key}] {elapsed}/{total} {platform}",
            game="Hades", key="hades", elapsed=90, total=3600, platform="linux",
        )
        assert rendered == "Playing Hades [hades] 1m/1h linux"
        # Unknown placeholders survive untouched.
        assert format_template("Hi {nope}", game="X") == "Hi {nope}"

    @test
    def discord_stays_silent_until_enabled_with_an_app_id() -> None:
        from launcher.services.discord import DiscordService

        made: list[str] = []

        class FakePresence:
            def __init__(self, app_id: str) -> None:
                made.append(app_id)

            def connect(self) -> None:
                pass

            def update(self, **kwargs: object) -> None:
                pass

            def clear(self) -> None:
                pass

            def close(self) -> None:
                pass

        with sandbox() as ctx:
            service = DiscordService(
                ctx.settings, ctx.processes, state=ctx.state,
                presence_factory=FakePresence,
            )
            service.start()
            assert made == [], "connected while disabled"
            ctx.settings.set("discord_app_id", "123")
            service.start()
            assert made == [], "connected without being enabled"
            # Enabling connects live through the settings-changed handler.
            ctx.settings.set("discord_enabled", True)
            assert made == ["123"], made
            service.stop()

    @test
    def discord_updates_on_launch_and_clears_when_idle() -> None:
        from launcher.services.discord import DiscordService

        calls: list[tuple] = []

        class FakePresence:
            def __init__(self, _app_id: str) -> None:
                pass

            def connect(self) -> None:
                pass

            def update(self, **kwargs) -> None:
                calls.append(("update", kwargs))

            def clear(self) -> None:
                calls.append(("clear", {}))

            def close(self) -> None:
                pass

        with sandbox() as ctx:
            ctx.settings.update({"discord_enabled": True, "discord_app_id": "123"})
            service = DiscordService(
                ctx.settings, ctx.processes, state=ctx.state,
                presence_factory=FakePresence,
            )
            service.start()
            assert service.connected

            ctx.processes._sessions["Hades"] = type("_S", (), {})()
            ctx.processes._sessions["Hades"].process = object()
            import time as _time

            ctx.processes._sessions["Hades"].started_at = _time.monotonic() - 65
            from datetime import datetime as _dt

            ctx.processes._sessions["Hades"].started_wall = _dt.now()
            ctx.processes._sessions["Hades"].pid = None
            ctx.processes._sessions["Hades"].watcher_pid = None
            service._on_game_started("Hades")
            updates = [c for c in calls if c[0] == "update"]
            assert updates, calls
            payload = updates[-1][1]
            assert payload["details"] == "Playing Hades"
            assert payload["large_image"] == "hades"
            assert "start" in payload, "elapsed timestamp missing"

            del ctx.processes._sessions["Hades"]
            service._on_game_finished("Hades", 0)
            assert any(c[0] == "clear" for c in calls), calls
            service.stop()

    @test
    def discord_connect_failure_retries_quietly() -> None:
        from launcher.services.discord import DiscordService

        with sandbox() as ctx:
            ctx.settings.update({"discord_enabled": True, "discord_app_id": "123"})

            def _boom(_app_id: str):
                raise RuntimeError("no Discord here")

            service = DiscordService(
                ctx.settings, ctx.processes, presence_factory=_boom,
            )
            notices: list[str] = []
            service.notice.connect(notices.append)
            service.start()
            assert not service.connected
            assert notices, "failure should surface as a notice, not an exception"
            service.stop()

    @test
    def game_folder_points_at_the_executable_parent() -> None:
        from launcher.services.discord import game_dir

        assert game_dir("") == ""
        assert game_dir("/g/Games/Hades/Hades.exe").replace("\\", "/").endswith("Games/Hades")

    @test
    def detail_menu_offers_open_game_folder() -> None:
        from launcher.app.main import build_window
        from launcher.domain.models import GameConfig
        from launcher.services import prefix_tools as pt

        app = qt_app()
        with sandbox() as ctx:
            exedir = ctx.paths.base / "exes"
            exedir.mkdir(parents=True, exist_ok=True)
            (exedir / "A.exe").write_bytes(b"\0")
            ctx.games.add(GameConfig(name="Alpha", executable=str(exedir / "A.exe")))
            window = build_window(ctx)
            window.show()
            app.processEvents()
            window._sidebar.select_game("Alpha")
            app.processEvents()
            menu = window._detail._more_btn.menu()
            assert menu is not None
            labels = [a.text() for a in menu.actions()]
            assert "Open game folder" in labels, labels

            fired: list[str] = []
            window._detail.game_folder_requested.connect(fired.append)
            opened: list[str] = []
            original = pt.open_path
            pt.open_path = lambda p: opened.append(str(p)) or True
            try:
                for action in menu.actions():
                    if action.text() == "Open game folder":
                        action.trigger()
                app.processEvents()
            finally:
                pt.open_path = original
            assert fired == ["Alpha"], fired
            assert opened == [str(exedir)], opened
            window.close()
