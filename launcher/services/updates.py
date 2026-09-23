"""Release update checks against GitHub Releases.

The app ships as a versioned ``.run`` file built by ``package.sh`` and
published as a release asset. The checker asks the GitHub API for the
latest release, compares its tag with the installed version, and hands
the UI a download URL so the main window can offer a one-click install
instead of silent staleness.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

#: The repository checked when the user has not configured another one.
DEFAULT_REPO = "Aletropy/milso-launcher"
#: Asset suffix per platform. Linux ships the one-run installer; Windows
#: ships a zip with the payload plus setup-win.bat.
PLATFORM_ASSETS = {"linux": (".run",), "windows": (".zip", "-win.zip")}
WIN_ASSET_INFIX = "-win"
#: How long a successful check suppresses the next automatic one.
CHECK_INTERVAL = timedelta(hours=24)
#: Hosts a release download may come from (API + release asset CDN).
_ALLOWED_SUFFIXES = ("api.github.com", "github.com", "githubusercontent.com")
#: ``owner/name``, the only shape accepted for the repo setting.
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class UpdateInfo:
    """A newer release, or the fact that none is known."""

    available: bool
    version: str = ""
    url: str = ""
    notes: str = ""
    size_bytes: int = 0
    page_url: str = ""
    platform: str = ""
    asset: str = ""


def _parts(version: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for chunk in version.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """Whether ``latest`` is a newer version than ``current``."""
    return _parts(normalize_version(latest)) > _parts(normalize_version(current))


def normalize_version(tag: str) -> str:
    """Strip a leading ``v`` and whitespace from a release tag."""
    cleaned = (tag or "").strip()
    if cleaned[:1].lower() == "v":
        cleaned = cleaned[1:]
    return cleaned.strip()


def current_version() -> str:
    """The installed package version, or pyproject's when run from source."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("milso-launcher")
    except PackageNotFoundError:
        pass
    from pathlib import Path as _Path

    pyproject = _Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def release_api_url(repo: str) -> str:
    """The GitHub API URL for a repo's latest release. Raises on bad input."""
    cleaned = (repo or "").strip().strip("/")
    if not _REPO_RE.match(cleaned):
        raise ValueError(f"Not a GitHub owner/name: {repo!r}")
    return f"https://api.github.com/repos/{cleaned}/releases/latest"


def _check_repo(repo: str) -> str:
    cleaned = (repo or "").strip()
    if not cleaned:
        raise ValueError("No repository configured")
    return cleaned


