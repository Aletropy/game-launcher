# Milso Launcher

A PySide6 game library: artwork, playtime, saves, backups and friends.

Linux is the main version: it runs Windows games through Proton inside
the Steam Flatpak container. Windows is a sub-app for managing the same
kind of library natively — it runs each game's `.exe` directly, with no
Proton, no prefixes and no Flatpak. One codebase, one version number;
`launcher/platform.py` is the single branch point (see Platforms below).

## Install

One file, run once:

```bash
./milso-launcher-2.4.1.run             # install, or upgrade in place
./milso-launcher-2.4.1.run --target DIR
./milso-launcher-2.4.1.run --yes       # no questions
./milso-launcher-2.4.1.run --check     # dependencies only, changes nothing
./milso-launcher-2.4.1.run --extract DIR
```

It verifies its own payload, unpacks itself, finds an existing
installation if there is one, and runs the setup. It picks the target in
this order: `--target`, an installation in the current directory, the
one the `milso-launcher` command already points at, then
`~/.local/share/milso-launcher`.

**Upgrading an existing project** keeps everything that is yours:
`games/`, `Prefix/`, `prefixes/`, `backups/`, `launcher/artwork/`,
`launcher/heroes/`, `.prefix-name` and the virtualenv. Only the
application source and the helper scripts are replaced, the previous
version is archived to `.upgrade-backup-<timestamp>.tar.gz` first, and
modules that no longer exist upstream are removed so they cannot shadow
the new layout. Settings and playtime live outside the project and are
never touched.

Without a terminal and without `--yes` it refuses rather than guessing.

If you already have the source tree, `install.sh` does the same setup:

```bash
./install.sh              # check dependencies, create the venv, install
./install.sh --check      # report dependencies and exit, changing nothing
./install.sh --uninstall  # remove the command and desktop entry
```

The installer checks for Python, bash, the Steam Flatpak and the optional
extras (gamescope, winetricks), creates `.venv`, installs PySide6, adds a
`milso-launcher` command to `~/.local/bin` and a desktop entry so the app
appears in your menu. Nothing is installed system-wide and nothing needs
root. If Python 3.11+ is missing it offers to install it via your package
manager (Debian/Ubuntu `apt`, Fedora `dnf`, Arch `pacman`, openSUSE
`zypper`); with `--yes` it installs without asking. Uninstalling leaves
your games, prefixes, artwork and settings alone.

## Install on Windows

Extract the `-win.zip` from the same release, then run once:

```bat
setup-win.bat            :: install into %LOCALAPPDATA%\MilsoLauncher
setup-win.bat -Target DIR -Yes
```

It installs Python 3.11+ via `winget` when missing, creates `.venv`,
installs PySide6 and adds a Start Menu shortcut. `run-win.bat` starts
the app from the folder. Upgrading keeps `games/`, `Saves/`,
`backups/`, artwork and settings.

## Building a release

```bash
./package.sh              # dist/*.run, dist/*-win.zip and dist/*.tar.gz
./package.sh --no-check   # skip the test and lint gate
./package.sh --clean      # remove dist/
```

It produces five artifacts (all checksummed with SHA-256):

| | |
|---|---|
| `*-bundle.tar.gz` | one `.tar.gz` to send by mail, chat or a USB stick |
| `*.run` | Linux: one file; run it once to install or upgrade in place |
| `*-win.zip` | Windows sub-app: extract and run `setup-win.bat` |
| `*.tar.gz` | the same payload as a plain archive |
| `*-src.tar.gz` | the whole project, to publish anywhere |

The bundle is what to send someone directly. Mail and chat clients
routinely block executables, so it wraps the `.run` in a `.tar.gz`
alongside a plain-text `INSTALL.txt`, the source archive, the README and
`SHA256SUMS`. The instructions say to `chmod +x` the installer, and it
also runs as `bash milso-launcher-<version>.run`, so a transport that
drops the executable bit cannot break it.

The `.run` is the release archive appended to `installer/header.sh`
after a `__PAYLOAD_BELOW__` marker, with the payload's SHA-256 baked
into the header; the header seeks past itself to read it back and
refuses a payload that does not match.

