#!/usr/bin/env bash
# Dev entry: runs this checkout inside the project sandbox (.sandbox/),
# so settings/playtime/cache never touch ~/.config/milso-launcher or
# ~/.local/share/milso-launcher. Games, Saves/ and prefixes are already
# project-local and shared. The installed `milso-launcher` command runs
# without the sandbox.
#
#   ./run.sh              # sandboxed dev run
#   ./run.sh --seed       # one-time copy of prod settings + playtime
#   MILSO_SANDBOX=0 ./run.sh   # dev code, real user data
: "${MILSO_SANDBOX:=1}"
export MILSO_SANDBOX
cd "$(dirname "$0")"
source .venv/bin/activate
python run.py "$@" &
