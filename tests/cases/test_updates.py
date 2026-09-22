"""GitHub Releases auto-updates: parsing, safety and UI wiring."""

from __future__ import annotations

from datetime import datetime, timedelta


def _payload(version: str = "v9.9.9") -> dict:
    return {
        "tag_name": version,
        "html_url": "https://github.com/Aletropy/milso-launcher/releases/tag/v9.9.9",
        "body": "Fixes and speed.",
        "assets": [
            {"name": "SHA256SUMS", "browser_download_url": "https://github.com/x/SHA256SUMS"},
            {
                "name": "milso-launcher-9.9.9.run",
                "browser_download_url": "https://github.com/x/milso-launcher-9.9.9.run",
                "size": 12345,
            },
            {
                "name": "milso-launcher-9.9.9.tar.gz",
                "browser_download_url": "https://github.com/x/milso-launcher-9.9.9.tar.gz",
                "size": 999,
            },
        ],
    }


def register(*, test, qt_app, sandbox, pump):
    @test
    def update_versions_compare_numerically() -> None:
        from launcher.services.updates import current_version, is_newer, normalize_version

        assert is_newer("2.2.0", "2.1.0")
        assert is_newer("2.10.0", "2.9.0")
        assert is_newer("v2.2.0", "2.1.0")
        assert not is_newer("2.1.0", "2.1.0")
        assert not is_newer("2.1.0", "v2.1.0")
        assert not is_newer("2.1.0", "2.2.0")
        assert normalize_version("  v2.3.0 ") == "2.3.0"
        assert current_version()

    @test
    def update_release_parsing_picks_the_run_asset() -> None:
        from launcher.services.updates import parse_release, pick_run_asset, release_api_url

        url, size = pick_run_asset(_payload(), "9.9.9")
        assert url.endswith("milso-launcher-9.9.9.run")
        assert size == 12345

        info = parse_release(_payload(), "2.2.0")
        assert info.available and info.version == "9.9.9"
        assert info.url.endswith(".run")
        assert info.page_url.startswith("https://github.com/")
        assert info.notes == "Fixes and speed."

        assert not parse_release(_payload(), "9.9.9").available
        assert not parse_release(_payload(), "10.0.0").available

        try:
            pick_run_asset({"assets": []}, "9.9.9")
        except ValueError:
            pass
        else:
            raise AssertionError("empty assets accepted")

        try:
            release_api_url("not a repo!!")
        except ValueError:
            pass
        else:
            raise AssertionError("bad repo accepted")

    @test
    def update_check_never_raises_and_rejects_schemes() -> None:
        from launcher.services import updates
        from launcher.services.updates import check, check_download_url, fetch_feed

        assert not updates.check_github("").available
        assert not updates.check_github("not a repo").available
        # A broken network must surface as "no update", never raise.
        original = updates.fetch_release
        updates.fetch_release = lambda *a: (_ for _ in ()).throw(OSError("down"))  # type: ignore[assignment]
        try:
            assert not updates.check_github("Aletropy/milso-launcher", "1.0.0").available
        finally:
            updates.fetch_release = original
        assert not check("").available
        assert not check("not a url").available
        try:
            fetch_feed("file:///etc/passwd")
        except ValueError:
            pass
        else:
            raise AssertionError("file: feed accepted")
        assert not check("http://127.0.0.1:1/nope", "2.1.0").available

        try:
            check_download_url("http://github.com/x/y.run")
        except ValueError:
            pass
        else:
            raise AssertionError("http asset accepted")
        try:
            check_download_url("https://evil.example.com/y.run")
        except ValueError:
            pass
        else:
            raise AssertionError("foreign host accepted")
        assert check_download_url("https://github.com/x/y.run")

    @test
    def update_auto_check_throttles_to_daily() -> None:
        from launcher.services.updates import check_due, should_auto_check

        assert check_due("")
        assert check_due("bogus")
        now = datetime.now()
        assert not check_due(now.isoformat())
        assert check_due((now - timedelta(hours=25)).isoformat(), now=now)
        assert should_auto_check(True, "")
        assert not should_auto_check(False, "")
        assert not should_auto_check(True, now.isoformat(), now=now)

    @test
    def update_relaunch_script_waits_then_installs() -> None:
        from pathlib import Path

        from launcher.services.updates import relaunch_script

        script = relaunch_script(Path("installer-test.run"), Path("target-test"), 4242)
        assert "4242" in script
        assert "--yes --target" in script
        assert "installer-test.run" in script and "target-test" in script

    @test
    def update_badge_hides_skipped_versions() -> None:
        from launcher.app.main import build_window
        from launcher.services.updates import UpdateInfo

        qt_app()
        with sandbox() as ctx:
            window = build_window(ctx)
            assert window._update_btn.isHidden()
            info = UpdateInfo(
                available=True, version="9.9.9", url="https://github.com/x/y.run"
            )
            window._show_update_badge(info)
            assert not window._update_btn.isHidden()
            assert "9.9.9" in window._update_btn.text()

            ctx.settings.set("update_skipped_version", "9.9.9")
            window._on_update_finished(0, info)
            assert window._update_btn.isHidden()
            window.close()

    @test
    def update_dialog_offers_install_later_and_skip() -> None:
        from launcher.services.updates import UpdateInfo
        from launcher.ui.dialogs.update_dialog import UpdateDialog

        qt_app()
        info = UpdateInfo(
            available=True,
            version="9.9.9",
            url="https://github.com/x/y.run",
            notes="Highlights.",
            size_bytes=2048,
            page_url="https://github.com/x/releases",
        )
        dialog = UpdateDialog(info, "2.2.0")
        assert dialog.result_action == "later"
        assert dialog.windowTitle() == "Update available"
        dialog._choose_skip()
        assert dialog.result_action == "skip"
        dialog2 = UpdateDialog(info, "2.2.0")
        dialog2._choose_install()
        assert dialog2.result_action == "install"
