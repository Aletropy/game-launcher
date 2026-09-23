"""Reading and writing games/*.conf.

The conf filename stem is a game's identity; favourites, artwork and
state all key off it, which is why renaming goes through one method.
"""

from __future__ import annotations

import os
from pathlib import Path

from launcher.data.paths import Paths
from launcher.data.state_store import StateStore
from launcher.domain.config import load, save
from launcher.domain.models import Game, GameConfig, GameStats

#: Conf key <-> GameConfig field, for the scalar values.
_SCALARS: dict[str, str] = {
    "GAME_EXECUTABLE": "executable",
    "GAMEID": "game_id",
    "CUSTOM_PROTON_PATH": "custom_proton_path",
    "GAMESCOPE_W": "gamescope_w",
    "GAMESCOPE_H": "gamescope_h",
    "GAMESCOPE_W_OUT": "gamescope_w_out",
    "GAMESCOPE_H_OUT": "gamescope_h_out",
    "GAMESCOPE_ARGS": "gamescope_args",
    "OVERRIDE_APP_ID": "override_app_id",
    "GAME_PREFIX": "prefix",
    "PROTON_USE_WINE_SYNC": "proton_use_wine_sync",
    "WINEDEBUG": "winedebug",
    "RADV_PERFTEST": "radv_perftest",
    "PULSE_LATENCY_MSEC": "pulse_latency_msec",
    "VKD3D_CONFIG": "vkd3d_config",
}

_ARRAYS: dict[str, str] = {
    "GAME_ARGS": "game_args",
    "ADDITIONAL_DLLS": "additional_dlls",
    "extra_vars": "extra_vars",
}

#: Values equal to the default are not written, so untouched confs stay
#: byte-identical and the file records only what the user actually set.
_DEFAULTS = GameConfig(name="")


def _as_list(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def config_from_data(name: str, data: dict[str, str | list[str]]) -> GameConfig:
    """Build a GameConfig from a parsed conf file."""
    config = GameConfig(name=name)
    for key, attr in _SCALARS.items():
        if key in data:
            setattr(config, attr, str(data[key]))
    for key, attr in _ARRAYS.items():
        if key in data:
            setattr(config, attr, _as_list(data[key]))
    config.use_gamescope = str(data.get("USE_GAMESCOPE", "0")) == "1"
    return config


#: Proton/Wine-only keys, never written on the Windows sub-app.
_WINDOWS_SKIP_KEYS = {
    "GAMEID",
    "CUSTOM_PROTON_PATH",
    "OVERRIDE_APP_ID",
    "GAME_PREFIX",
    "PROTON_USE_WINE_SYNC",
    "WINEDEBUG",
    "RADV_PERFTEST",
    "PULSE_LATENCY_MSEC",
    "VKD3D_CONFIG",
    "ADDITIONAL_DLLS",
    "GAMESCOPE_W",
    "GAMESCOPE_H",
    "GAMESCOPE_W_OUT",
    "GAMESCOPE_H_OUT",
    "GAMESCOPE_ARGS",
    "USE_GAMESCOPE",
}


def data_from_config(config: GameConfig) -> dict[str, str | list[str]]:
    """Serialise a GameConfig back to conf keys."""
    from launcher import platform as _platform

    windows = _platform.is_windows()
    data: dict[str, str | list[str]] = {"GAME_EXECUTABLE": config.executable}
    if config.name:
        data["GAME_NAME"] = config.name

    for key, attr in _SCALARS.items():
        if key == "GAME_EXECUTABLE":
            continue
        if windows and key in _WINDOWS_SKIP_KEYS:
            continue
        value = getattr(config, attr)
        if value and value != getattr(_DEFAULTS, attr):
            data[key] = value

    if not windows and config.use_gamescope:
        data["USE_GAMESCOPE"] = "1"
        for key in ("GAMESCOPE_W", "GAMESCOPE_H", "GAMESCOPE_W_OUT",
                    "GAMESCOPE_H_OUT", "GAMESCOPE_ARGS"):
            data[key] = getattr(config, _SCALARS[key])

    for key, attr in _ARRAYS.items():
        if windows and key == "ADDITIONAL_DLLS":
            continue
        value = getattr(config, attr)
        if value:
            data[key] = value
    return data


class GameRepository:
    """The set of configured games."""

    def __init__(self, paths: Paths, state: StateStore) -> None:
        self._paths = paths
        self._state = state

    def conf_path(self, name: str) -> Path:
        return self._paths.games_dir / f"{name}.conf"

    def list_games(self) -> list[Game]:
        """Every game in games/, with its stored state attached."""
        games_dir = self._paths.games_dir
        if not games_dir.is_dir():
            return []
        stats = self._state.all_stats()
        games: list[Game] = []
        for conf in sorted(games_dir.glob("*.conf")):
            name = conf.stem
            config = config_from_data(name, load(conf))
            games.append(
                Game(
                    config=config,
                    conf_path=conf,
                    stats=stats.get(name, GameStats()),
                    executable_exists=self._executable_exists(config),
                )
            )
        return games

    @staticmethod
    def _executable_exists(config: GameConfig) -> bool:
        return bool(config.executable) and os.path.isfile(config.executable)

    def get(self, name: str) -> Game | None:
        conf = self.conf_path(name)
        if not conf.is_file():
            return None
        config = config_from_data(name, load(conf))
        return Game(
            config=config,
            conf_path=conf,
            stats=self._state.get(name),
            executable_exists=self._executable_exists(config),
        )

    def exists(self, name: str) -> bool:
        return self.conf_path(name).is_file()

    def add(self, config: GameConfig) -> Path:
        """Write a new game's config. Raises if the name is taken."""
        self._paths.games_dir.mkdir(parents=True, exist_ok=True)
        conf = self.conf_path(config.name)
        if conf.exists():
            raise FileExistsError(conf)
        save(conf, data_from_config(config))
        self._state.mark_added(config.name)
        return conf

    def update(self, config: GameConfig) -> Path:
        """Overwrite an existing game's config."""
        conf = self.conf_path(config.name)
        save(conf, data_from_config(config))
        return conf

    def rename(self, old_name: str, new_name: str) -> Path:
        """Move a game's config and carry its state across."""
        old_conf = self.conf_path(old_name)
        new_conf = self.conf_path(new_name)
        if not old_conf.is_file():
            raise FileNotFoundError(old_conf)
        if new_conf.exists():
            raise FileExistsError(new_conf)

        data = load(old_conf)
        data["GAME_NAME"] = new_name
        save(new_conf, data)
        old_conf.unlink()
        self._state.rename(old_name, new_name)
        return new_conf

    def remove(self, name: str) -> bool:
        """Delete a game's config and its stored state."""
        conf = self.conf_path(name)
        if not conf.is_file():
            return False
        conf.unlink()
        self._state.remove(name)
        return True
