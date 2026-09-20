"""Game discovery, favorites, and CRUD operations."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from launcher.config_parser import load, save

_BASE_DIR = Path(__file__).resolve().parent.parent
_GAMES_DIR = _BASE_DIR / "games"
_HEROES_DIR = _BASE_DIR / "launcher" / "heroes"
_FAVORITES_PATH = Path.home() / ".config" / "launcher" / "favorites.json"

# Extensions a hero image may be stored with, in lookup order.
_HERO_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


@dataclass
class Game:
    name: str
    conf_path: Path
    executable: str = ""
    game_id: str = "480"
    game_args: list[str] = field(default_factory=list)
    custom_proton_path: str = ""
    additional_dlls: list[str] = field(default_factory=list)
    use_gamescope: bool = False
    gamescope_w: str = "1280"
    gamescope_h: str = "720"
    gamescope_w_out: str = "1920"
    gamescope_h_out: str = "1080"
    gamescope_args: str = "-f -e"
    override_app_id: str = ""
    extra_vars: list[str] = field(default_factory=list)
    proton_use_wine_sync: str = ""
    winedebug: str = ""
    radv_perftest: str = ""
    pulse_latency_msec: str = ""
    vkd3d_config: str = ""
    is_favorite: bool = False
    executable_exists: bool = True

    @property
    def hero_path(self) -> Path | None:
        """Return the hero image path if it exists, else None."""
        for ext in _HERO_EXTS:
            p = _HEROES_DIR / f"{self.name}{ext}"
            if p.is_file():
                return p
        return None

    @property
    def conf_name(self) -> str:
        """Return the .conf filename without extension."""
        return self.conf_path.stem


def _load_favorites() -> set[str]:
    """Load the set of favorited game names."""
    if _FAVORITES_PATH.is_file():
        try:
            return set(json.loads(_FAVORITES_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def _save_favorites(favs: set[str]) -> None:
    """Persist the favorites set."""
    _FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FAVORITES_PATH.write_text(json.dumps(sorted(favs), indent=2), encoding="utf-8")


def _as_list(value: str | list[str] | None) -> list[str]:
    """Ensure a config value is returned as a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _game_from_conf(conf_path: Path, favs: set[str]) -> Game:
    """Build a Game dataclass from a .conf file."""
    data = load(conf_path)
    name = conf_path.stem
    executable = str(data.get("GAME_EXECUTABLE", ""))
    return Game(
        name=name,
        conf_path=conf_path,
        executable=executable,
        game_id=str(data.get("GAMEID", "480")),
        game_args=_as_list(data.get("GAME_ARGS")),
        custom_proton_path=str(data.get("CUSTOM_PROTON_PATH", "")),
        additional_dlls=_as_list(data.get("ADDITIONAL_DLLS")),
        use_gamescope=str(data.get("USE_GAMESCOPE", "0")) == "1",
        gamescope_w=str(data.get("GAMESCOPE_W", "1280")),
        gamescope_h=str(data.get("GAMESCOPE_H", "720")),
        gamescope_w_out=str(data.get("GAMESCOPE_W_OUT", "1920")),
        gamescope_h_out=str(data.get("GAMESCOPE_H_OUT", "1080")),
        gamescope_args=str(data.get("GAMESCOPE_ARGS", "-f -e")),
        override_app_id=str(data.get("OVERRIDE_APP_ID", "")),
        extra_vars=_as_list(data.get("extra_vars")),
        proton_use_wine_sync=str(data.get("PROTON_USE_WINE_SYNC", "")),
        winedebug=str(data.get("WINEDEBUG", "")),
        radv_perftest=str(data.get("RADV_PERFTEST", "")),
        pulse_latency_msec=str(data.get("PULSE_LATENCY_MSEC", "")),
        vkd3d_config=str(data.get("VKD3D_CONFIG", "")),
        is_favorite=name in favs,
        executable_exists=os.path.isfile(executable) if executable else False,
    )


