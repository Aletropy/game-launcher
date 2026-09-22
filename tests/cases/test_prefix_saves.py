"""Proton discovery, prefix health, saves exchange and backup verify."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path


def register(*, test, qt_app, sandbox, pump):
    @test
    def proton_discovery_lists_builds_newest_first() -> None:
        import time

        from launcher.services.protons import describe, list_installed

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old = root / "Proton-Old"
            (old).mkdir()
            (old / "proton").write_text("#")
            time.sleep(0.02)
            new = root / "Proton-New"
            new.mkdir()
            (new / "proton").write_text("#")
            (new / "version").write_text("Proton 10\n")
            (root / "notaproton").mkdir()
            builds = list_installed([root])
            assert [b.name for b in builds] == ["Proton-New", "Proton-Old"]
            assert "10" in builds[0].label
            assert describe(str(new)).startswith("Proton build")
            assert describe(str(root / "notaproton")) != ""
            assert describe(str(root / "missing")) == "Path does not exist"
            assert describe("") == ""

    @test
    def prefix_health_reports_size_and_broken_links() -> None:
        from launcher.domain.prefix_health import inspect_health

        with tempfile.TemporaryDirectory() as d:
            missing = inspect_health(Path(d) / "nope")
            assert not missing.exists and missing.size_bytes == 0
            prefix = Path(d) / "Prefix"
            drive_c = prefix / "pfx" / "drive_c"
            (drive_c / "users/steamuser/Documents").mkdir(parents=True)
            (drive_c / "users/steamuser/Documents/save.sav").write_text("x" * 100)
            health = inspect_health(prefix)
            assert health.exists and health.is_proton
            assert health.size_bytes >= 100 and health.file_count == 1
            assert health.last_used is not None

    @test
    def saves_export_import_round_trip() -> None:
        from launcher.services import save_exchange

        with sandbox() as ctx:
            (ctx.paths.saves_dir / "Documents/Game").mkdir(parents=True)
            (ctx.paths.saves_dir / "Documents/Game/save.sav").write_text("DATA")
            dest = ctx.paths.data / "out.zip"
            summary = save_exchange.export_zip(ctx.save_store, None, dest)
            assert summary.files == 1 and dest.is_file()
            preview = save_exchange.preview_import(dest)
            assert preview.files == 1 and preview.folders == ["Documents"]

            junk = ctx.paths.data / "junk.zip"
            with zipfile.ZipFile(junk, "w") as archive:
                archive.writestr("x.txt", "hi")
            try:
                save_exchange.preview_import(junk)
            except ValueError:
                pass
            else:
                raise AssertionError("junk archive accepted")

    @test
    def backup_verify_reports_health() -> None:
        with sandbox() as ctx:
            (ctx.paths.saves_dir / "Documents").mkdir(parents=True)
            (ctx.paths.saves_dir / "Documents/x.sav").write_text("x")
            snapshot = ctx.backups.create("t")
            report = ctx.backups.verify(snapshot)
            assert report.ok, report.problems
            assert report.files >= 1

    @test
    def prefix_rebuild_deletes_only_inside() -> None:
        with sandbox() as ctx:
            tools = ctx.prefix_tools
            prefix = ctx.paths.base / "prefixes" / "Doom"
            (prefix / "pfx").mkdir(parents=True)
            (prefix / "pfx" / "user.reg").write_text("x")
            tools.rebuild("prefixes/Doom")
            assert not prefix.exists()
            assert ctx.paths.base.is_dir()

            outside = Path(tempfile.gettempdir()) / "milso-outside-prefix"
            try:
                tools.rebuild(str(outside))
            except OSError:
                pass
            else:
                raise AssertionError("outside prefix rebuilt")
            try:
                tools.rebuild("prefixes/Missing")
            except OSError:
                pass
            else:
                raise AssertionError("missing prefix rebuilt")