The source archive is built with `git archive` from `HEAD`, so it can
only contain tracked files — the game library, stored artwork, Wine
prefixes and the virtualenv are all ignored and cannot slip in. It is
checked afterwards for game configs, artwork, local state and any
mention of your home directory, and the build fails if it finds any.

Your own games are deliberately not tracked: `games/*.conf` hold
absolute paths into your home directory and describe your private
library. `games/.gitkeep` keeps the folder in a clone.

The archive carries the source, the scripts, the icon and the docs, with
an empty `games/` folder. It leaves out the virtualenv, Wine prefixes,
artwork, save backups, caches and your own games, and a check refuses to
build if any of those sneak in.

`milso-launcher.sh` ships as a plain executable file and is verified
byte-identical to the original. It is never bundled or rewritten: it
rewrites its own source with `sed` on `"$0"`, so it has to stay a
readable file on disk to work at all.

Packaging runs the tests, ruff and mypy first, then extracts the
finished archive and checks it imports, so a broken build cannot ship.
Archives are reproducible — two builds of the same tree are
byte-identical.

To install elsewhere:

```bash
tar xzf milso-launcher-2.4.1.tar.gz
cd milso-launcher-2.4.1
./install.sh
```

Games can also be launched straight from the shell:

```bash
./milso-launcher.sh "Schedule I"
./milso-launcher.sh --dry-run "Schedule I"   # print the resolved config, run nothing
./milso-launcher.sh -exec /path/to/game.exe
```

`--dry-run` prints the prefix, Proton path, app id and environment a
launch would use — the quickest way to check a game's configuration
without a running Steam Flatpak.

## Developing

`./run.sh` runs this checkout in an isolated sandbox: settings, playtime
and cache live in `.sandbox/` inside the project, never in
`~/.config/milso-launcher` or `~/.local/share/milso-launcher`, so dev runs
cannot disturb the installed app — both can even run side by side. Games,
Saves/, prefixes and artwork are already project-local and shared.

```bash
./run.sh              # sandboxed dev run
./run.sh --seed       # one-time copy of prod settings + playtime
MILSO_SANDBOX=0 ./run.sh   # dev code, real user data
```

## Architecture

```
launcher/
  platform.py    the single OS branch point: is_windows() / is_linux()
  domain/      models and rules. No Qt, no I/O, no globals.
    models.py    GameConfig, GameStats, Game, sorting and formatting
    config.py    reading and writing bash .conf files
    prefixes.py  prefix resolution, mirroring milso-launcher.sh (Linux only)
    prefix_health  prefix size, freshness and broken save links (Linux only)
    crash_signatures  telling a crash from a quit
    outcome.py   typed Ok/Err results and launch blocks
    journal.py   play sessions: heatmap, streaks, totals
    backup_policy  what backups leave out and how long they are kept
    friends.py   snapshots, leaderboards and games in common
  data/        persistence, each taking a Paths in its constructor
    paths.py         every filesystem location, as an object (XDG or %APPDATA%)
    game_repository  games/*.conf (Proton keys skipped when writing on Windows)
    settings_store   preferences (JSON)
    preferences      typed access over the settings
    state_store      playtime, sessions, favourites, tags (SQLite)
  services/    side effects
    artwork/     specs, store + display cache, cleanup
    process.py   launching games and timing sessions (Proton script vs raw .exe)
    sessions.py  active launches on disk (locked) and pending sidecars
    session_watcher.py  detached per-game watcher for full playtime
    game_log.py  per-game log files that survive restarts
    save_store.py  the shared Saves/ folder and the links into it (Linux only)
    win_saves.py  Windows save auto-discovery + copy-only mirror into Saves/<Game>/
    save_exchange.py  export/import saves as zip archives
    backups.py   incremental snapshots of Saves/, and restoring them
    prefix_tools winecfg / winetricks / open folder / rebuild (Linux only)
    protons.py   installed Proton builds for the game editor (Linux only)
    steam_import.py  installed Steam games worth adding (per-OS library roots)
    shortcuts.py per-game entries (.desktop on Linux, Start Menu .url on Windows)
    updates.py   GitHub Releases checks, download and install (per-OS asset)
    sgdb.py      SteamGridDB
    importer.py  finding games in a folder
    tasks.py     bounded background work
  app/         composition root and orchestration
    context.py           builds the object graph
    library_controller   library state and every mutation
    session_recorder     launches, sessions and crash diagnosis
    launch_checks        pre-launch blocks and warnings (Steam/Proton checks Linux only)
    single_instance      one copy per user, with request forwarding
    startup.py           per-stage startup timings
    save_keeper          automatic sharing and backups (mirror on Windows)
    main.py              entry point
  ui/          views, which talk to the controller and nothing else
    tray.py        the system tray icon and its live menu
    close_policy.py  hide vs. confirm vs. quit, without Qt
    errors.py      one consistent way to show failures
```