def scan_games() -> list[Game]:
    """Scan the games/ directory and return all discovered games."""
    favs = _load_favorites()
    games: list[Game] = []
    if not _GAMES_DIR.is_dir():
        return games
    for conf in sorted(_GAMES_DIR.glob("*.conf")):
        games.append(_game_from_conf(conf, favs))
    return games


def toggle_favorite(game_name: str) -> bool:
    """Toggle favorite status. Returns the new state."""
    favs = _load_favorites()
    if game_name in favs:
        favs.discard(game_name)
    else:
        favs.add(game_name)
    _save_favorites(favs)
    return game_name in favs


def remove_game(game_name: str) -> bool:
    """Delete a game's .conf file. Returns True on success."""
    conf = _GAMES_DIR / f"{game_name}.conf"
    if conf.is_file():
        conf.unlink()
        return True
    return False


def _build_data(game: Game) -> dict[str, str | list[str]]:
    """Build the data dict for writing a .conf file from a Game."""
    d: dict[str, str | list[str]] = {"GAME_EXECUTABLE": game.executable}
    if game.name:
        d["GAME_NAME"] = game.name
    if game.game_id and game.game_id != "480":
        d["GAMEID"] = game.game_id
    if game.game_args:
        d["GAME_ARGS"] = game.game_args
    if game.custom_proton_path:
        d["CUSTOM_PROTON_PATH"] = game.custom_proton_path
    if game.additional_dlls:
        d["ADDITIONAL_DLLS"] = game.additional_dlls
    if game.use_gamescope:
        d["USE_GAMESCOPE"] = "1"
        d["GAMESCOPE_W"] = game.gamescope_w
        d["GAMESCOPE_H"] = game.gamescope_h
        d["GAMESCOPE_W_OUT"] = game.gamescope_w_out
        d["GAMESCOPE_H_OUT"] = game.gamescope_h_out
        d["GAMESCOPE_ARGS"] = game.gamescope_args
    if game.override_app_id:
        d["OVERRIDE_APP_ID"] = game.override_app_id
    if game.extra_vars:
        d["extra_vars"] = game.extra_vars
    if game.proton_use_wine_sync:
        d["PROTON_USE_WINE_SYNC"] = game.proton_use_wine_sync
    if game.winedebug:
        d["WINEDEBUG"] = game.winedebug
    if game.radv_perftest:
        d["RADV_PERFTEST"] = game.radv_perftest
    if game.pulse_latency_msec:
        d["PULSE_LATENCY_MSEC"] = game.pulse_latency_msec
    if game.vkd3d_config:
        d["VKD3D_CONFIG"] = game.vkd3d_config
    return d


def add_game(game: Game) -> Path:
    """Create a new .conf file for the game. Returns the path."""
    _GAMES_DIR.mkdir(parents=True, exist_ok=True)
    conf_path = _GAMES_DIR / f"{game.name}.conf"
    game.conf_path = conf_path
    save(conf_path, _build_data(game))
    return conf_path


def update_game(game: Game) -> None:
    """Overwrite the .conf file for an existing game."""
    save(game.conf_path, _build_data(game))


def clear_hero_images(game_name: str, keep: Path | None = None) -> None:
    """Delete stored hero images for a game, except ``keep``.

    Lookup is by extension, so leaving an older file of a different extension
    behind would shadow the new artwork.
    """
    for ext in _HERO_EXTS:
        p = _HEROES_DIR / f"{game_name}{ext}"
        if keep is not None and p == keep:
            continue
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass


def set_hero_image(game_name: str, source_path: str) -> Path:
    """Copy an image into heroes/ with the correct name. Returns dest path."""
    _HEROES_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(source_path).suffix.lower()
    if ext not in _HERO_EXTS:
        ext = ".png"
    dest = _HEROES_DIR / f"{game_name}{ext}"
    shutil.copy2(source_path, dest)
    clear_hero_images(game_name, keep=dest)
    return dest
