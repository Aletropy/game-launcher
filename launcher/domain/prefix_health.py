"""Prefix health: size, freshness and broken save links.

A prefix is a black box until something breaks. One walk reports how big
it is, when anything in it last changed, whether it looks like a Proton
prefix at all, and which shared-save links wineboot replaced with real
directories, so the UI can show that before a launch rather than after.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from launcher.domain.save_layout import LINKS


@dataclass
class PrefixHealth:
    """What one prefix looks like from the outside."""

    path: Path
    exists: bool = False
    size_bytes: int = 0
    file_count: int = 0
    #: Newest modification time found, if the prefix exists.
    last_used: datetime | None = None
    #: True when Proton's pfx/ layout is present.
    is_proton: bool = False
    #: Save links wineboot replaced with real directories.
    broken_save_links: list[str] = field(default_factory=list)


def _drive_c(prefix: Path) -> Path:
    nested = prefix / "pfx" / "drive_c"
    return nested if nested.is_dir() or not (prefix / "drive_c").is_dir() else prefix / "drive_c"


def inspect_health(prefix: Path) -> PrefixHealth:
    """Walk a prefix once and summarise it. Never raises."""
    health = PrefixHealth(path=prefix, exists=prefix.is_dir())
    if not health.exists:
        return health
    newest = 0.0
    try:
        for root, _dirs, files in os.walk(prefix):
            for name in files:
                try:
                    st = os.lstat(os.path.join(root, name))
                except OSError:
                    continue
                health.file_count += 1
                health.size_bytes += st.st_size
                newest = max(newest, st.st_mtime)
    except OSError:
        pass
    if newest:
        # Naive local time, matching datetime.now() used everywhere else.
        health.last_used = datetime.fromtimestamp(newest)  # noqa: DTZ006
    health.is_proton = (prefix / "pfx").is_dir()
    drive_c = _drive_c(prefix)
    for spec in LINKS:
        link = drive_c / spec.in_prefix
        try:
            if link.is_symlink() and not link.exists():
                health.broken_save_links.append(spec.in_store)
        except OSError:
            continue
    return health
