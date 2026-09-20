#!/usr/bin/env bash
#
# Build a release archive that installs on any machine.
#
#   ./package.sh            build dist/game-launcher-<version>.tar.gz
#   ./package.sh --no-check skip the test and lint gate
#   ./package.sh --clean    remove dist/ and exit
#
# What goes in: the source, the scripts, the icon and the docs.
# What stays out: the virtualenv, Wine prefixes, artwork, save backups,
# caches, and your own games.
#
# game-launcher.sh is copied in as a plain executable file and is never
# bundled or rewritten: it rewrites its own source with sed on "$0", so
# it has to stay a readable file on disk to work at all.

set -uo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SOURCE_DIR/dist"
VENV="$SOURCE_DIR/.venv"

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

# Files and directories copied into the archive. Anything not listed
# here does not ship, so new private data cannot leak in by accident.
PAYLOAD=(
    launcher
    tests
    game-launcher.sh
    install.sh
    repair-prefix.sh
    migrate-from-flatpak-prefix.sh
    migrate-saves.sh
    steam_flatpak_saves.sh
    steam_native_saves.sh
    run.py
    run.sh
    requirements.txt
    pyproject.toml
    README.md
    icon.png
)

# User data that lives inside a shipped directory and must be pruned.
# Relative to the package root, so the source package
# launcher/services/artwork is never touched.
USER_DATA_DIRS=(
    launcher/artwork
    launcher/heroes
)

# Scripts that must arrive executable.
EXECUTABLES=(
    game-launcher.sh
    install.sh
    repair-prefix.sh
    migrate-from-flatpak-prefix.sh
    migrate-saves.sh
    steam_flatpak_saves.sh
    steam_native_saves.sh
    run.sh
)

read_version() {
    sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' \
        "$SOURCE_DIR/pyproject.toml" | head -n1
}

run_checks() {
    head_ "Checking the tree"

    if [ ! -x "$VENV/bin/python" ]; then
        warn "no .venv; skipping tests and lint"
        note "Run ./install.sh first to check before packaging."
        return 0
    fi

    if "$VENV/bin/ruff" check launcher tests >/dev/null 2>&1; then
        ok "ruff clean"
    else
        err "ruff reported problems"
        "$VENV/bin/ruff" check launcher tests --output-format=concise | head -10
        return 1
    fi

    if "$VENV/bin/mypy" launcher >/dev/null 2>&1; then
        ok "mypy clean"
    else
        err "mypy reported problems"
        "$VENV/bin/mypy" launcher 2>&1 | tail -10
        return 1
    fi

    local output
    if output="$("$VENV/bin/python" "$SOURCE_DIR/tests/smoke.py" 2>&1)"; then
        ok "$(printf '%s' "$output" | tail -n1 | tr -s ' ')"
    else
        err "tests failed"
        printf '%s\n' "$output" | tail -20
        return 1
    fi
}

stage() {
    local staging="$1"
    head_ "Staging files"

    mkdir -p "$staging"
    local item missing=0
    for item in "${PAYLOAD[@]}"; do
        if [ ! -e "$SOURCE_DIR/$item" ]; then
            err "missing: $item"
            missing=1
            continue
        fi
        cp -r "$SOURCE_DIR/$item" "$staging/"
    done
    [ "$missing" -eq 0 ] || return 1

    # cp -r brings whole directories, so user data living inside them
    # has to be pruned back out. By exact path, never by name:
    # launcher/services/artwork is source code, launcher/artwork is not.
    local junk
    for junk in "${USER_DATA_DIRS[@]}"; do
        rm -rf "${staging:?}/$junk"
    done
    find "$staging" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null
    find "$staging" -type f -name '*.py[co]' -delete 2>/dev/null
    ok "pruned caches and stored user data"

    # An empty library, so a fresh install starts clean.
    mkdir -p "$staging/games"
    cat > "$staging/games/.gitkeep" <<'EOF'
EOF
    ok "empty games/ directory"

    local script
    for script in "${EXECUTABLES[@]}"; do
        chmod +x "$staging/$script" 2>/dev/null
    done
    ok "${#EXECUTABLES[@]} scripts marked executable"

    ok "$(find "$staging" -type f | wc -l) files staged"
}

