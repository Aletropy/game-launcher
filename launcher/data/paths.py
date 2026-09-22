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


@dataclass(frozen=True)
class Paths:
    """Where the launcher keeps everything."""

    #: The launcher installation, containing game-launcher.sh and games/.
    base: Path
    #: Per-user configuration and state.
    config: Path
    #: Per-user data (the state database).
    data: Path

    @classmethod
    def default(cls) -> Paths:
        """The real locations, honouring the XDG variables."""
        import os

        config_home = Path(
            os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
        )
        data_home = Path(
            os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        )
        return cls(
            base=PROJECT_ROOT,
            config=config_home / "launcher",
            data=data_home / "launcher",
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
        return self.base / "game-launcher.sh"

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
    def state_backups_dir(self) -> Path:
        """Copies of the database taken before clearing data."""
        return self.data / "state-backups"

    @property
    def state_db(self) -> Path:
        return self.data / "state.db"

    def ensure_dirs(self) -> None:
        """Create the directories the launcher writes to."""
        for directory in (self.config, self.data, self.games_dir):
            directory.mkdir(parents=True, exist_ok=True)