The rule that keeps this honest: nothing below `app/` imports a global,
and `ui/` never touches a repository. `AppContext.create(paths)` builds
everything in one place, which is what lets a test point the whole
application at a temporary directory:

```python
with tempfile.TemporaryDirectory() as d:
    ctx = AppContext.for_testing(Path(d))
```

`tests/smoke.py` is a dependency-free suite covering the domain, the
repositories, the services, the shell script and headless UI
construction; feature tests live in `tests/cases/test_*.py`, one module
per area, loaded by the same runner so CI needs one command:

```bash
.venv/bin/python tests/smoke.py
.venv/bin/ruff check launcher tests
.venv/bin/mypy launcher
```

## Platforms

Linux is the main version; Windows is a sub-app sharing one codebase
and one version number. The rule: `launcher/platform.py` owns every OS
check — call sites use `platform.is_windows()`, never `sys.platform`
directly — so Linux behaviour stays untouched behind the gate.

Shared core (both): library, artwork, playtime/sessions/journal,
backups/export/import, friends, updates framework, SteamGridDB import.

Linux only: `milso-launcher.sh` (Flatpak enter + Proton), Wine prefixes
(`domain/prefixes.py`, prefix tools, Proton picker, gamescope), the
symlinked shared save store (`services/save_store.py`), `.desktop`
shortcuts, XDG paths.

Windows only: direct `.exe` launch (`services/process.py`), native save
auto-discovery (`services/win_saves.py`, copy-only mirror into
`Saves/<Game>/`, symlinks never created), Start Menu `.url` shortcuts,
`%APPDATA%`/`%LOCALAPPDATA%` paths, `installer/setup-win.{bat,ps1}` and
`run-win.bat`. The game editor hides Compatibility, App ID, Gamescope
and Proton/driver fields; Proton keys in old confs still load but are
never written back.

## Using it

| | |
|---|---|
| Select a game | Shows its details. Selecting never launches. |
| Play | The Play button, a double-click, Enter, or `Ctrl+P` |
| Sort | Name A–Z or Z–A, last played, most or least played, recently added, most launched; optionally favourites first |
| Filter | Favourites, running now, missing a cover, installed or missing, played or never played, shared or own prefix |
| Search | `Ctrl+F` |
| Add / import | `Ctrl+N` / `Ctrl+I` |
| Edit / settings | `Ctrl+E` / `Ctrl+,` |
| Refresh | `F5` |
| Quit entirely | `Ctrl+Q` |

Playtime is recorded per session. A session shorter than 20 seconds is
treated as a failed launch and does not count, so a game that crashes on
startup does not inflate the number. How each session ended (exit code,
crashed or not) is kept with it.

**Staying in the tray.** The first time the launcher starts it asks
whether closing the window should keep it in the system tray; Settings →
Library changes it later. In the tray, left-click shows the window and
the menu shows running games with live timers, per-game Stop and Quit.
Playtime keeps counting with the window closed. Quitting never kills a
game: a detached watcher records its full session when it exits, even if
the launcher is gone by then. Reopening while a game is still running
shows it as playing again, with its timer picked up where it left off.

