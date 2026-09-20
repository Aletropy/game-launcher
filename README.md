# Game Launcher

A PySide6 launcher for running Windows games through Proton inside the
Steam Flatpak container.

## Install

```bash
./install.sh              # check dependencies, create the venv, install
./install.sh --check      # report dependencies and exit, changing nothing
./install.sh --uninstall  # remove the command and desktop entry
```

The installer checks for Python, bash, the Steam Flatpak and the optional
extras (gamescope, winetricks), creates `.venv`, installs PySide6, adds a
`game-launcher` command to `~/.local/bin` and a desktop entry so the app
appears in your menu. Nothing is installed system-wide and nothing needs
root. Uninstalling leaves your games, prefixes, artwork and settings
alone.

Games can also be launched straight from the shell:

```bash
./game-launcher.sh "Schedule I"
./game-launcher.sh --dry-run "Schedule I"   # print the resolved config, run nothing
./game-launcher.sh -exec /path/to/game.exe
```

`--dry-run` prints the prefix, Proton path, app id and environment a
launch would use — the quickest way to check a game's configuration
without a running Steam Flatpak.

## Architecture

```
launcher/
  domain/      models and rules. No Qt, no I/O, no globals.
    models.py    GameConfig, GameStats, Game, sorting and formatting
    config.py    reading and writing bash .conf files
    prefixes.py  prefix resolution, mirroring game-launcher.sh
  data/        persistence, each taking a Paths in its constructor
    paths.py         every filesystem location, as an object
    game_repository  games/*.conf
    settings_store   preferences (JSON)
    state_store      playtime, favourites, last played (SQLite)
  services/    side effects
    artwork/     specs, store + display cache, cleanup
    process.py   launching games and timing sessions
    saves.py     backing up and restoring save data
    prefix_tools winecfg / winetricks / open folder
    sgdb.py      SteamGridDB
    importer.py  finding games in a folder
    tasks.py     bounded background work
  app/         composition root and orchestration
    context.py           builds the object graph
    library_controller   library state and every mutation
    main.py              entry point
  ui/          views, which talk to the controller and nothing else
```

The rule that keeps this honest: nothing below `app/` imports a global,
and `ui/` never touches a repository. `AppContext.create(paths)` builds
everything in one place, which is what lets a test point the whole
application at a temporary directory:

```python
with tempfile.TemporaryDirectory() as d:
    ctx = AppContext.for_testing(Path(d))
```

`tests/smoke.py` is a dependency-free suite (33 tests) covering the
domain, the repositories, the services, the shell script and headless UI
construction:

```bash
.venv/bin/python tests/smoke.py
.venv/bin/ruff check launcher tests
.venv/bin/mypy launcher
```

## Using it

| | |
|---|---|
| Select a game | Shows its details. Selecting never launches. |
| Play | The Play button, a double-click, Enter, or `Ctrl+P` |
| Sort | By name, recently played, most played or recently added |
| Search | `Ctrl+F` |
| Add / import | `Ctrl+N` / `Ctrl+I` |
| Edit / settings | `Ctrl+E` / `Ctrl+,` |
| Refresh | `F5` |

Playtime is recorded per session. A session shorter than 20 seconds is
treated as a failed launch and does not count, so a game that crashes on
startup does not inflate the number.

**Importing** scans a folder for `.exe` files and guesses which are
games: installers, crash handlers, redistributables and anything inside
a Wine prefix are listed but unticked, and where a folder holds several
executables the largest is preferred. Review the list before importing.

**Artwork** can come from SteamGridDB (needs an API key, set in
Settings) or by dragging an image onto the detail panel.

**The ⋯ menu** on a selected game opens its prefix, runs winecfg or
winetricks against it, and backs up or restores that game's saves.
Backups land in `backups/<game>/<timestamp>` and copy the same
directories `repair-prefix.sh` does.

## Wine prefixes

By default every game shares one prefix, `./Prefix`. Writing a folder
name into `.prefix-name` changes which one.

A game can instead use its own, set in **Edit → Wine Prefix**:

| Value | Resolves to |
|---|---|
| *(empty)* | the shared prefix |
| `prefixes/Ds3` | `<launcher>/prefixes/Ds3` |
| `~/wine/ds3` | `$HOME/wine/ds3` |
| `/mnt/ssd/ds3` | exactly that |

The prefix is created on first launch. The dialog says so before you
save, and warns when a path is outside the launcher and home folders —
the game runs inside the Steam Flatpak container via `flatpak enter`, so
such a path may not be visible there without a `flatpak override`.

Moving a game to its own prefix does not carry over its saves or
registry; it will look freshly installed. Use the ⋯ → Saves menu, or
`repair-prefix.sh`, to move save data.

`launcher/domain/prefixes.py` and `resolve_conf_overrides()` in
`game-launcher.sh` implement the same rules, and a smoke test runs both
to prove they still agree.

## Artwork storage

Artwork is stored once per game per type, scaled to the size it is shown
at and re-encoded — a 600×900 source of ~800 KB becomes roughly 35 KB.

**Clean Up Artwork…** scans what is stored and offers to resize oversized
files, drop duplicates, and delete artwork belonging to games no longer
in the library. Each is a separate checkbox, the dialog shows exactly
what each reclaims, and nothing is deleted until you confirm. Re-encoding
replaces the original.

Removing a game deletes its artwork and recorded state with it.

## Per-game configuration

`games/<name>.conf` is sourced by `game-launcher.sh`. The filename stem
is the game's identity — renaming in the launcher moves the config, the
artwork, the favourite and the playtime together.

| Key | Effect |
|---|---|
| `GAME_EXECUTABLE` | the .exe to run |
| `GAME_ARGS` | arguments passed to it |
| `GAMEID` / `OVERRIDE_APP_ID` | Steam app id used for the Proton environment |
| `GAME_PREFIX` | per-game Wine prefix (see above) |
| `CUSTOM_PROTON_PATH` | Proton build to use, as a path inside the Flatpak |
| `ADDITIONAL_DLLS` | extra `WINEDLLOVERRIDES` entries |
| `USE_GAMESCOPE`, `GAMESCOPE_*` | gamescope wrapping and resolutions |
| `extra_vars` | environment variables, e.g. `("PROTON_NO_ESYNC=1")` |
| `WINEDEBUG`, `RADV_PERFTEST`, `PULSE_LATENCY_MSEC`, `VKD3D_CONFIG`, `PROTON_USE_WINE_SYNC` | exported as-is |

Values are escaped when written, so paths containing quotes, `$` or
backticks are safe even though the file is `source`d.

## Where things live

| | |
|---|---|
| Games | `games/*.conf` |
| Artwork | `launcher/artwork/{grid,hero,icon}/` |
| Prefixes | `Prefix/`, `prefixes/<game>/`, or wherever you point them |
| Save backups | `backups/<game>/<timestamp>/` |
| Preferences | `~/.config/launcher/settings.json` |
| Playtime and favourites | `~/.local/share/launcher/state.db` |
