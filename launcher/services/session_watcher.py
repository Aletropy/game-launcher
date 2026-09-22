"""Wait for one game to exit, then leave its playtime as a sidecar.

Runs detached from the launcher (``start_new_session=True``), so quitting
the app — or closing the window to the tray and then quitting — never cuts
a session short. The main app imports the sidecar on its next start; if the
app is still alive it records the session itself and the watcher exits
without writing anything.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from launcher.data.paths import Paths

_POLL_SECONDS = 5.0


def _paths_for(data_dir: str) -> Paths:
    # Only the per-user data dir matters here; base is unused.
    return Paths(base=Path(data_dir), config=Path(data_dir), data=Path(data_dir))

def spawn_watcher(
    paths: Paths, game_name: str, started_iso: str, pid: object
) -> int | None:
    """Launch the watcher detached. Returns its pid, or None if skipped."""
    if not isinstance(pid, int) or pid <= 0 or not game_name or not started_iso:
        return None
    try:
        data_dir = str(paths.data)
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "launcher.services.session_watcher",
                "--data",
                data_dir,
                "--game",
                game_name,
                "--started",
                started_iso,
                "--pid",
                str(pid),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        return proc.pid
    except (OSError, ValueError):
        return None


def watch(data_dir: str, game_name: str, started_iso: str, pid: int) -> int:
    """Block until the game exits, then write the sidecar. Returns 0."""
    from launcher.services import sessions as _sessions
    from launcher.services.process import MIN_SESSION_SECONDS

    paths = _paths_for(data_dir)
    try:
        started = datetime.fromisoformat(started_iso)
    except ValueError:
        return 0
    while True:
        time.sleep(_POLL_SECONDS)
        active = _sessions.load_active(paths)
        entry = active.get(game_name)
        if entry is None or entry.get("started_iso") != started_iso:
            # The app recorded (or dropped) this launch itself.
            return 0
        if _sessions.pid_alive(pid):
            continue
        seconds = int((datetime.now() - started).total_seconds())
        if seconds >= MIN_SESSION_SECONDS:
            _sessions.write_pending(paths, game_name, started, seconds)
        _sessions.remove_active(paths, game_name, started_iso)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one finished game session.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--started", required=True)
    parser.add_argument("--pid", required=True, type=int)
    args = parser.parse_args(argv)
    return watch(args.data, args.game, args.started, args.pid)


if __name__ == "__main__":
    sys.exit(main())
