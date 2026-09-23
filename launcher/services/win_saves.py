"""Windows native save discovery and mirroring.

Linux keeps the Wine-prefix symlink store; on Windows there are no
prefixes, so saves live in their native folders (%APPDATA%, Documents,
...). This module finds the folders that probably belong to a game and
mirrors them into ``Saves/<Game>/`` so the existing backup, export and
restore pipeline works unchanged.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WinSaveHit:
    path: Path
    confidence: str  # "high" | "medium" | "low"
    reason: str


def name_variants(game_name: str, exe_path: str = "") -> list[str]:
    """Lowercased tokens identifying a game: name, exe stem, publisher-ish parts."""
    variants: list[str] = []
    for raw in (game_name, Path(exe_path).stem if exe_path else ""):
        cleaned = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
        if not cleaned:
            continue
        variants.append(cleaned)
        variants.append(cleaned.replace(" ", ""))
        for token in cleaned.split():
            if len(token) >= 4 and token not in variants:
                variants.append(token)
    seen: list[str] = []
    for variant in variants:
        if variant and variant not in seen:
            seen.append(variant)
    return seen[:12]


def known_roots(exe_path: str = "", roots_override: list[Path] | None = None) -> list[Path]:
    """Native locations worth scanning. Never walks a whole drive."""
    if roots_override is not None:
        return [p for p in roots_override if p.is_dir()]
    home = Path.home()
    candidates = [
        Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming"),
        Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"),
        Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "Packages",
        home / "AppData" / "LocalLow",
        home / "Documents",
        home / "Documents" / "My Games",
        home / "Saved Games",
        Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData"),
    ]
    if exe_path:
        with_separate = Path(exe_path).parent
        candidates.append(with_separate)
        # Publisher folder one level up (e.g. Ubisoft/Game) is common.
        candidates.append(with_separate.parent)
    roots = []
    for root in candidates:
        try:
            if root.is_dir() and root not in roots:
                roots.append(root)
        except OSError:
            continue
    return roots


def _score(dirname: str, variants: list[str]) -> tuple[str, str] | None:
    folded = re.sub(r"[^a-z0-9]+", " ", dirname.lower()).strip()
    nospace = folded.replace(" ", "")
    for variant in variants:
        if not variant:
            continue
        if folded == variant or nospace == variant.replace(" ", ""):
            return "high", f"matches '{dirname}'"
        if variant in folded and len(variant) >= 4:
            return "medium", f"'{dirname}' contains '{variant}'"
    for variant in variants:
        token = variant.split(" ")[0] if variant else ""
        if len(token) >= 5 and token in folded:
            return "low", f"'{dirname}' mentions '{token}'"
    return None


def _children(entry: Path, variants: list[str], max_hits: int) -> list[WinSaveHit]:
    """Scored folders one level under a container folder."""
    found: list[WinSaveHit] = []
    try:
        sub = list(entry.iterdir())
    except OSError:
        return found
    for child in sub:
        try:
            if not child.is_dir() or child.is_symlink():
                continue
            scored = _score(child.name, variants)
            if scored is not None and len(found) < max_hits:
                found.append(
                    WinSaveHit(
                        child, scored[0], f"{scored[1]} (under {entry.name})"
                    )
                )
        except OSError:
            continue
    return found


def _scan_root(
    root: Path, variants: list[str], max_hits: int, hits: list[WinSaveHit]
) -> None:
    """Append scored folders directly under root (plus one container level)."""
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    container = root.name.lower() in ("my games", "packages")
    for entry in entries:
        if len(hits) >= max_hits:
            break
        try:
            if not entry.is_dir() or entry.is_symlink():
                continue
            scored = _score(entry.name, variants)
            if scored is None:
                if container or entry.name.lower() == "my games":
                    for hit in _children(entry, variants, max_hits - len(hits)):
                        hits.append(hit)
                continue
            hits.append(WinSaveHit(entry, scored[0], scored[1]))
        except OSError:
            continue


def discover(
    game_name: str,
    exe_path: str = "",
    *,
    roots_override: list[Path] | None = None,
    max_hits: int = 10,
) -> list[WinSaveHit]:
    """Candidate native save folders for a game. Reads only, never raises."""
    variants = name_variants(game_name, exe_path)
    if not variants:
        return []
    hits: list[WinSaveHit] = []
    try:
        roots = known_roots(exe_path, roots_override)
    except (OSError, ValueError):
        return []
    for root in roots:
        _scan_root(root, variants, max_hits, hits)
        if len(hits) >= max_hits:
            break
    order = {"high": 0, "medium": 1, "low": 2}
    hits.sort(key=lambda h: (order.get(h.confidence, 3), h.path.name.lower()))
    return hits[:max_hits]


def _quarantine(src: Path, conflicts_root: Path, safe: str, relative: Path) -> None:
    """Copy a conflict loser aside. Best-effort."""
    import contextlib
    import shutil
    import time

    qdir = conflicts_root / safe / time.strftime("%Y-%m-%d_%H%M%S")
    with contextlib.suppress(OSError):
        qdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, qdir / relative.name)


def _mirror_file(
    path: Path, target: Path, conflicts_root: Path, safe: str, stats: dict[str, int]
) -> None:
    """Copy one file newer-wins into the store. Native is never deleted."""
    import shutil

    if target.exists():
        try:
            sst, tst = path.stat(), target.stat()
        except OSError:
            stats["errors"] += 1
            return
        if sst.st_size == tst.st_size and int(sst.st_mtime) == int(tst.st_mtime):
            return
        try:
            relative = path.relative_to(path.parent.parent)
        except ValueError:
            relative = Path(path.name)
        if int(sst.st_mtime) > int(tst.st_mtime):
            _quarantine(target, conflicts_root, safe, relative)
            stats["conflicts"] += 1
        else:
            _quarantine(path, conflicts_root, safe, relative)
            stats["conflicts"] += 1
            return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    stats["mirrored"] += 1


def mirror_game(
    game_name: str,
    native_paths: list[Path],
    store_root: Path,
    conflicts_root: Path,
) -> dict[str, int]:
    """Copy native save folders into ``Saves/<Game>/``. Returns stats.

    Newer files win; losers are quarantined under ``conflicts_root`` with
    the game name prefixed. Native folders are only read, never moved or
    deleted; symlinks are skipped so a link cannot pull outside files in.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", game_name).strip("-") or "game"
    dest_root = store_root / safe
    dest_root.mkdir(parents=True, exist_ok=True)
    stats = {"mirrored": 0, "conflicts": 0, "errors": 0}
    for native in native_paths:
        try:
            if not native.is_dir() or native.is_symlink():
                continue
            dest = dest_root / native.name
            dest.mkdir(parents=True, exist_ok=True)
            for path in native.rglob("*"):
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    relative = path.relative_to(native)
                except (OSError, ValueError):
                    continue
                try:
                    _mirror_file(path, dest / relative, conflicts_root, safe, stats)
                except OSError:
                    stats["errors"] += 1
        except OSError:
            stats["errors"] += 1
    return stats


def restore_game(game_name: str, store_root: Path, native_parent: Path) -> int:
    """Copy ``Saves/<Game>/*`` back over native folders. Returns files restored."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", game_name).strip("-") or "game"
    source_root = store_root / safe
    if not source_root.is_dir():
        return 0
    restored = 0
    for child in source_root.iterdir():
        try:
            if not child.is_dir():
                continue
            dest = native_parent / child.name
            shutil.copytree(child, dest, dirs_exist_ok=True)
            restored += 1
        except OSError:
            continue
    return restored