Only one copy runs per user. Starting it again (or
`milso-launcher --play "Name"`, which desktop shortcuts use) forwards to
the running one and exits.

**When a game fails.** Before launching, the launcher checks the
executable, the prefix, the Steam Flatpak, the Proton path and free disk
on Linux (executable and free disk on Windows), and tells you everything at once instead of one dialog per problem. When
a session looks like a crash, a failure card names the likely cause,
shows the log tail, and offers Copy log, a `--dry-run` of the launch
configuration, and Open prefix. Game output is also kept in
`~/.local/share/milso-launcher/logs/` across restarts.

**Collections.** The ⋯ menu holds Tags & notes (comma-separated tags,
free-form notes) and Hide. Search finds games by tag, Filters offers
every tag in use and a Show-hidden toggle, and Settings → Data can clear
them. The **Covers** button above the library swaps the list for a large,
fast cover grid; clicking a cover returns to the library on that game,
double-clicking plays it.

**Sessions.** The ⋯ menu's Sessions… lists one game's sessions with
their dates, lengths and outcomes. Delete, correct or manually add a
session; totals follow. A desktop shortcut per game (⋯ → Desktop
shortcut) starts it from the menu or taskbar.

**Importing** scans a folder for `.exe` files and guesses which are
games: installers, crash handlers, redistributables and anything inside
a Wine prefix are listed but unticked, and where a folder holds several
executables the largest is preferred. Review the list before importing.
The Steam button reads installed Steam games (name, app id and best
`.exe` guess) and ticks the ones missing from your library.

Filters are remembered between sessions. The count under the list says
how many games they hide, with a link that clears them.

**Artwork** (⋯ → Artwork…) is a wizard. Find the game on SteamGridDB,
then pick a cover, banner, logo and icon from everything it has,
filtered by style, portrait shape, adult and humour content. Each step
also takes a local file, keeps what is there, or removes it. The right
side is the real library row, banner, Journal cover and the icon at
every size it is drawn, redrawn from your picks; thumbnails show at once
and are replaced by the full image as it downloads. Nothing is saved
until Apply. Without an API key the wizard still works with files, and
an image can also be dragged onto the detail panel.

**Clear data** (⋯ → Clear data…, or Settings → Data) clears any mix of
play history, total playtime, last played and launch counts, favourites,
artwork and logs, for one game or all of them, and can forget games no
longer in the library. A copy of the database is saved to
`~/.local/share/milso-launcher/state-backups/` first; the last five are kept.

**Appearance** (Settings → Appearance) has seven themes: Midnight,
Harbour, Nebula, Frost, Ember, Pitch Black and the light Paper. You can
also choose any accent colour, square, rounded or soft corners, compact,
comfortable or spacious density, text size and font. Changes preview
live, and Cancel puts the old look back.

**Your own themes.** New theme… (or the + card) opens a three-step
wizard. First, start from any theme, or give a background and an accent
colour and let the rest be generated; *Surprise me* picks a pairing.
Next, fine-tune each of the twenty colours by swatch or hex. Last, name
it. A miniature launcher built from the real widgets previews every
change, and a readability check rates text against its background with
WCAG contrast ratios, warning before you save something hard to read.
Themes are JSON files in `~/.config/milso-launcher/themes/`: Edit, Delete,
Import and Export work on them from the same page.

**Settings** is a sidebar of pages: Appearance, Library, Artwork, Saves
& backups, Data, Prompts and About (version, and where everything is
stored with a button to open each). Tools sit on the page they belong
to. The toolbar keeps only Library and Journal, a Saves menu (shared
saves, backups, back up now) and Settings. The game editor has General,
Compatibility, Display and Advanced tabs on Linux; on Windows
Compatibility is hidden and Advanced keeps only Environment. Advanced
includes the Proton and driver variables (`WINEDEBUG`, `VKD3D_CONFIG`
and friends).

**The ⋯ menu** on a selected game opens its prefix, runs winecfg or
winetricks against it (Linux only), and backs up saves or opens the
backups at that game's own folder.

