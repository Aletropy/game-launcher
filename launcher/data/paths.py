"""Filesystem locations, as an object rather than module globals.

Everything that touches disk takes a Paths instance, so a test can point
the whole application at a temporary directory instead of monkeypatching
module attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: launcher/data/paths.py -> launcher/data -> launcher -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

#: Set MILSO_SANDBOX=1 to run this checkout without touching the real
#: per-user locations (~/.config/milso-launcher and
#: ~/.local/share/milso-launcher). Settings, playtime and cache then live
#: in <project>/.sandbox instead, so dev runs cannot disturb the installed
#: app. MILSO_SANDBOX_DIR overrides where that sandbox lives.
#: ./run.sh sets this for you; the installed command does not.
SANDBOX_ENV = "MILSO_SANDBOX"
SANDBOX_DIR_ENV = "MILSO_SANDBOX_DIR"
SANDBOX_DIRNAME = ".sandbox"


def sandbox_enabled() -> bool:
    """Whether dev runs should stay inside the project sandbox."""
    import os

    return os.environ.get(SANDBOX_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def sandbox_root() -> Path:
    """Where the dev sandbox lives. Never touches real user data."""
    import os

    override = os.environ.get(SANDBOX_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return PROJECT_ROOT / SANDBOX_DIRNAME


def sandbox_cache_dir() -> Path:
    """Sandbox equivalent of the per-user cache dir."""
    return sandbox_root() / "cache"


def seed_sandbox_from_production() -> list[str]:
    """One-time copy of prod settings/state into the sandbox.

    Copies settings.json, themes/ and state.db (plus any -wal/-shm
    sidecars) when the sandbox lacks them. Never writes to the real
    locations; friends.json (the server identity) is deliberately left
    behind. Close the installed app first so state.db copies cleanly.
    Returns the sandbox-relative paths it created.
    """
    import shutil

    prod = Paths.production()
    box = Paths.sandbox()
    copied: list[str] = []

    def _copy_file(source: Path, dest: Path, rel: str) -> None:
        if dest.exists() or not source.is_file():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(rel)

    _copy_file(prod.settings_file, box.settings_file, "config/settings.json")
    if prod.themes_dir.is_dir():
        for item in sorted(prod.themes_dir.glob("*.json")):
            _copy_file(item, box.themes_dir / item.name, f"config/themes/{item.name}")
    _copy_file(prod.state_db, box.state_db, "data/state.db")
    if (box.state_db).is_file():
        for suffix in ("-wal", "-shm"):
            _copy_file(
                prod.state_db.parent / (prod.state_db.name + suffix),
                box.state_db.parent / (box.state_db.name + suffix),
                f"data/{box.state_db.name}{suffix}",
            )
    return copied


@dataclass(frozen=True)
class Paths:
    """Where the launcher keeps everything."""

    #: The launcher installation, containing milso-launcher.sh and games/.
    base: Path
    #: Per-user configuration and state.
    config: Path
    #: Per-user data (the state database).
    data: Path

    @classmethod
    def default(cls) -> Paths:
        """The real locations, honouring the XDG variables.

        Returns the project sandbox when MILSO_SANDBOX=1 (see ./run.sh),
        so dev runs never touch the installed app's data.
        """
        if sandbox_enabled():
            return cls.sandbox()
        return cls.production()

    @classmethod
    def sandbox(cls) -> Paths:
        """Everything project-local: games were already, config/data now too."""
        root = sandbox_root()
        return cls(
            base=PROJECT_ROOT,
            config=root / "config",
            data=root / "data",
        )

    @classmethod
    def production(cls) -> Paths:
        """The installed locations, honouring the XDG variables."""
        import contextlib
        import shutil

        from launcher import platform as _platform

        if _platform.is_windows():
            config = _platform.config_home()
            # config_home() already includes the app name on Windows.
            data = _platform.data_home()
            # Legacy single-"launcher" dirs are siblings of the new ones.
            legacy_config = config.parent / "launcher"
            legacy_data = data.parent / "launcher"
        else:
            import os

            config_home = Path(
                os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
            )
            data_home = Path(
                os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
            )
            config = config_home / "milso-launcher"
            data = data_home / "milso-launcher"
            # One-time migration from the old "launcher" name.
            legacy_config = config_home / "launcher"
            legacy_data = data_home / "launcher"
        for legacy, new in ((legacy_config, config), (legacy_data, data)):
            if legacy == new:
                continue
            if legacy.is_dir():
                if not new.exists():
                    with contextlib.suppress(OSError):
                        shutil.copytree(legacy, new, dirs_exist_ok=True)
                else:
                    # New already exists (e.g. created on first run); copy any
                    # missing files from the legacy location.
                    with contextlib.suppress(OSError):
                        for item in legacy.rglob("*"):
                            if item.is_file():
                                rel = item.relative_to(legacy)
                                target = new / rel
                                if not target.exists():
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    with contextlib.suppress(OSError):
                                        shutil.copy2(item, target)
        return cls(
            base=PROJECT_ROOT,
            config=config,
            data=data,
        )

    @classmethod
    def for_testing(cls, root: Path) -> Paths:
        """Everything under one temporary directory."""
        return cls(base=root / "base", config=root / "config", data=root / "data")

    # -- launcher installation -----------------------------------------

    @property
    def games_dir(self) -> Path:
        return self.base / "games"

    @property
    def launcher_script(self) -> Path:
        return self.base / "milso-launcher.sh"

    @property
    def prefix_name_file(self) -> Path:
        return self.base / ".prefix-name"

    @property
    def prefixes_dir(self) -> Path:
        return self.base / "prefixes"

    @property
    def icon(self) -> Path:
        return self.base / "icon.png"

    @property
    def backups_dir(self) -> Path:
        return self.base / "backups"

    @property
    def saves_dir(self) -> Path:
        """The shared save store.

        Must stay under the launcher directory: games resolve its
        symlinks inside the Steam Flatpak container, which can see this
        directory but not arbitrary paths elsewhere.
        """
        return self.base / "Saves"

    @property
    def artwork_dir(self) -> Path:
        return self.base / "launcher" / "artwork"

    @property
    def legacy_heroes_dir(self) -> Path:
        """Pre-revamp flat artwork directory, read as a fallback."""
        return self.base / "launcher" / "heroes"

    # -- per-user ------------------------------------------------------

    @property
    def settings_file(self) -> Path:
        return self.config / "settings.json"

    @property
    def legacy_favorites_file(self) -> Path:
        """Favourites before they moved into the state database."""
        return self.config / "favorites.json"

    @property
    def friends_file(self) -> Path:
        """The friends server profile: its token, so kept private."""
        return self.config / "friends.json"

    @property
    def themes_dir(self) -> Path:
        """Themes the user made, one JSON file each."""
        return self.config / "themes"

    @property
    def state_backups_dir(self) -> Path:
        """Copies of the database taken before clearing data."""
        return self.data / "state-backups"

    @property
    def state_db(self) -> Path:
        return self.data / "state.db"

    @property
    def active_sessions_file(self) -> Path:
        """Games believed to be running, so a quit does not lose them."""
        return self.data / "active-sessions.json"

    @property
    def pending_sessions_dir(self) -> Path:
        """Finished sessions written by the background watcher."""
        return self.data / "sessions-pending"

    def ensure_dirs(self) -> None:
        """Create the directories the launcher writes to."""
        for directory in (self.config, self.data, self.games_dir):
            directory.mkdir(parents=True, exist_ok=True)
