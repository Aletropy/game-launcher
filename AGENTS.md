# AGENTS.md

## Stack

- Single Python package `launcher` (PySide6, Qt) + `server/` (stdlib+SQLite only) + shell scripts. Python >=3.11. No monorepo, no pytest.
- Project root is the launcher install dir itself (`games/`, `Prefix/`, `prefixes/`, `Saves/`, `backups/` live here). `launcher/data/paths.py:PROJECT_ROOT` derives it from file location — don't hardcode paths.

## Commands

```bash
./install.sh --check              # verify deps without changing anything
./install.sh                      # create .venv, pip install, add ~/.local/bin/game-launcher + desktop entry
.venv/bin/python tests/smoke.py   # 85 tests, custom runner — no pytest
.venv/bin/ruff check launcher tests
.venv/bin/mypy launcher
./package.sh                      # runs ruff+mypy+smoke gate, then builds dist/*.tar.gz + dist/*.run + *-src.tar.gz + *-bundle.tar.gz
./package.sh --no-check           # skip the gate
./package.sh --clean              # remove dist/
python -m server                  # friends server on 127.0.0.1:8765 (LAN default 10.0.0.25:8765); --host/--port/--db/--quiet
LAUNCHER_FRIENDS_SERVER=http://127.0.0.1:8765 ./run.sh   # point launcher at local friends server
./game-launcher.sh --dry-run "Game Name"  # print resolved prefix/Proton/app-id/env without launching
```

- Headless Qt: `QT_QPA_PLATFORM=offscreen` is required for `tests/smoke.py` and any `from launcher.app.main import build_window` import outside a display (see `tests/smoke.py:22`, `package.sh:617`).
- `install.sh`/`package.sh`/`game-launcher.sh` must remain executable and pass `bash -n`; `package.sh:verify_staging` enforces this.

## Architecture

```
launcher/domain/   pure models/rules — no Qt, no I/O, no globals (models.py, config.py, prefixes.py, journal.py, backup_policy.py)
launcher/data/     persistence, each takes Paths in ctor (paths.py, game_repository.py, settings_store.py, state_store.py)
launcher/services/ side effects (artwork/, process.py, save_store.py, backups.py, prefix_tools.py, sgdb.py, importer.py, tasks.py)
launcher/app/      composition root — AppContext.create(paths) wires everything (context.py, library_controller.py, save_keeper.py, main.py)
launcher/ui/       views talk only to LibraryController, never to repositories
server/            not shipped in release archives
```

- Dependency rule: nothing below `app/` imports a global; `ui/` never touches a repository. `AppContext.create()` is the only place that builds the graph.
- Tests isolate via temp dir: `with tempfile.TemporaryDirectory() as d: ctx = AppContext.for_testing(Path(d))` (`launcher/app/context.py:78`, `launcher/data/paths.py:46`). Never touch real `games/`, `~/.config/launcher/`, or `~/.local/share/launcher/` in tests.
- `AppContext.for_testing` puts `base/config/data` all under one tmp root; `Paths.default()` uses XDG vars.

## Gotchas

- `game-launcher.sh` rewrites itself with `sed` on `"$0"` (`wrap()` at `game-launcher.sh:143`). Keep it a plain executable file, byte-identical through packaging (`package.sh:187` checks `cmp -s`). Never bundle or rewrite it.
- Prefix resolution is duplicated: `launcher/domain/prefixes.py:resolve` and `game-launcher.sh:resolve_conf_overrides` must agree. `tests/smoke.py:prefix_resolution_matches_the_shell` runs both via `--dry-run` and diffs `WINEPREFIX`.
- `Saves/` must stay under `base` (`launcher/data/paths.py:77`). Games resolve symlinks inside the Steam Flatpak container — a store outside is refused (`launcher/domain/save_layout.py:store_is_reachable`, `tests/smoke.py:a_store_outside_the_launcher_folder_is_refused`).
- `games/*.conf` are bash-sourced files with escaped values (`launcher/domain/config.py`). `ADDITIONAL_DLLS`, `GAME_PREFIX`, `CUSTOM_PROTON_PATH`, `OVERRIDE_APP_ID`, and `extra_vars` all flow through `resolve_conf_overrides`; `extra_vars` splitting only when every token is `KEY=VALUE`.
- `.gitignore` hides `Prefix/`, `prefixes/`, `Saves/`, `backups/`, `launcher/artwork/`, `launcher/heroes/`, `games/*.conf`, `.venv/`. `package.sh` allowlists `PAYLOAD` and rejects private data; `git archive` builds `*-src.tar.gz` from tracked files only. Don't add user data to the allowlist.
- Artwork: files are classified by real shape (`launcher/services/artwork/specs.py:classify`), not requested type — portrait saved as `hero` goes to `grid/`. `AppContext.create` calls `reclassify_misfiled()` on startup.
- Save backups: hardlink unchanged files, reflink on btrfs/XFS, skip caches (`dxvk`, `Temp`, `D3DSCache`, `cache`/`shadercache` + `Settings → Saves & backups` extras). Never link live `Saves/` files into snapshots. Partial snapshots (`*.partial`) are ignored and cleaned on next `create`.
- Wine links are verified before every launch — `wineboot` replaces symlinks with dirs on Proton update. `game-launcher.sh` direct launch bypasses the check; launcher's `SaveKeeper.before_launch` repairs first.
- Sessions <20s are discarded (`launcher/services/process.py:MIN_SESSION_SECONDS`).
- `TaskGroup` tokens must fit 32-bit `Signal(int)`; `TaskGroup.cancel_all()` + `submit` is tested for overflow.
- KDE single-click style: `tests/smoke.py:_single_click_style` forces `SH_ItemView_ActivateItemOnSingleClick` to catch single-click-launch bugs under Fusion.
