#!/usr/bin/env bash
#
# Game Launcher @@VERSION@@ — self-extracting installer.
#
#   ./game-launcher-@@VERSION@@.run                 install or upgrade
#   ./game-launcher-@@VERSION@@.run --target DIR    install into DIR
#   ./game-launcher-@@VERSION@@.run --yes           no questions
#   ./game-launcher-@@VERSION@@.run --check         check dependencies only
#   ./game-launcher-@@VERSION@@.run --extract DIR   unpack without installing
#
# Run it once. It unpacks itself, upgrades an existing installation in
# place if it finds one, and sets up the venv, command and desktop entry.
#
# Upgrading never touches your games, Wine prefixes, artwork, save
# backups or settings.

set -uo pipefail

VERSION="@@VERSION@@"
PAYLOAD_SHA256="@@PAYLOAD_SHA256@@"
PACKAGE_NAME="game-launcher-@@VERSION@@"
APP_ID="game-launcher"

DEFAULT_TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
BIN_SHIM="${XDG_BIN_HOME:-$HOME/.local/bin}/$APP_ID"

# Directories that belong to the user and are never replaced.
PRESERVE=(
    games
    Prefix
    prefixes
    backups
    launcher/artwork
    launcher/heroes
    .venv
    .prefix-name
    dist
)

# Paths from older versions that no longer exist and must not linger.
OBSOLETE=(
    launcher/core
    launcher/app.py
    launcher/main.py
    launcher/config_parser.py
    launcher/game_manager.py
    launcher/process_manager.py
    launcher/settings.py
    launcher/steamgriddb.py
    launcher/services/artwork.py
    launcher/ui/styles.py
    launcher/ui/debug_tab.py
    launcher/ui/game_card.py
    launcher/ui/game_grid.py
    launcher/ui/add_game_dialog.py
    launcher/ui/sgdb_dialog.py
)

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'
    C_B=$'\033[1m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_WARN=""; C_ERR=""; C_B=""; C_DIM=""; C_OFF=""
fi
ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$1"; }
err()  { printf '  %s✗%s %s\n' "$C_ERR" "$C_OFF" "$1" >&2; }
note() { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }
head_() { printf '\n%s%s%s\n' "$C_B" "$1" "$C_OFF"; }

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//; s/@@VERSION@@/'"$VERSION"'/g'
}

# ----------------------------------------------------------------------
# Payload
# ----------------------------------------------------------------------
payload_line() {
    awk '/^__PAYLOAD_BELOW__$/ { print NR + 1; exit 0 }' "$0"
}

extract_payload() {
    local dest="$1" line
    line="$(payload_line)"
    if [ -z "$line" ]; then
        err "this installer has no payload (was it edited or truncated?)"
        return 1
    fi

    if command -v sha256sum >/dev/null 2>&1; then
        local actual
        actual="$(tail -n "+$line" "$0" | sha256sum | cut -d' ' -f1)"
        if [ "$actual" != "$PAYLOAD_SHA256" ]; then
            err "the payload is corrupt"
            note "expected $PAYLOAD_SHA256"
            note "got      $actual"
            return 1
        fi
        ok "payload verified"
    else
        warn "sha256sum not found; skipping the integrity check"
    fi

    mkdir -p "$dest"
    if tail -n "+$line" "$0" | tar xz -C "$dest"; then
        ok "unpacked $VERSION"
    else
        err "could not unpack the payload"
        return 1
    fi
}

# ----------------------------------------------------------------------
# Working out where to install
# ----------------------------------------------------------------------
looks_like_install() {
    local dir="$1"
    [ -n "$dir" ] && [ -d "$dir" ] || return 1
    [ -f "$dir/game-launcher.sh" ] || return 1
    [ -d "$dir/launcher" ] || [ -d "$dir/games" ]
}

installed_location() {
    # The command shim records the directory it was generated for.
    [ -f "$BIN_SHIM" ] || return 1
    local path
    path="$(sed -n 's|.*"\(/.*\)/run\.py".*|\1|p' "$BIN_SHIM" | head -n1)"
    [ -n "$path" ] && looks_like_install "$path" && printf '%s\n' "$path"
}