def fetch_release(repo: str, *, timeout: int = 10) -> dict:
    """Download and parse the latest-release payload. Raises on any problem."""
    url = release_api_url(_check_repo(repo))
    request = urllib.request.Request(  # noqa: S310 - https URL built above
        url,
        headers={
            "User-Agent": "milso-launcher",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Unexpected release payload")
    return payload


def pick_run_asset(payload: dict, version: str) -> tuple[str, int]:
    """Pick the ``.run`` asset URL (and size) from a release payload."""
    url, size, _ = pick_asset(payload, version, "linux")
    return url, size


def pick_asset(
    payload: dict, version: str, platform: str | None = None
) -> tuple[str, int, str]:
    """Pick the installer asset URL, size and name for a platform.

    ``platform`` is 'linux' or 'windows'; defaults to the running OS.
    Raises ValueError when the release has no asset for it.
    """
    from launcher import platform as _platform

    want = (platform or _platform.app_platform()).lower()
    if want not in PLATFORM_ASSETS:
        want = "linux"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Release has no assets")
    if want == "windows":
        candidates = [
            a
            for a in assets
            if isinstance(a, dict)
            and str(a.get("name", "")).endswith(".zip")
            and WIN_ASSET_INFIX in str(a.get("name", ""))
            and str(a.get("browser_download_url", "")).startswith("https://")
        ]
        preferred = f"milso-launcher-{version}-win.zip"
    else:
        candidates = [
            a
            for a in assets
            if isinstance(a, dict)
            and str(a.get("name", "")).endswith(".run")
            and str(a.get("browser_download_url", "")).startswith("https://")
        ]
        preferred = f"milso-launcher-{version}.run"
    if not candidates:
        raise ValueError(f"No installer asset for {want} in release {version or '?'}")
    for asset in candidates:
        if str(asset.get("name", "")) == preferred:
            return (
                str(asset["browser_download_url"]),
                int(asset.get("size") or 0),
                str(asset["name"]),
            )
    first = candidates[0]
    return (
        str(first["browser_download_url"]),
        int(first.get("size") or 0),
        str(first.get("name")),
    )


def parse_release(
    payload: dict, current: str, platform: str | None = None
) -> UpdateInfo:
    """Turn a release payload into an UpdateInfo. Raises on bad payloads."""
    from launcher import platform as _platform

    want = (platform or _platform.app_platform()).lower()
    if want not in PLATFORM_ASSETS:
        want = "linux"
    latest = normalize_version(str(payload.get("tag_name", "")))
    if not latest or not is_newer(latest, current):
        return UpdateInfo(available=False, version=latest, platform=want)
    url, size, asset = pick_asset(payload, latest, want)
    notes = str(payload.get("body", "") or "")
    page_url = str(payload.get("html_url", "") or "")
    return UpdateInfo(
        available=True,
        version=latest,
        url=url,
        notes=notes,
        size_bytes=size,
        page_url=page_url,
        platform=want,
        asset=asset,
    )


def check_github(repo: str, current: str | None = None) -> UpdateInfo:
    """Check GitHub for a newer release. Never raises."""
    repo = (repo or "").strip()
    if not repo:
        return UpdateInfo(available=False)
    current = current or current_version()
    try:
        return parse_release(fetch_release(repo), current)
    except (OSError, ValueError, KeyError, TypeError):
        return UpdateInfo(available=False)


def check_due(last_check: str, *, now: datetime | None = None) -> bool:
    """Whether the last automatic check is old enough to check again."""
    if not (last_check or "").strip():
        return True
    try:
        checked_at = datetime.fromisoformat(last_check.strip())
    except ValueError:
        return True
    return (now or datetime.now()) - checked_at >= CHECK_INTERVAL


def should_auto_check(auto_enabled: bool, last_check: str, **kwargs) -> bool:
    """Whether a startup check should run. Never raises."""
    try:
        return bool(auto_enabled) and check_due(last_check, **kwargs)
    except (TypeError, ValueError):
        return bool(auto_enabled)


def update_cache_dir() -> Path:
    """Where downloaded installers wait for the user to install them."""
    from launcher import platform as _platform

    if _platform.is_windows():
        return _platform.cache_home() / "milso-launcher" / "updates"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "milso-launcher" / "updates"


def installer_dest(version: str, platform: str | None = None) -> Path:
    """The cache path a downloaded installer for ``version`` lives at."""
    from launcher import platform as _platform

    want = (platform or _platform.app_platform()).lower()
    safe = normalize_version(version) or "unknown"
    if want == "windows":
        return update_cache_dir() / f"milso-launcher-{safe}-win.zip"
    return update_cache_dir() / f"milso-launcher-{safe}.run"


def check_download_url(url: str) -> str:
    """Validate an asset URL. Returns it, or raises."""
    from urllib.parse import urlparse

    parts = urlparse((url or "").strip())
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"Refusing non-HTTPS asset URL: {url!r}")
    host = parts.hostname.lower()
    if not any(host == s or host.endswith("." + s) for s in _ALLOWED_SUFFIXES):
        raise ValueError(f"Refusing asset host: {host!r}")
    return url.strip()


def download_asset(
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int], None] | None = None,
    *,
    timeout: int = 120,
) -> Path:
    """Download a release asset to ``dest`` (via ``.part`` + rename).

    ``progress_cb``, when given, is called as ``(done_bytes, total_bytes)``.
    If it raises, the download aborts and the partial file is removed.
    Raises on any problem; a partial file is removed.
    """
    checked = check_download_url(url)
    request = urllib.request.Request(  # noqa: S310 - host allowlisted above
        checked, headers={"User-Agent": "milso-launcher"}
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    callback = progress_cb if callable(progress_cb) else None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with part.open("wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if callback is not None:
                        callback(done, total)
        part.replace(dest)
    except BaseException:
        with contextlib.suppress(OSError):
            part.unlink()
        raise
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return dest


def relaunch_script(installer: Path, target: Path, pid: int) -> str:
    """A shell script that installs once this process (``pid``) is gone."""
    return (
        "for i in $(seq 1 600); do\n"
        f'  kill -0 {int(pid)} 2>/dev/null || break\n'
        "  sleep 0.5\n"
        "done\n"
        f'exec "{installer}" --yes --target "{target}"\n'
    )


def relaunch_script_win(installer: Path, target: Path, pid: int) -> str:
    """A batch file that installs once this process (``pid``) is gone."""
    setup = installer.parent / "setup-win.ps1"
    return (
        "@echo off\r\n"
        f"REM Wait for PID {int(pid)} then install {installer.name}\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {int(pid)}"'
        f' | find "{int(pid)}" >nul\r\n'
        "if not errorlevel 1 (\r\n  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n)\r\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{setup}"'
        f' -Target "{target}" -Yes\r\n'
    )


def schedule_install(installer: Path, target: Path) -> Path:
    """Run the installer detached once this process exits. Returns log path."""
    import shutil
    import subprocess

    from launcher import platform as _platform

    log = update_cache_dir() / "update-install.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if _platform.is_windows():
        script = relaunch_script_win(installer, target, os.getpid())
        bat = update_cache_dir() / "update-install.bat"
        bat.write_text(script, encoding="utf-8")
        cmd = shutil.which("cmd") or os.environ.get("COMSPEC") or "cmd"
        with log.open("ab") as handle:
            subprocess.Popen(  # noqa: S603 - resolved cmd, file just written
                [cmd, "/c", str(bat)],
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        return log
    script = relaunch_script(installer, target, os.getpid())
    shell = shutil.which("bash") or "/bin/bash"
    with log.open("ab") as handle:
        subprocess.Popen(  # noqa: S603 - resolved shell, script via stdin-safe argv
            [shell, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return log


def fetch_feed(feed_url: str, *, timeout: int = 10) -> dict:
    """Download and parse a legacy JSON release feed. Raises on any problem."""
    from urllib.parse import urlparse

    if urlparse(feed_url).scheme not in ("http", "https"):
        raise ValueError(f"Refusing non-HTTP feed URL: {feed_url!r}")
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        feed_url, headers={"User-Agent": "milso-launcher"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def check(feed_url: str, current: str | None = None) -> UpdateInfo:
    """Check a legacy JSON feed for a newer release. Never raises."""
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
