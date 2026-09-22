"""Whether closing the window hides it or quits the app.

A pure decision, kept out of the window so it can be unit-tested without
Qt: given the confirmed-quit flag, whether the tray is live, and the
running games, there are only three answers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CloseDecision:
    """What ``closeEvent`` should do."""

    #: "accept" quits, "hide" minimizes to the tray, "confirm" asks first.
    action: str


def decide(quitting: bool, tray_active: bool, running: list[str]) -> CloseDecision:
    """Decide the close behaviour. Pure: no Qt, no settings."""
    if quitting:
        return CloseDecision("accept")
    if tray_active:
        return CloseDecision("hide")
    if running:
        return CloseDecision("confirm")
    return CloseDecision("accept")