choose_target() {
    if [ -n "${TARGET:-}" ]; then
        printf '%s\n' "$TARGET"
        return 0
    fi
    # An install in the current directory wins: running the installer
    # from inside a project is the obvious way to upgrade it.
    if looks_like_install "$PWD"; then
        printf '%s\n' "$PWD"
        return 0
    fi
    local recorded
    if recorded="$(installed_location)"; then
        printf '%s\n' "$recorded"
        return 0
    fi
    printf '%s\n' "$DEFAULT_TARGET"
}

confirm() {
    local prompt="$1"
    [ "${ASSUME_YES:-0}" -eq 1 ] && return 0
    if [ ! -t 0 ]; then
        # Piped from curl with no terminal: refuse rather than guess.
        err "$prompt"
        note "No terminal to ask on. Re-run with --yes to accept."
        return 1
    fi
    local reply
    read -r -p "  $prompt [Y/n] " reply
    case "${reply:-y}" in
        [Yy]*|"") return 0 ;;
        *) return 1 ;;
    esac
}

# ----------------------------------------------------------------------
# Installing
# ----------------------------------------------------------------------
describe_plan() {
    local target="$1" upgrading="$2"

    head_ "Plan"
    if [ "$upgrading" -eq 1 ]; then
        printf '  Upgrade the installation in %s\n' "$target"
        local current="unknown"
        if [ -f "$target/pyproject.toml" ]; then
            current="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' \
                "$target/pyproject.toml" | head -n1)"
            [ -n "$current" ] || current="unknown"
        fi
        printf '  %s → %s\n\n' "$current" "$VERSION"
        printf '  Replaced: the application source and the helper scripts\n'
        printf '  Kept:     '
        local kept=() item
        for item in "${PRESERVE[@]}"; do
            [ -e "$target/$item" ] && kept+=("$item")
        done
        if [ "${#kept[@]}" -eq 0 ]; then
            printf 'nothing found to keep\n'
        else
            printf '%s\n' "${kept[0]}"
            local i
            for ((i = 1; i < ${#kept[@]}; i++)); do
                printf '            %s\n' "${kept[$i]}"
            done
        fi
    else
        printf '  Fresh installation into %s\n' "$target"
    fi
}

back_up_existing() {
    local target="$1"
    local stamp archive
    stamp="$(date +%Y-%m-%d_%H%M%S)"
    archive="$target/.upgrade-backup-$stamp.tar.gz"

    # Only the application files are archived; user data is untouched by
    # the upgrade, so backing it up would just waste space.
    local items=() item
    for item in launcher tests *.sh run.py requirements.txt pyproject.toml README.md; do
        [ -e "$target/$item" ] && items+=("$item")
    done
    [ "${#items[@]}" -gt 0 ] || return 0

    if tar czf "$archive" -C "$target" \
        --exclude='launcher/artwork' --exclude='launcher/heroes' \
        --exclude='__pycache__' "${items[@]}" 2>/dev/null
    then
        ok "previous version saved to $(basename "$archive")"
    else
        warn "could not back up the previous version; continuing"
        rm -f "$archive"
    fi
}

sync_tree() {
    local source="$1" target="$2"
    head_ "Installing files"

    mkdir -p "$target" || return 1

    # The launcher package is replaced wholesale so modules deleted
    # upstream cannot linger and shadow the new layout. The user's
    # artwork lives inside it, so it is moved aside and put back.
    local stash=""
    if [ -d "$target/launcher" ]; then
        stash="$(mktemp -d)" || return 1
        local kept item
        for kept in artwork heroes; do
            if [ -d "$target/launcher/$kept" ]; then
                mv "$target/launcher/$kept" "$stash/$kept"
            fi
        done
        rm -rf "$target/launcher"
    fi

    cp -r "$source/launcher" "$target/" || return 1
    if [ -n "$stash" ]; then
        local kept
        for kept in artwork heroes; do
            [ -d "$stash/$kept" ] && mv "$stash/$kept" "$target/launcher/$kept"
        done
        rm -rf "$stash"
    fi
    ok "application source"

    local item
    for item in tests game-launcher.sh install.sh repair-prefix.sh \
                migrate-from-flatpak-prefix.sh migrate-saves.sh \
                steam_flatpak_saves.sh steam_native_saves.sh \
                run.py run.sh requirements.txt pyproject.toml README.md icon.png
    do
        [ -e "$source/$item" ] || continue
        rm -rf "$target/$item"
        cp -r "$source/$item" "$target/" || return 1
    done
    ok "scripts, tests and documentation"

    # A fresh install needs a games directory; an existing one keeps its own.
    mkdir -p "$target/games"

    local removed=0
    for item in "${OBSOLETE[@]}"; do
        if [ -e "$target/$item" ]; then
            rm -rf "$target/$item"
            removed=$((removed + 1))
        fi
    done
    [ "$removed" -gt 0 ] && ok "removed $removed file(s) from older versions"

    find "$target" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null

    local script
    for script in game-launcher.sh install.sh repair-prefix.sh \
                  migrate-from-flatpak-prefix.sh migrate-saves.sh \
                  steam_flatpak_saves.sh steam_native_saves.sh run.sh
    do
        [ -f "$target/$script" ] && chmod +x "$target/$script"
    done
    ok "scripts are executable"
}

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
TARGET=""
ASSUME_YES=0
MODE="install"
EXTRACT_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --target|-t)
            TARGET="${2:-}"
            [ -n "$TARGET" ] || { err "--target needs a directory"; exit 2; }
            shift 2
            ;;
        --target=*) TARGET="${1#*=}"; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --check|-c) MODE="check"; shift ;;
        --extract|-x)
            MODE="extract"
            EXTRACT_DIR="${2:-}"
            [ -n "$EXTRACT_DIR" ] || { err "--extract needs a directory"; exit 2; }
            shift 2
            ;;
        --version|-V) printf '%s\n' "$VERSION"; exit 0 ;;
        --help|-h) usage; exit 0 ;;
        *) err "unknown option: $1"; printf 'Try --help.\n'; exit 2 ;;
    esac
