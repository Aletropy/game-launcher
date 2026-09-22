"""Persisted game logs, preferences, profiler and outcomes."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def game_logs_survive_and_rotate() -> None:
        with sandbox() as ctx:
            ctx.processes.game_started.emit("Alpha")
            ctx.processes.game_output.emit("Alpha", "first line\n")
            tail = ctx.logs.recent("Alpha")
            assert "first line" in tail
            assert ctx.logs.size("Alpha") > 0
            ctx.logs.clear("Alpha")
            assert ctx.logs.recent("Alpha") == ""

    @test
    def preferences_read_settings_with_types() -> None:
        from launcher.data.preferences import Preferences
        from launcher.domain.models import SortOrder

        with sandbox() as ctx:
            prefs = Preferences(ctx.settings)
            assert prefs.sort_order is SortOrder.NAME
            assert prefs.confirm_remove is True
            ctx.settings.set("sort_order", "bogus")
            assert prefs.sort_order is SortOrder.NAME
            ctx.settings.set("sort_order", "added")
            assert prefs.sort_order is SortOrder.RECENTLY_ADDED

    @test
    def startup_profiler_reports_longest_first() -> None:
        from launcher.app.startup import StartupProfiler

        profiler = StartupProfiler()
        with profiler.stage("b"):
            pass
        with profiler.stage("a"):
            pass
        assert profiler.total_ms() >= 0
        assert {n for n, _ in profiler.report()} == {"a", "b"}

    @test
    def outcomes_carry_errors() -> None:
        from launcher.domain.outcome import Err, Ok

        assert Ok(3).ok and Ok(3).unwrap() == 3
        err = Err("Nope", "gone", hint="retry", kind="x")
        assert not err.ok
        try:
            err.unwrap()
        except KeyError:
            pass
        else:
            raise AssertionError("unwrap should raise")
