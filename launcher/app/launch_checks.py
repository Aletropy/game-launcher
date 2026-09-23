"""Pre-launch checks with one consolidated answer.

Launching used to fail in exactly one place (missing executable) and
everywhere else with a Proton dump. Checks return blocks (cannot start)
and warnings (starts anyway, but likely fails); the controller shows all
of them at once instead of one dialog per problem.
"""

from __future__ import annotations

import os
import shutil

from launcher.data.paths import Paths
from launcher.domain.models import Game
from launcher.domain.outcome import Block
from launcher.domain.prefixes import PrefixState, inspect
from launcher.services.prefix_tools import steam_flatpak_running

#: Refuse to launch when less than this is free where saves land.
MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024


def check_launch(
    game: Game,
    paths: Paths,
    *,
    steam_running: bool | None = None,
    free_bytes: int | None = None,
) -> tuple[list[Block], list[Block]]:
    """Check whether a game can start. Returns (blocks, warnings).

    ``steam_running`` and ``free_bytes`` are injectable so tests never
    shell out to flatpak or read real disks.
    """
    blocks: list[Block] = []
    warnings: list[Block] = []

    from launcher import platform as _platform

    windows = _platform.is_windows()

    if not game.executable:
        blocks.append(
            Block(
                title="No executable set",
                detail=f"'{game.name}' has no executable configured.",
                hint="Open Edit and pick the game's .exe file.",
                kind="missing-executable",
            )
        )
    elif not os.path.isfile(game.executable):
        blocks.append(
            Block(
                title="Executable not found",
                detail=f"The executable for '{game.name}' was not found:\n{game.executable}",
                hint="Remount the drive, or open Edit and pick the new location.",
                kind="missing-executable",
            )
        )

    info = inspect(game.prefix, paths)
    if not windows and info.state is PrefixState.NOT_A_DIRECTORY:
        blocks.append(
            Block(
                title="Prefix path is a file",
                detail=f"A file already exists at the prefix path:\n{info.path}",
                hint="Choose a different folder in Edit → Compatibility.",
                kind="bad-prefix",
            )
        )
    elif not windows and info.state is PrefixState.OUTSIDE_SANDBOX:
        warnings.append(
            Block(
                title="Prefix may be invisible to the game",
                detail=info.message,
                hint="Move the prefix under the launcher or home folder, "
                "or grant access with flatpak override.",
                kind="prefix-visibility",
            )
        )

    if not windows:
        if steam_running is None:
            steam_running = steam_flatpak_running()
        if not steam_running:
            warnings.append(
                Block(
                    title="Steam does not look running",
                    detail="The Steam Flatpak was not detected.",
                    hint="Start Steam first; the launcher enters its container to play.",
                    kind="steam-not-running",
                )
            )

        custom_proton = (game.config.custom_proton_path or "").strip()
        if custom_proton and not os.path.isdir(custom_proton):
            warnings.append(
                Block(
                    title="Custom Proton not found",
                    detail=f"The configured Proton path does not exist:\n{custom_proton}",
                    hint="Fix it in Edit → Compatibility, or clear it to use the default.",
                    kind="proton-not-found",
                )
            )

    if free_bytes is None:
        try:
            free_bytes = shutil.disk_usage(paths.saves_dir).free
        except OSError:
            free_bytes = MIN_FREE_BYTES
    if free_bytes < MIN_FREE_BYTES:
        blocks.append(
            Block(
                title="Disk almost full",
                detail="Less than 1 GB is free where saves and prefixes live.",
                hint="Free some disk space before playing.",
                kind="no-space",
            )
        )

    return blocks, warnings