done

printf '%sGame Launcher %s%s\n' "$C_B" "$VERSION" "$C_OFF"

WORKDIR="$(mktemp -d)" || exit 1
trap 'rm -rf "$WORKDIR"' EXIT

head_ "Unpacking"
extract_payload "$WORKDIR" || exit 1
SOURCE="$WORKDIR/$PACKAGE_NAME"
if [ ! -d "$SOURCE" ]; then
    err "the payload does not contain $PACKAGE_NAME"
    exit 1
fi

case "$MODE" in
    extract)
        mkdir -p "$EXTRACT_DIR" || exit 1
        cp -r "$SOURCE/." "$EXTRACT_DIR/" || exit 1
        ok "extracted to $EXTRACT_DIR"
        exit 0
        ;;
    check)
        exec bash "$SOURCE/install.sh" --check
        ;;
esac

TARGET="$(choose_target)"
case "$TARGET" in
    /*) ;;
    *) TARGET="$(cd "$(dirname "$TARGET")" 2>/dev/null && pwd)/$(basename "$TARGET")" ;;
esac

UPGRADING=0
looks_like_install "$TARGET" && UPGRADING=1

describe_plan "$TARGET" "$UPGRADING"

printf '\n'
if [ "$UPGRADING" -eq 1 ]; then
    confirm "Upgrade in place?" || { printf 'Cancelled.\n'; exit 1; }
    head_ "Backing up"
    back_up_existing "$TARGET"
else
    confirm "Install here?" || { printf 'Cancelled.\n'; exit 1; }
fi

sync_tree "$SOURCE" "$TARGET" || { err "installation failed"; exit 1; }

head_ "Running the setup"
if bash "$TARGET/install.sh"; then
    :
else
    err "setup failed"
    note "The files are in $TARGET; run ./install.sh there to retry."
    exit 1
fi

if [ "$UPGRADING" -eq 1 ]; then
    printf '\n%sUpgraded to %s.%s  Your games and settings were kept.\n' \
        "$C_OK" "$VERSION" "$C_OFF"
else
    printf '\n%sInstalled %s into %s.%s\n' "$C_OK" "$VERSION" "$TARGET" "$C_OFF"
fi

exit 0

__PAYLOAD_BELOW__
