"""Dev/prod entry point. ./run.sh runs sandboxed; the installed command does not."""

from __future__ import annotations

import os
import sys

#: Flags handled here and stripped before QApplication sees argv.
_SANDBOX_ON = {"--sandbox"}
_SANDBOX_OFF = {"--no-sandbox", "--prod"}
_SEED = {"--seed"}


def apply_sandbox_argv(argv: list[str]) -> bool:
    """Apply --sandbox/--no-sandbox/--seed from argv.

    Sets MILSO_SANDBOX accordingly, strips those flags in place, and
    returns whether --seed was requested.
    """
    seed = any(arg in _SEED for arg in argv)
    for arg in argv:
        if arg in _SANDBOX_ON:
            os.environ["MILSO_SANDBOX"] = "1"
        elif arg in _SANDBOX_OFF:
            os.environ["MILSO_SANDBOX"] = "0"
    argv[:] = [arg for arg in argv if arg not in _SANDBOX_ON | _SANDBOX_OFF | _SEED]
    return seed


def maybe_seed_sandbox() -> None:
    """One-time copy of prod settings/state into the sandbox, with a report."""
    from launcher.data.paths import seed_sandbox_from_production

    copied = seed_sandbox_from_production()
    if copied:
        print("Seeded sandbox from the installed data:")
        for rel in copied:
            print(f"  {rel}")
    else:
        print("Sandbox already seeded (or nothing to copy).")


if __name__ == "__main__":
    _seed_requested = apply_sandbox_argv(sys.argv)
    if _seed_requested:
        maybe_seed_sandbox()
    from launcher.app.main import main

    main()
