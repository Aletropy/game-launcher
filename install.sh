#!/usr/bin/env bash
#
# Install (or remove) the game launcher for the current user.
#
#   ./install.sh              install
#   ./install.sh --uninstall  remove the desktop entry and command
#   ./install.sh --check      report dependencies and exit
#
# Nothing is installed system-wide and nothing needs root.

set -uo pipefail

LAUNCHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="game-launcher"
APP_NAME="Game Launcher"

BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

VENV="$LAUNCHER_DIR/.venv"
PYTHON_MIN_MINOR=11

# ----------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'
    C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi

ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$1"; }
err()  { printf '  %s✗%s %s\n' "$C_ERR" "$C_OFF" "$1" >&2; }
note() { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }
head_() { printf '\n%s\n' "$1"; }

FAILED=0

# ----------------------------------------------------------------------
# Dependency checks
# ----------------------------------------------------------------------
find_python() {
    # Newest suitable interpreter, so a system with several works.
    local candidate
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $PYTHON_MIN_MINOR) else 1)" 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

check_dependencies() {
    head_ "Checking dependencies"

    if PYTHON="$(find_python)"; then
        ok "python $("$PYTHON" -c 'import platform; print(platform.python_version())') ($PYTHON)"
    else
        err "python 3.$PYTHON_MIN_MINOR or newer not found"
        note "Install python3 from your distribution's package manager."
        FAILED=1
    fi

    if "$PYTHON" -c "import venv" 2>/dev/null; then
        ok "python venv module"
    else
        err "the python venv module is missing"
        note "On Debian/Ubuntu: sudo apt install python3-venv"
        FAILED=1
    fi

    if command -v bash >/dev/null 2>&1; then
        ok "bash ${BASH_VERSION%%(*}"
    else
        err "bash not found"
        FAILED=1
    fi

    # The launcher runs games inside the Steam Flatpak container.
    if command -v flatpak >/dev/null 2>&1; then
        if flatpak info com.valvesoftware.Steam >/dev/null 2>&1; then
            ok "Steam Flatpak installed"
            if flatpak ps 2>/dev/null | grep -qi steam; then
                ok "Steam is running"
            else
                warn "Steam is not running"
                note "Start Steam before launching a game, or the launcher"
                note "cannot enter its container."
            fi
        else
            warn "Steam Flatpak not installed"
            note "flatpak install flathub com.valvesoftware.Steam"
        fi
    else
        warn "flatpak not found — games cannot be launched without it"
        note "The launcher runs games inside the Steam Flatpak container."
    fi

    # Optional extras.
    if command -v gamescope >/dev/null 2>&1; then
        ok "gamescope (optional)"
    else
        warn "gamescope not found (optional)"
        note "Needed only for the per-game Gamescope settings."
    fi

    if command -v winetricks >/dev/null 2>&1; then
        ok "winetricks (optional)"
    elif [ -f "$LAUNCHER_DIR/winetricks" ]; then
        ok "winetricks (bundled copy)"
    else
        warn "winetricks not found (optional)"
        note "Needed only for the prefix tools menu."
    fi
}

# ----------------------------------------------------------------------
# Install steps
# ----------------------------------------------------------------------
setup_venv() {
    head_ "Setting up the Python environment"

    if [ -d "$VENV" ] && [ -x "$VENV/bin/python" ]; then
        ok "virtualenv already exists"
    elif "$PYTHON" -m venv "$VENV"; then
        ok "virtualenv created at .venv"
    else
        err "could not create the virtualenv"
        return 1
    fi

    if "$VENV/bin/python" -m pip install --quiet --upgrade pip 2>/dev/null; then
        ok "pip up to date"
    else
        warn "could not upgrade pip; continuing"
    fi

    printf '  … installing PySide6 (this can take a minute)\n'
    if "$VENV/bin/python" -m pip install --quiet -r "$LAUNCHER_DIR/requirements.txt"; then
        ok "dependencies installed"
    else
        err "could not install dependencies"
        return 1
    fi

    if "$VENV/bin/python" -c "import PySide6" 2>/dev/null; then
        ok "PySide6 imports"
    else
        err "PySide6 did not import after installation"
        return 1
    fi
}

