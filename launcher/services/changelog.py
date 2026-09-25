"""What's new after an update.

When the launcher installs a newer release through its own updater, the
release notes are stashed to disk first. On the next startup, a version
change is detected and the notes are shown once in a dialog. Releases
installed by hand (running the ``.run`` directly) have no stash, so the
notes are fetched from the GitHub API by tag instead, with a generic
message as the last resort. Nothing here ever raises.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

#: The stashed notes, relative to Paths.data.
PENDING_NAME = "pending-changelog.json"


@dataclass(frozen=True)
class Changelog:
    """Release notes for one version."""

    version: str = ""
    notes: str = ""
    page_url: str = ""


def should_show(stored: str, current: str) -> bool:
    """Whether a version change deserves the What's new dialog.

    First runs (nothing stored), identical versions, downgrades and an
    unknown current version all stay silent; only a real upgrade shows.
    """
    from launcher.services.updates import is_newer

    stored = (stored or "").strip()
    current = (current or "").strip()
    if not stored or not current or current == "unknown":
        return False
    with contextlib.suppress(TypeError, ValueError):
        return is_newer(current, stored)
    return stored != current


def pending_path(data_dir: Path) -> Path:
    """Where the stashed notes wait for the next startup."""
    return Path(data_dir) / PENDING_NAME


def stash_pending(
    data_dir: Path, version: str, notes: str, page_url: str = ""
) -> None:
    """Remember release notes for the startup after an in-app install."""
    with contextlib.suppress(OSError):
        path = pending_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"version": version, "notes": notes, "page_url": page_url}
            ),
            encoding="utf-8",
        )
        tmp.replace(path)


def peek_pending(data_dir: Path) -> Changelog | None:
    """The stashed notes, if any, left in place."""
    try:
        raw = json.loads(pending_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return Changelog(
        version=str(raw.get("version", "")),
        notes=str(raw.get("notes", "") or ""),
        page_url=str(raw.get("page_url", "") or ""),
    )


def take_pending(data_dir: Path) -> Changelog | None:
    """The stashed notes, consumed: the file is removed either way."""
    info = peek_pending(data_dir)
    with contextlib.suppress(OSError):
        pending_path(data_dir).unlink(missing_ok=True)
    return info


def releases_page(repo: str) -> str:
    """The web page listing a repo's releases."""
    from launcher.services.updates import DEFAULT_REPO

    repo = (repo or "").strip().strip("/") or DEFAULT_REPO
    return f"https://github.com/{repo}/releases"


def fetch_notes_for(
    repo: str, version: str, *, timeout: int = 10
) -> Changelog | None:
    """Fetch one release's notes from the GitHub API. None on any problem."""
    import urllib.request

    from launcher.services.updates import normalize_version

    repo = (repo or "").strip().strip("/")
    tag = normalize_version(version)
    if not repo or not tag:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/tags/v{tag}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "milso-launcher",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        # The URL is an https GitHub API URL built from a validated tag above.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return Changelog(
        version=tag,
        notes=str(payload.get("body", "") or ""),
        page_url=str(payload.get("html_url", "") or ""),
    )
