"""Friends in-common games and shared form pieces."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from launcher.domain.friends import Friend, GameTotal, common_games
from launcher.ui.widgets.forms import Card, button_row, hint


def _local_name(key: str) -> str | None:
    return {"hades": "Hades"}.get(key)


def _local_seconds(key: str) -> int:
    return {"hades": 3600}.get(key, 0)


def register(*, test, qt_app, sandbox, pump):
    @test
    def common_games_match_by_key_and_sort() -> None:
        friends = [
            Friend(
                user_id=2,
                name="Bo",
                top_games=(
                    GameTotal(key="hades", name="Hades", seconds=120),
                    GameTotal(key="other", name="Other", seconds=999),
                ),
            ),
            Friend(
                user_id=3,
                name="Cy",
                top_games=(GameTotal(key="hades", name="Hades", seconds=60),),
            ),
        ]
        common = common_games(
            friends,
            local_name=_local_name,
            local_seconds=_local_seconds,
        )
        assert len(common) == 1, common
        game = common[0]
        assert game.name == "Hades"
        assert game.friend_names == ("Bo", "Cy")
        assert game.friends_seconds == 180
        assert game.mine_seconds == 3600
        assert common_games([], local_name=_local_name) == []

    @test
    def shared_form_pieces_keep_object_names() -> None:
        qt_app()
        card = Card("Title")
        assert card.objectName() == "settingsCard"
        assert card.form is not None
        assert hint("x").objectName() == "hintLabel"
        row = button_row(QPushButton("A"))
        assert row.count() == 2