install_launcher_command() {
    head_ "Installing the command"

    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/$APP_ID" <<EOF
#!/usr/bin/env bash
# Generated by $LAUNCHER_DIR/install.sh
exec "$VENV/bin/python" "$LAUNCHER_DIR/run.py" "\$@"
EOF
    chmod +x "$BIN_DIR/$APP_ID"
    ok "command installed: $BIN_DIR/$APP_ID"

    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            warn "$BIN_DIR is not on your PATH"
            note "Add this to your shell profile:"
            note "  export PATH=\"\$PATH:$BIN_DIR\""
            ;;
    esac
}

install_desktop_entry() {
    head_ "Installing the desktop entry"

    mkdir -p "$DESKTOP_DIR"
    local icon="$APP_ID"
    if [ -f "$LAUNCHER_DIR/icon.png" ]; then
        mkdir -p "$ICON_DIR"
        if cp "$LAUNCHER_DIR/icon.png" "$ICON_DIR/$APP_ID.png"; then
            ok "icon installed"
        else
            warn "could not install the icon; using the launcher's own file"
            icon="$LAUNCHER_DIR/icon.png"
        fi
    else
        icon="applications-games"
        warn "icon.png not found; using a generic icon"
    fi

    cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
GenericName=Game Launcher
Comment=Run Windows games through Proton
Exec=$BIN_DIR/$APP_ID
Icon=$icon
Terminal=false
Categories=Game;
Keywords=games;wine;proton;steam;
StartupNotify=true
StartupWMClass=$APP_ID
EOF
    ok "desktop entry: $DESKTOP_DIR/$APP_ID.desktop"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null && ok "desktop database updated"
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -qtf "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" \
            2>/dev/null && ok "icon cache updated"
    fi
}

verify_install() {
    head_ "Verifying"

    if QT_QPA_PLATFORM=offscreen "$VENV/bin/python" - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, ".")
from launcher.app.context import AppContext  # noqa: F401
from launcher.app.main import build_window   # noqa: F401
PY
    then
        ok "the launcher imports cleanly"
    else
        err "the launcher failed to import"
        note "Run '$VENV/bin/python run.py' to see the error."
        return 1
    fi

    chmod +x "$LAUNCHER_DIR/game-launcher.sh" 2>/dev/null
    if bash -n "$LAUNCHER_DIR/game-launcher.sh" 2>/dev/null; then
        ok "game-launcher.sh is valid"
    else
        err "game-launcher.sh has a syntax error"
        return 1
    fi
}

# ----------------------------------------------------------------------
# Uninstall
# ----------------------------------------------------------------------
uninstall() {
    head_ "Removing $APP_NAME"

    local removed=0
    for target in \
        "$BIN_DIR/$APP_ID" \
        "$DESKTOP_DIR/$APP_ID.desktop" \
        "$ICON_DIR/$APP_ID.png"
    do
        if [ -e "$target" ]; then
            rm -f "$target" && ok "removed $target" && removed=1
        fi
    done
    [ "$removed" -eq 0 ] && warn "nothing was installed"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null
    fi

    printf '\nYour games, prefixes, artwork and settings were left alone:\n'
    note "games      $LAUNCHER_DIR/games"
    note "prefixes   $LAUNCHER_DIR/Prefix (and any per-game prefixes)"
    note "settings   ${XDG_CONFIG_HOME:-$HOME/.config}/launcher"
    note "state      ${XDG_DATA_HOME:-$HOME/.local/share}/launcher"
    printf '\nTo remove those too, delete the directories above and this folder.\n'
}

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
case "${1:-}" in
    --uninstall|-u)
        uninstall
        exit 0
        ;;
    --check|-c)
        check_dependencies
        exit "$FAILED"
        ;;
    --help|-h)
        sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    "")
        ;;
    *)
        err "unknown option: $1"
        printf 'Try --help.\n'
        exit 2
        ;;
esac

printf '%s\n' "Installing $APP_NAME"
printf '%s\n' "from $LAUNCHER_DIR"

check_dependencies
if [ "$FAILED" -ne 0 ]; then
    printf '\n%sInstallation cannot continue until the errors above are fixed.%s\n' \
        "$C_ERR" "$C_OFF"
    exit 1
fi

setup_venv || exit 1
install_launcher_command
install_desktop_entry
verify_install || exit 1

cat <<EOF

${C_OK}Done.${C_OFF}

  Launch from your application menu, or run:
      $APP_ID

  If the command is not found, restart your shell or add
  $BIN_DIR to your PATH.

  To remove: ./install.sh --uninstall
EOF
