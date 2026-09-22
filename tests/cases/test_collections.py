"""Tags, notes, hidden games and their filters."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def tags_normalize_and_match() -> None:
        from launcher.domain.models import normalize_tags

        assert normalize_tags("RPG, co-op;rpg , ") == ("rpg", "co-op")
        assert normalize_tags(["A", "a", "B"]) == ("a", "b")

    @test
    def collections_round_trip_through_state() -> None:
        with sandbox() as ctx:
            ctx.state.set_tags("Alpha", ("rpg", "backlog"))
            ctx.state.set_notes("Alpha", "  great build  ")
            ctx.state.set_hidden("Alpha", True)
            stats = ctx.state.get("Alpha")
            assert stats.tags == ("backlog", "rpg"), stats.tags
            assert stats.notes == "great build"
            assert stats.hidden
            assert ctx.state.all_tags() == ["backlog", "rpg"]
            ctx.state.clear_collections(["Alpha"])
            assert ctx.state.get("Alpha").tags == ()
            assert not ctx.state.get("Alpha").hidden

    @test
    def hidden_games_filter_and_search_by_tag() -> None:
        from launcher.app.library_controller import LibraryController
        from launcher.domain.library_filter import LibraryFilter
        from launcher.domain.models import GameConfig

        with sandbox() as ctx:
            ctx.games.add(GameConfig(name="Seen", executable="/g/s.exe"))
            ctx.games.add(GameConfig(name="Hid", executable="/g/h.exe"))
            lib = LibraryController(ctx)
            lib.reload()
            lib.set_tags("Hid", "rpg, stealth")
            lib.set_hidden("Hid", True)
            assert [g.name for g in lib.visible_games()] == ["Seen"]
            assert lib.all_tags() == ["rpg", "stealth"]

            lib.set_filter(lib.filter.with_(show_hidden=True))
            assert {g.name for g in lib.visible_games()} == {"Seen", "Hid"}

            filt = LibraryFilter(tags=("rpg",), show_hidden=True)
            assert [g.name for g in lib.games if filt.matches(g)] == ["Hid"]
            assert filt.to_json()["tags"] == ["rpg"]
            assert LibraryFilter.from_json(filt.to_json()).tags == ("rpg",)

            lib.set_search("stea")
            assert [g.name for g in lib.visible_games()] == ["Hid"]
