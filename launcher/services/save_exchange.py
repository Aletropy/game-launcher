"""Move saves between machines as a zip archive.

The shared store and its snapshots are bound to this installation;
there was no way to take saves elsewhere. Export writes the store (or
chosen top-level folders) to a zip with a manifest; import previews the
archive, takes a safety snapshot, and merges it with the same
newer-wins rules as prefix sharing, quarantining every loser.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from launcher.services.backups import BackupService, Snapshot
from launcher.services.merge import MergeResult, apply_merge
from launcher.services.save_store import SaveStore

#: Written into every export; imports without it are refused.
MANIFEST_NAME = "milso-saves.json"
#: Never exported nor imported: conflict quarantine, not save data.
SKIP_TOP_DIRS = {".conflicts"}


@dataclass
class ExportSummary:
    """What an export wrote."""

    dest: Path
    files: int = 0
    total_bytes: int = 0


@dataclass
class ImportPreview:
    """What an archive holds, before anything is touched."""

    files: int = 0
    total_bytes: int = 0
    folders: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    """What an import changed."""

    moved: int = 0
    identical: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)
    safety: Snapshot | None = None


def _data_files(root: Path, folders: list[str] | None) -> list[tuple[Path, str]]:
    """(absolute path, archive name) of exported files, sorted."""
    names = sorted(folders) if folders else None
    found: list[tuple[Path, str]] = []
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        top = relative.split("/", 1)[0]
        if top in SKIP_TOP_DIRS or top.startswith("."):
            continue
        if names is not None and top not in names:
            continue
        found.append((path, relative))
    return found


def top_folders(store: SaveStore) -> list[str]:
    """Top-level save folders available for export, sorted."""
    root = store.root
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and p.name not in SKIP_TOP_DIRS and not p.name.startswith(".")
    )


def export_zip(
    store: SaveStore, folders: list[str] | None, dest: Path
) -> ExportSummary:
    """Write the store (or some top folders) to a zip archive."""
    files = _data_files(store.root, folders)
    manifest = {
        "app": "milso-launcher",
        "version": 1,
        "exported": datetime.now().isoformat(timespec="seconds"),
        "folders": sorted(folders) if folders else [],
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    summary = ExportSummary(dest=dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for path, relative in files:
            try:
                archive.write(path, relative)
                summary.files += 1
                summary.total_bytes += path.stat().st_size
            except OSError:
                continue
    return summary


def preview_import(archive: Path) -> ImportPreview:
    """Describe an archive without touching the store. Raises on junk."""
    preview = ImportPreview()
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(f"Not a saves archive: {e}") from e
    if MANIFEST_NAME not in names:
        raise ValueError("Not a saves archive: no manifest inside.")
    for info in _safe_members(archive):
        preview.files += 1
        preview.total_bytes += info.file_size
        top = info.filename.split("/", 1)[0]
        if top and top not in preview.folders:
            preview.folders.append(top)
    preview.folders.sort()
    return preview


def _safe_members(archive: Path) -> list[zipfile.ZipInfo]:
    """Archive members safe to extract: no absolute paths, no escapes."""
    with zipfile.ZipFile(archive) as bundle:
        members = [i for i in bundle.infolist() if not i.is_dir()]
    safe: list[zipfile.ZipInfo] = []
    for info in members:
        name = info.filename
        if name == MANIFEST_NAME:
            continue
        parts = Path(name).parts
        if Path(name).is_absolute() or ".." in parts:
            continue
        top = parts[0] if parts else ""
        if top in SKIP_TOP_DIRS or top.startswith("."):
            continue
        safe.append(info)
    return safe


def import_zip(
    store: SaveStore,
    backups: BackupService,
    archive: Path,
    *,
    safety_snapshot: bool = True,
) -> ImportResult:
    """Merge an archive into the store with a safety snapshot first."""
    preview = preview_import(archive)
    if preview.files == 0:
        raise ValueError("The archive holds no saves.")
    result = ImportResult()
    if safety_snapshot and store.exists:
        result.safety = backups.create("before importing saves")
    with tempfile.TemporaryDirectory(prefix="milso-import-") as directory:
        staged = Path(directory) / "staged"
        staged.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for info in _safe_members(archive):
                try:
                    bundle.extract(info, staged)
                except (OSError, zipfile.BadZipFile) as e:
                    result.errors.append(f"{info.filename}: {e}")
        merged: MergeResult = apply_merge(staged, store.root, store.conflicts_root)
        result.moved = merged.moved
        result.identical = merged.identical_removed
        result.conflicts = len(merged.conflicts)
        result.errors.extend(merged.errors)
    return result
