"""Update feed comparison and safety."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def update_versions_compare_numerically() -> None:
        from launcher.services.updates import current_version, is_newer

        assert is_newer("2.2.0", "2.1.0")
        assert is_newer("2.10.0", "2.9.0")
        assert not is_newer("2.1.0", "2.1.0")
        assert not is_newer("2.1.0", "2.2.0")
        assert current_version()

    @test
    def update_check_never_raises_and_rejects_schemes() -> None:
        from launcher.services.updates import check, fetch_feed

        assert not check("").available
        assert not check("not a url").available
        try:
            fetch_feed("file:///etc/passwd")
        except ValueError:
            pass
        else:
            raise AssertionError("file: feed accepted")
        assert not check("http://127.0.0.1:1/nope", "2.1.0").available