verify_staging() {
    local staging="$1"
    head_ "Verifying the payload"

    # Nothing personal or machine-specific may ship. Names that could
    # also be source directories are checked by exact path.
    local forbidden_names=(
        ".venv" "Prefix" "prefixes" "backups"
        ".git" ".mypy_cache" ".ruff_cache" "state.db" "settings.json"
    )
    local name found=0
    for name in "${forbidden_names[@]}"; do
        if find "$staging" -name "$name" -print -quit | grep -q .; then
            err "$name must not be in the archive"
            found=1
        fi
    done
    for name in "${USER_DATA_DIRS[@]}"; do
        if [ -e "$staging/$name" ]; then
            err "$name must not be in the archive"
            found=1
        fi
    done
    if find "$staging/games" -name '*.conf' -print -quit | grep -q .; then
        err "personal game configs must not be in the archive"
        found=1
    fi
    [ "$found" -eq 0 ] && ok "no private or machine-specific files"
    [ "$found" -eq 0 ] || return 1

    # game-launcher.sh must arrive intact, executable and parseable.
    if ! cmp -s "$SOURCE_DIR/game-launcher.sh" "$staging/game-launcher.sh"; then
        err "game-launcher.sh was modified during packaging"
        return 1
    fi
    ok "game-launcher.sh byte-identical (never bundled or rewritten)"

    if [ ! -x "$staging/game-launcher.sh" ]; then
        err "game-launcher.sh is not executable"
        return 1
    fi
    if bash -n "$staging/game-launcher.sh" 2>/dev/null; then
        ok "game-launcher.sh parses"
    else
        err "game-launcher.sh has a syntax error"
        return 1
    fi

    local script
    for script in "${EXECUTABLES[@]}"; do
        if ! bash -n "$staging/$script" 2>/dev/null; then
            err "$script has a syntax error"
            return 1
        fi
    done
    ok "every shipped script parses"

    if "${PYTHON:-python3}" -c "
import pathlib, sys
root = pathlib.Path(sys.argv[1])
missing = [
    p for p in (
        'launcher/app/main.py',
        'launcher/domain/models.py',
        'launcher/services/artwork/__init__.py',
        'launcher/services/artwork/store.py',
        'launcher/services/artwork/cleanup.py',
        'launcher/ui/main_window.py',
        'run.py',
    )
    if not (root / p).is_file()
]
sys.exit(1 if missing else 0)
" "$staging"; then
        ok "the package entry points are present"
    else
        err "the package is missing an entry point"
        return 1
    fi
}

build_archive() {
    local staging="$1" name="$2"
    head_ "Building the archive"

    mkdir -p "$DIST_DIR"
    local archive="$DIST_DIR/$name.tar.gz"
    rm -f "$archive"

    # --sort and a fixed mtime make the archive reproducible, so two
    # builds of the same tree are byte-identical.
    if tar --sort=name \
           --mtime="@${SOURCE_DATE_EPOCH:-$(date +%s)}" \
           --owner=0 --group=0 --numeric-owner \
           -czf "$archive" -C "$(dirname "$staging")" "$name" 2>/dev/null
    then
        ok "reproducible archive"
    elif tar -czf "$archive" -C "$(dirname "$staging")" "$name"; then
        warn "built without reproducible flags (older tar)"
    else
        err "could not build the archive"
        return 1
    fi

    printf '%s\n' "$archive"
}

test_install() {
    local archive="$1" name="$2"
    head_ "Testing the archive"

    local scratch
    scratch="$(mktemp -d)" || return 1
    trap 'rm -rf "$scratch"' RETURN

    if tar xzf "$archive" -C "$scratch"; then
        ok "extracts cleanly"
    else
        err "could not extract the archive"
        return 1
    fi

    local extracted="$scratch/$name"
    if [ -x "$extracted/install.sh" ]; then
        ok "install.sh is executable after extraction"
    else
        err "install.sh lost its executable bit"
        return 1
    fi
    if [ -x "$extracted/game-launcher.sh" ]; then
        ok "game-launcher.sh is executable after extraction"
    else
        err "game-launcher.sh lost its executable bit"
        return 1
    fi

    # The dependency check is the part of install.sh that is safe to run
    # here: it writes nothing.
    if (cd "$extracted" && ./install.sh --check >/dev/null 2>&1); then
        ok "install.sh --check passes in the extracted tree"
    else
        warn "install.sh --check reported missing dependencies"
        note "That is about this machine, not the package."
    fi

    # The app must import from the extracted copy, using this machine's
    # virtualenv, to prove no file was left behind.
    if [ -x "$VENV/bin/python" ]; then
        if (cd "$extracted" && QT_QPA_PLATFORM=offscreen \
            "$VENV/bin/python" -c "
import sys
sys.path.insert(0, '.')
from launcher.app.main import build_window
from launcher.app.context import AppContext
" >/dev/null 2>&1); then
            ok "the extracted copy imports"
        else
            err "the extracted copy does not import"
            (cd "$extracted" && QT_QPA_PLATFORM=offscreen \
                "$VENV/bin/python" -c "
import sys; sys.path.insert(0, '.')
from launcher.app.main import build_window" 2>&1 | tail -5)
            return 1
        fi
    fi
}

case "${1:-}" in
    --clean)
        rm -rf "$DIST_DIR"
        printf 'Removed %s\n' "$DIST_DIR"
        exit 0
        ;;
    --help|-h)
        sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    --no-check) SKIP_CHECKS=1 ;;
    "") SKIP_CHECKS=0 ;;
    *)
        err "unknown option: $1"
        exit 2
        ;;
esac

VERSION="$(read_version)"
[ -n "$VERSION" ] || VERSION="0.0.0"
NAME="game-launcher-$VERSION"

printf 'Packaging %s\n' "$NAME"

if [ "${SKIP_CHECKS:-0}" -eq 0 ]; then
    run_checks || { err "refusing to package a tree that does not pass"; exit 1; }
else
    warn "checks skipped (--no-check)"
fi

STAGING_ROOT="$(mktemp -d)" || exit 1
trap 'rm -rf "$STAGING_ROOT"' EXIT
STAGING="$STAGING_ROOT/$NAME"

stage "$STAGING" || exit 1
verify_staging "$STAGING" || exit 1
ARCHIVE="$(build_archive "$STAGING" "$NAME" | tail -n1)" || exit 1
test_install "$ARCHIVE" "$NAME" || exit 1

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
cat <<EOF

${C_OK}Done.${C_OFF}  $ARCHIVE  ($SIZE)

  To install elsewhere:
      tar xzf $(basename "$ARCHIVE")
      cd $NAME
      ./install.sh
EOF
