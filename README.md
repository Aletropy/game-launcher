# Game Launcher

A PySide6 launcher for running Windows games through Proton inside the
Steam Flatpak container.

## Running

```bash
./install.sh     # creates .venv and installs PySide6
./run.sh         # starts the launcher
```

Games can also be launched straight from the shell:

```bash
./game-launcher.sh "Schedule I"
./game-launcher.sh --dry-run "Schedule I"   # print the resolved config, run nothing
./game-launcher.sh -exec /path/to/game.exe
```

`--dry-run` prints the prefix, Proton path, app id and environment a
launch would use. It is the quickest way to check a game's configuration
without a running Steam Flatpak.

## Layout

```
launcher/
  app.py           entry point
  core/            config parsing, the Game model, prefixes, settings, paths
  services/        artwork, process management, SteamGridDB, background tasks
  ui/              main window, widgets, dialogs, theme
games/*.conf       one bash config per game, sourced by game-launcher.sh
launcher/artwork/  stored artwork: grid/ hero/ icon/
game-launcher.sh   resolves the config and runs the game via flatpak enter
```

`tests/smoke.py` is a dependency-free suite covering config round-trips,
prefix resolution against the real shell script, the artwork service and
headless window construction:

```bash
.venv/bin/python tests/smoke.py
```

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
registry; it will look freshly installed. `repair-prefix.sh` and
`steam_flatpak_saves.sh` can copy save data between prefixes.

## Artwork

Artwork is stored once per game per type, scaled to the size it is shown
at and re-encoded — a 600×900 source of ~800 KB becomes roughly 35 KB.

**Clean Up Artwork…** in the toolbar scans what is stored and offers to:

- resize anything larger than it needs to be,
- drop duplicates of the same game stored under different file types,
- delete artwork belonging to games no longer in the library.

Each is a separate checkbox, the dialog shows exactly what each reclaims,
and nothing is deleted until you confirm. Re-encoding replaces the
original. The offer appears once, the first time it would help; after
that use the toolbar button.

Removing a game now deletes its artwork with it.

## Per-game configuration

`games/<name>.conf` is sourced by `game-launcher.sh`. The filename stem
is the game's identity — renaming in the launcher moves the config, the
artwork and the favourite together.

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
