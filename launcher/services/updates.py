"""Release update checks.

The app ships as a versioned ``.run`` file, but nothing told the user a
newer one exists. The checker fetches a small JSON feed (disabled until
a feed URL is configured) of the form
``{"version": "2.2.0", "url": "https://…", "notes": "…"}`` and compares
it with the installed version, so Settings → About can offer a
download instead of silent staleness.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UpdateInfo:
    """A newer release, or the fact that none is known."""

    available: bool
    version: str = ""
    url: str = ""
    notes: str = ""


def _parts(version: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for chunk in version.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """Whether ``latest`` is a newer version than ``current``."""
    return _parts(latest) > _parts(current)


def current_version() -> str:
    """The installed package version, or pyproject's when run from source."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("milso-launcher")
    except PackageNotFoundError:
        pass
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def fetch_feed(feed_url: str, *, timeout: int = 10) -> dict:
    """Download and parse the release feed. Raises on any problem."""
    from urllib.parse import urlparse

    if urlparse(feed_url).scheme not in ("http", "https"):
        raise ValueError(f"Refusing non-HTTP feed URL: {feed_url!r}")
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        feed_url, headers={"User-Agent": "milso-launcher"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked above
        return json.loads(response.read().decode("utf-8"))


def check(feed_url: str, current: str | None = None) -> UpdateInfo:
    """Check the feed for a newer release. Never raises."""
    feed_url = (feed_url or "").strip()
    if not feed_url:
        return UpdateInfo(available=False)
    current = current or current_version()
    try:
        payload = fetch_feed(feed_url)
        latest = str(payload.get("version", "")).strip()
        if not latest or not is_newer(latest, current):
            return UpdateInfo(available=False, version=latest)
        return UpdateInfo(
            available=True,
            version=latest,
            url=str(payload.get("url", "")),
            notes=str(payload.get("notes", "")),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return UpdateInfo(available=False)


def stamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")