**Journal**, the second view, is about time rather than games: a banner
to continue the last game, total and weekly playtime, the current day
streak, the longest session, a six-month activity heatmap (hover a day
to see what was played), recently played covers and a most-played chart.
Playtime recorded before sessions existed appears once, on the day each
game was last played, marked as approximate.

## Shared saves

On Linux, per-game prefixes are cheap to rebuild, but save data normally
lives inside the prefix, so rebuilding one loses the saves and the same
game in another prefix starts fresh. The shared store fixes that: one
copy of the Windows user profile in `Saves/`, symlinked into every
prefix.

On Windows there are no prefixes, so there is nothing to link. Instead
the launcher auto-discovers native save folders (`%APPDATA%`,
`%LOCALAPPDATA%`, `LocalLow`, `Documents`, `Saved Games`,
`ProgramData`, the game's own folder) by matching the game and exe
names, and mirrors confirmed folders copy-only into
`Saves/<Game>/` — natives are only ever read, never moved or linked.
Everything below (backups, export/import, conflicts) then works on
`Saves/` exactly as on Linux.

```
Saves/
  AppData/{Local,LocalLow,Roaming}
  Documents/
  Saved Games/
  ProgramData/
  .conflicts/<timestamp>/    losers from a merge, never deleted
  .manifest.json
```

Six links per prefix. `AppData`'s children are linked individually
rather than `AppData` itself, so it stays a real directory and Wine's
own aliases keep working.

**Saves → Shared saves…** in the toolbar shows every prefix and its state.
Sharing one previews exactly what will move before touching anything.
Where the same file exists on both sides the newer wins and the other
goes to `Saves/.conflicts/`; nothing is deleted. Moves within one
filesystem are renames, so adopting 4.5 GB takes seconds.

The store has to live inside the launcher folder. Games resolve these
links *inside* the Steam Flatpak container, which can see this directory
but not arbitrary paths elsewhere — a store outside it would make every
save folder look empty in-game, so it is refused.

`wineboot` recreates missing user folders when Proton updates and will
replace a symlink with a real directory, quietly splitting your saves.
The links are therefore verified before every launch; anything written
into a replacement is merged back into the store and the link restored.
Launching `./milso-launcher.sh` directly bypasses that check.

**Every prefix is shared by default.** On startup, before a game starts
and after it exits (a new prefix only exists after its first run), any
prefix still keeping its own saves is merged into the store, with a
backup taken first. Turn this off in Settings → Saves & backups; **Share all** in
the Shared Saves window does the same on demand.

**Stop sharing** gives a prefix its own copy again. The store keeps its
data, so this costs disk but never loses anything.

Two consequences worth knowing. The whole profile is shared, so shader
caches, anti-cheat and launcher installs are shared too — one Ubisoft
login across prefixes, but also one corrupt `EasyAntiCheat` for
everything. And rebuilding a prefix no longer clears bad state that
lives in `AppData`.

## Save backups

Snapshots of `Saves/` go to `backups/saves/<timestamp>/data`, a plain
copy you can browse without the launcher. They cost little:

- A file unchanged since the previous snapshot is a hard link to that
  snapshot's copy, so it takes no space.
- A changed file is cloned (reflink) on btrfs and XFS, which also takes
  no space until either copy changes; elsewhere it is copied.
- Caches are left out: `dxvk`, `Temp`, `D3DSCache`, `Package Cache` and
  any folder named `cache`, `shadercache` or similar. Add your own in
  Settings → Saves & backups, e.g. a mod folder.

On this machine a first snapshot of 3.4 GB took 1.3 s and no extra disk,
and the next one copied only the 2.5 KB that had changed. Before
writing anything, a snapshot checks there will still be 512 MB free
afterwards. Snapshots are never linked to the live files, so a game
rewriting a save in place cannot reach into a backup.

A snapshot is taken automatically:

- after playing, at most every 30 minutes;
- before sharing a prefix, repairing links, or restoring.

Retention keeps the latest 5, then the newest per day for 7 days and per
week for 4 weeks. Manual backups (**Back up now**) are kept until
deleted, as is any snapshot marked **Keep forever**. All of it can be
changed in Settings → Saves & backups.

**Backups…** (in the ⋯ → Saves menu, or the Shared Saves window) lists
the snapshots and what each holds. Opened from a game, it goes straight
to that game's folder. **Restore this folder** or **Restore everything**
puts files back as they were and removes files created since, leaving
excluded caches alone. It refuses while a game is running, refuses when
the disk would fill past the 512 MB margin, and always takes a snapshot
first, so a restore can itself be undone. **Verify** checks a snapshot
is complete and readable against its own manifest.

**Moving machines.** Saves → Export saves… writes the shared store (or
chosen folders) to a zip with a manifest; Import saves… previews an
archive, takes a safety snapshot, and merges it newer-wins, quarantining
every loser into `Saves/.conflicts/` like prefix sharing does.

## Wine prefixes

By default every game shares one prefix, `./Prefix`. Writing a folder
name into `.prefix-name` changes which one.

A game can instead use its own, set in **Edit → Wine Prefix**,
alongside a **Proton** picker listing the builds installed on the
machine (or a custom path, which is checked and warns when missing):

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
`repair-prefix.sh`, to move save data. The ⋯ → Prefix menu's **Rebuild
prefix…** deletes a prefix after showing its size and broken save links,
so Proton builds it fresh on next launch; saves are shared and survive.

`launcher/domain/prefixes.py` and `resolve_conf_overrides()` in
`milso-launcher.sh` implement the same rules, and a smoke test runs both
to prove they still agree.

## Artwork storage

Artwork is stored once per game per type, scaled to the size it is shown
at and re-encoded — a 600×900 source of ~800 KB becomes roughly 35 KB.

**Clean up artwork…** (Settings → Artwork) scans what is stored and offers to resize oversized
files, drop duplicates, and delete artwork belonging to games no longer
in the library. Each is a separate checkbox, the dialog shows exactly
what each reclaims, and nothing is deleted until you confirm. Re-encoding
replaces the original.

Removing a game deletes its artwork and recorded state with it.

## Friends

An opt-in tab that shows what friends are playing right now, the games
they play most, and a leaderboard for this week, all time, or one game.
**In common** lists the games you own that friends play too, with who
and how long on each side. There's no chat and nothing to reply to. The
only thing you can do with another user is send or answer a friend
request.

**Offline Mode is the default.** In Offline Mode the launcher makes no
network requests at all, and nothing outside the Friends tab changes
between modes. To go online, open Settings → Friends, choose *Online*,
then create a profile in the Friends tab. You get a friend code such as
`K7QX-29MB` to share. Friends appear once they accept your request.

Going online shares these with friends you have accepted:

- your display name
- your play history, including sessions recorded before you went online
- the game you're playing now, if you allow it
- your platform (`linux`, `windows`, or `unknown` for older clients)

"Playing now" only covers games started from the launcher. When you clear
play history under Settings → Data, it is cleared on the server too. If
you are offline at the time, it is cleared the next time you connect.
*Delete my friends profile* removes everything you shared.

### The friends server

The server is `server/`: standard-library Python and SQLite, with no
dependencies. It ships as source inside the release archives; run it
with:

```bash
python -m server                          # 127.0.0.1:8765, ./friends-server.db
python -m server --host 0.0.0.0           # reachable from other machines
python -m server --port 9000 --db /srv/friends.db --quiet
```

Launchers connect to `http://10.0.0.25:8765` by default. For now that is
the shared LAN server; you can change the address under Settings →
Friends. To develop against a local server, set the address with an
environment variable:

```bash
MILSO_FRIENDS_SERVER=http://127.0.0.1:8765 ./run.sh
```

The server uses plain HTTP, so run it only on a network you trust. To
expose it further, put it behind a reverse proxy with TLS (e.g. Caddy
or nginx) and keep the token database (`--db`) on a backed-up volume;
the server itself is stateless apart from that file. Tokens are stored
hashed on the server, and in
`~/.config/milso-launcher/friends.json` (mode 0600) on each client.

Profiles survive losing that file. Registering shows a recovery key
once — save it. The same `user_id` and friend code come back with:

```bash
python -m server --db friends-server.db admin users list
python -m server --db friends-server.db admin users search gabriel
python -m server --db friends-server.db admin users show ATTR-295Z
python -m server --db friends-server.db admin users reset-token ATTR-295Z \
  --server http://10.0.0.25:8765 --out /tmp/opencode/profile.json
milso-launcher --import-profile /tmp/opencode/profile.json
milso-launcher --export-profile ~/profile-backup.json
```

Upgrading keeps every login: the `devices` migration is additive and
idempotent, backs the DB up to `friends-server.db.pre-devices-*.bak`,
and old clients keep working for one release (`users.token_hash` is
kept as a fallback, then dropped).

## Updates

Releases carry one asset per platform (`.run` for Linux,
`-win.zip` for Windows) published on GitHub Releases (one per `v*`
tag, built by the release workflow). On startup, at most once a day,
the launcher asks the GitHub API for the latest release and compares
its tag numerically against the installed version; each platform picks
its own asset, so Linux never offers a Windows zip and vice versa.

When a newer release is out, a tiny `↓ version` button appears in the
top bar. Click it when ready: a dialog shows the release notes with
Install now, Later and Skip this version. Nothing is downloaded until
you pick Install now. Installing downloads the platform asset to the
cache, verifies its integrity, then runs it with `--yes` into the
current installation once the launcher quits — games, prefixes (Linux),
artwork and settings are kept, exactly like running the installer by
hand. It refuses while a game is running.

Settings → About shows the running version, a Check for updates
button, the GitHub repository checked (as `owner/name`), and whether to
check automatically. Skipped versions can be unskipped there; only that
version is silenced, newer ones still notify.

## Per-game configuration

`games/<name>.conf` is sourced by `milso-launcher.sh`. The filename stem
is the game's identity — renaming in the launcher moves the config, the
artwork, the favourite and the playtime together.

| Key | Effect |
|---|---|
| `GAME_EXECUTABLE` | the .exe to run |
| `GAME_ARGS` | arguments passed to it |
| `GAMEID` / `OVERRIDE_APP_ID` | Steam app id used for the Proton environment (Linux only) |
| `GAME_PREFIX` | per-game Wine prefix, see above (Linux only) |
| `CUSTOM_PROTON_PATH` | Proton build to use, as a path inside the Flatpak (Linux only) |
| `ADDITIONAL_DLLS` | extra `WINEDLLOVERRIDES` entries (Linux only) |
| `USE_GAMESCOPE`, `GAMESCOPE_*` | gamescope wrapping and resolutions (Linux only) |
| `extra_vars` | environment variables, e.g. `("PROTON_NO_ESYNC=1")` |
| `WINEDEBUG`, `RADV_PERFTEST`, `PULSE_LATENCY_MSEC`, `VKD3D_CONFIG`, `PROTON_USE_WINE_SYNC` | exported as-is (Linux only) |

Linux-only keys still load on Windows but are never written back.

Values are escaped when written, so paths containing quotes, `$` or
backticks are safe even though the file is `source`d.

## Where things live

| | |
|---|---|
| Games | `games/*.conf` |
| Artwork | `launcher/artwork/{grid,hero,icon}/` |
| Prefixes | Linux: `Prefix/`, `prefixes/<game>/`, or wherever you point them |
| Shared saves | `Saves/` (Linux: symlinked profile; Windows: `Saves/<Game>/` mirrors) |
| Save backups | `backups/saves/<timestamp>/` |
| Preferences | Linux `~/.config/milso-launcher/settings.json`, Windows `%APPDATA%\milso-launcher` |
| Playtime, sessions, favourites | Linux `~/.local/share/milso-launcher/state.db`, Windows `%LOCALAPPDATA%\milso-launcher` |
| Game logs | Linux `~/.local/share/milso-launcher/logs/` |
