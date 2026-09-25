"""What's new after an update, and the locked-in Discord App ID."""

from __future__ import annotations


def register(*, test, qt_app, sandbox, pump):
    @test
    def changelog_shows_only_on_real_upgrades() -> None:
        from launcher.services.changelog import should_show

        assert should_show("", "2.6.0") is False, "first run must stay silent"
        assert should_show("2.6.0", "2.6.0") is False
        assert should_show("2.6.0", "2.5.0") is False, "downgrades stay silent"
        assert should_show("2.6.0", "unknown") is False
        assert should_show("2.5.0", "2.6.0") is True
        assert should_show("v2.5.0", "2.6.0") is True, "tags compare too"

    @test
    def pending_notes_round_trip_and_are_consumed() -> None:
        import tempfile
        from pathlib import Path

        from launcher.services import changelog as cl

        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            assert cl.take_pending(data) is None
            cl.stash_pending(data, "2.6.0", "Hello", "https://example.com")
            peeked = cl.peek_pending(data)
            assert peeked is not None and peeked.notes == "Hello"
            # Peeking leaves the file; taking consumes it.
            assert cl.peek_pending(data) is not None
            taken = cl.take_pending(data)
            assert taken is not None and taken.version == "2.6.0"
            assert taken.page_url == "https://example.com"
            assert cl.take_pending(data) is None
            assert not cl.pending_path(data).exists()

    @test
    def corrupt_pending_notes_are_dropped() -> None:
        import tempfile
        from pathlib import Path

        from launcher.services import changelog as cl

        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            cl.pending_path(data).write_text("{not json")
            assert cl.take_pending(data) is None
            assert not cl.pending_path(data).exists(), "junk must not linger"

    @test
    def changelog_fetch_never_raises_without_network() -> None:
        from launcher.services import changelog as cl

        assert cl.fetch_notes_for("", "2.6.0") is None
        assert cl.fetch_notes_for("!!/bad", "2.6.0") is None
        assert cl.fetch_notes_for("owner/name", "") is None
        assert cl.releases_page("").endswith("/releases")

    @test
    def changelog_dialog_builds_with_and_without_notes() -> None:
        from launcher.ui.dialogs.changelog_dialog import ChangelogDialog

        qt_app()
        full = ChangelogDialog("2.6.0", "Some notes", "https://example.com")
        assert "2.6.0" in full.windowTitle()
        empty = ChangelogDialog("2.6.0", "")
        assert "2.6.0" in empty.windowTitle()

    @test
    def offer_changelog_shows_once_after_an_upgrade() -> None:
        from launcher.app.main import build_window
        from launcher.services import changelog as cl
        from launcher.ui.dialogs import changelog_dialog as dlg_module

        app = qt_app()
        with sandbox() as ctx:
            ctx.settings.set("last_seen_version", "0.0.0")
            cl.stash_pending(ctx.paths.data, "9.9.9", "Stashed notes", "")
            window = build_window(ctx)
            window.show()
            app.processEvents()

            shown: list[tuple] = []
            original = dlg_module.ChangelogDialog
            dlg_module.ChangelogDialog = lambda *a, **k: shown.append((a, k)) or _Closed()
            try:
                window.offer_changelog()
                app.processEvents()
            finally:
                dlg_module.ChangelogDialog = original
            assert len(shown) == 1, shown
            assert "Stashed notes" in shown[0][0], shown
            assert not cl.pending_path(ctx.paths.data).exists(), "stash not consumed"

            # Second startup: same version, silent.
            shown.clear()
            dlg_module.ChangelogDialog = lambda *a, **k: shown.append((a, k)) or _Closed()
            try:
                window.offer_changelog()
                app.processEvents()
            finally:
                dlg_module.ChangelogDialog = original
            assert shown == [], shown
            window.close()

    @test
    def settings_about_reopens_whats_new() -> None:
        from PySide6.QtWidgets import QPushButton

        from launcher.ui.dialogs import changelog_dialog as dlg_module
        from launcher.ui.dialogs.settings_dialog import SettingsDialog

        qt_app()
        with sandbox() as ctx:
            from launcher.services import changelog as cl

            cl.stash_pending(ctx.paths.data, "x", "Stashed", "")
            dialog = SettingsDialog(ctx, page="about")
            buttons = {
                b.text(): b for b in dialog.findChildren(QPushButton)
            }
            assert "What's new" in buttons, sorted(buttons)
            shown: list[tuple] = []
            original = dlg_module.ChangelogDialog
            dlg_module.ChangelogDialog = lambda *a, **k: shown.append((a, k)) or _Closed()
            try:
                buttons["What's new"].click()
            finally:
                dlg_module.ChangelogDialog = original
            assert len(shown) == 1, shown
            dialog.close()

    @test
    def discord_settings_no_longer_take_an_app_id() -> None:
        from launcher.ui.dialogs.settings_dialog import SettingsDialog

        qt_app()
        with sandbox() as ctx:
            dialog = SettingsDialog(ctx, page="discord")
            assert not hasattr(dialog, "_discord_app_id"), "field was not removed"
            assert dialog._discord_enabled is not None
            dialog.close()
            # The baked-in ID survives a save untouched.
            assert (
                ctx.settings.get_str("discord_app_id") == "1553159875318517882"
            )


class _Closed:
    """A stub dialog whose exec() is already dismissed."""

    def exec(self) -> int:
        return 0
