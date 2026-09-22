"""Tell a crash from a quit.

Exit codes alone lie: Proton returns nonzero for clean exits of some
games, and zero after swallowing a Wine fault. The assessment combines
the exit code, how long the game ran, and known error lines from the
log tail, and always explains itself in one sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CrashAssessment:
    """What a finished session looks like."""

    crashed: bool
    summary: str = ""
    hint: str = ""


#: (pattern, summary, hint) checked against the log tail, first match wins.
_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"steam flatpak is not running", re.IGNORECASE),
        "Steam is not running",
        "Start the Steam Flatpak first, then play again.",
    ),
    (
        re.compile(r"could not load kernel32\.dll", re.IGNORECASE),
        "System Wine touched a Proton prefix",
        "Only run winecfg and winetricks from the launcher, never system wine.",
    ),
    (
        re.compile(r"config not found", re.IGNORECASE),
        "The game's configuration is missing",
        "Re-add the game or restore its .conf file.",
    ),
    (
        re.compile(r"failed to create prefix|failed to create directory", re.IGNORECASE),
        "The prefix could not be created",
        "Check the prefix path is writable and visible to the Steam Flatpak.",
    ),
    (
        re.compile(r"err:.*module .* not found|failed to load .*\.(dll|so)", re.IGNORECASE),
        "A game library failed to load",
        "Verify the game files, then check the log for the missing file.",
    ),
    (
        re.compile(r"out of memory|bad alloc|dxgi_error_device_removed", re.IGNORECASE),
        "The game ran out of memory or lost the GPU",
        "Close other apps, lower the game's graphics settings, update GPU drivers.",
    ),
    (
        re.compile(r"wine: .*exception|unhandled exception|stack overflow", re.IGNORECASE),
        "The game crashed inside Wine",
        "Try a different Proton build in Edit → Compatibility.",
    ),
)


def assess(log_tail: str, exit_code: int, seconds: int) -> CrashAssessment:
    """Judge one finished session.

    A clean exit (code 0, or a long session) is never a crash. A nonzero
    code on a short session is, with the log deciding the explanation.
    """
    tail = log_tail[-8000:]
    for pattern, summary, hint in _PATTERNS:
        if pattern.search(tail):
            crashed = exit_code != 0 or seconds < 300
            return CrashAssessment(crashed=crashed, summary=summary, hint=hint)
    if exit_code == 0:
        return CrashAssessment(crashed=False)
    if seconds >= 300:
        return CrashAssessment(
            crashed=False,
            summary=f"Exited with code {exit_code} after a full session",
            hint="Playtime was recorded normally.",
        )
    return CrashAssessment(
        crashed=True,
        summary=f"Exited quickly with code {exit_code}",
        hint="Check the log tail for the failing line.",
    )
