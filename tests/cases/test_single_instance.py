"""Single-instance lock, forwarding and argument parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path


def register(*, test, qt_app, sandbox, pump):
    from launcher.app.main import parse_launch_request

    @test
    def single_instance_lock_and_forward() -> None:
        from launcher.app.single_instance import SingleInstance

        qt_app()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = SingleInstance(root / "a.lock", "test-milso-single-1")
            assert first.try_acquire()
            second = SingleInstance(root / "a.lock", "test-milso-single-1")
            assert not second.try_acquire()

            received: list[str] = []
            first.message_received.connect(received.append)
            assert second.forward(["show", "play:Hades"])
            pump(lambda: len(received) == 2)
            assert received == ["show", "play:Hades"], received
            second.release()
            first.release()

    @test
    def launch_request_parsing() -> None:
        assert parse_launch_request(["milso"]) == (None, False)
        assert parse_launch_request(["milso", "--play", "Hades"]) == ("Hades", False)
        assert parse_launch_request(["milso", "Hades"]) == ("Hades", False)
        assert parse_launch_request(["milso", "--profile"]) == (None, True)
        assert parse_launch_request(["milso", "--play"]) == (None, False)
        assert parse_launch_request(["milso", "--check"]) == (None, False)
