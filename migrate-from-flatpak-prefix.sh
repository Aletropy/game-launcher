#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "$0")" && pwd)"

PREFIX_NAME="Prefix"
if [ -f "$LAUNCHER_DIR/.prefix-name" ]; then
    read -r PREFIX_NAME < "$LAUNCHER_DIR/.prefix-name"
fi
PREFIX="$LAUNCHER_DIR/$PREFIX_NAME"
PFX_USER="$PREFIX/pfx/drive_c/users/steamuser"
PFX_PROGRAMDATA="$PREFIX/pfx/drive_c/ProgramData"

FLATPAK_STEAM_COMPAT=(
    "$HOME/.var/app/com.valvesoftware.Steam/.steam/steam/steamapps/compatdata"
    "$HOME/.var/app/com.valvesoftware.Steam/data/steam/steamapps/compatdata"
    "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata"
)
NATIVE_STEAM_COMPAT="$HOME/.local/share/Steam/steamapps/compatdata"

SAVE_PAIRS=(
    "drive_c/users/steamuser/AppData/Local|AppData/Local"
    "drive_c/users/steamuser/AppData/LocalLow|AppData/LocalLow"
    "drive_c/users/steamuser/AppData/Roaming|AppData/Roaming"
    "drive_c/users/steamuser/Application Data|AppData/Roaming"
    "drive_c/users/steamuser/Documents|Documents"
    "drive_c/users/steamuser/My Documents|Documents"
    "drive_c/users/steamuser/Saved Games|Saved Games"
    "drive_c/ProgramData|ProgramData"
)

dest_for_save() {
    local dest_rel="$1"
    if [ "$dest_rel" = "ProgramData" ]; then
        printf '%s' "$PFX_PROGRAMDATA"
    else
        printf '%s' "$PFX_USER/$dest_rel"
    fi
}

migrate_from_compatdata() {
    local compat_dir="$1"
    local label="$2"

    if [ ! -d "$compat_dir" ]; then
        return
    fi

    echo "Scanning $label compatdata folders for saves..."
    local found=0
    for folder in "$compat_dir"/*/; do
        [ -d "$folder" ] || continue
        appid="$(basename "$folder")"

        for pair in "${SAVE_PAIRS[@]}"; do
            src_rel="${pair%%|*}"
            dest_rel="${pair#*|}"
            src="$folder/pfx/$src_rel"
            if [ ! -d "$src" ] || [ -z "$(ls -A "$src" 2>/dev/null)" ]; then
                continue
            fi

            found=1
            dest="$(dest_for_save "$dest_rel")"
            echo "  [App $appid] $src_rel -> Prefix/$dest_rel/"
            mkdir -p "$(dirname "$dest")"
            cp -an "$src"/. "$dest"/
        done
    done

    if [ "$found" -eq 0 ]; then
        echo "  No save data found in $label compatdata."
    fi
}

copy_from_container() {
    local src="$1"
    local dest="$2"

    # flatpak enter does not propagate the inner command's exit status and
    # mangles quotes in the command string, so pass the paths as positional
    # arguments and signal success with a marker on stdout instead.
    flatpak enter "$STEAM_PID" bash -c '
        if [ -d "$1" ] && [ -n "$(ls -A "$1" 2>/dev/null)" ]; then
            mkdir -p "$2"
            cp -an "$1"/. "$2"/ && echo COPIED
        fi
    ' _ "$src" "$dest" 2>/dev/null | grep -qx COPIED
}

migrate_from_flatpak_container() {
    echo ""
    echo "Looking for a misplaced prefix inside the Flatpak container..."

    STEAM_PID=$(flatpak ps 2>/dev/null | awk 'tolower($3) ~ /steam/ {print $2}' | sort -n | head -n1)
    if [ -z "$STEAM_PID" ]; then
        echo "  Steam Flatpak is not running. Skipping container scan."
        echo "  Start Steam and run this script again for the full migration."
        return
    fi

    echo "  Steam Flatpak running at PID $STEAM_PID"

    CANDIDATE_PATHS=(
        "$LAUNCHER_DIR/$PREFIX_NAME"
        "/app/Projects/Launcher/Prefix"
        "/app/launcher/Prefix"
        "$HOME/.steam/steam/steamapps/compatdata"
    )

    dest_pfx="$(realpath -m "$PREFIX/pfx")"

    for candidate in "${CANDIDATE_PATHS[@]}"; do
        echo "  Checking $candidate inside container..."
        found_pfxs=$(flatpak enter "$STEAM_PID" bash -c 'find "$1" -maxdepth 4 -type d -name pfx 2>/dev/null' _ "$candidate" 2>/dev/null || true)
        if [ -n "$found_pfxs" ]; then
            while IFS= read -r pfx_dir; do
                [ -n "$pfx_dir" ] || continue
                if [ "$(realpath -m "$pfx_dir")" = "$dest_pfx" ]; then
                    echo "    Skipping $pfx_dir (this is the destination prefix)."
                    continue
                fi
                echo "  Found prefix at $pfx_dir inside container. Copying data out..."
                for pair in "${SAVE_PAIRS[@]}"; do
                    src_rel="${pair%%|*}"
                    dest_rel="${pair#*|}"
                    src="$pfx_dir/$src_rel"
                    dest="$(dest_for_save "$dest_rel")"
                    if copy_from_container "$src" "$dest"; then
                        echo "    Copied $dest_rel ..."
                    fi
                done
            done <<< "$found_pfxs"
        fi
    done
}

echo "=== Migrate Prefix Data to Launcher Root ==="
echo "Launcher: $LAUNCHER_DIR"
echo "Target:   $PREFIX"
echo ""

mkdir -p "$PFX_USER/AppData/Local"
mkdir -p "$PFX_USER/AppData/LocalLow"
mkdir -p "$PFX_USER/AppData/Roaming"
mkdir -p "$PFX_USER/Documents"
mkdir -p "$PFX_USER/Saved Games"
mkdir -p "$PFX_PROGRAMDATA"

for compat in "${FLATPAK_STEAM_COMPAT[@]}"; do
    migrate_from_compatdata "$compat" "Steam Flatpak"
done
migrate_from_compatdata "$NATIVE_STEAM_COMPAT" "Steam Native"
migrate_from_flatpak_container

echo ""
echo "=== Migration complete ==="
echo "All found save data has been copied into:"
echo "  $PREFIX"
echo ""
echo "Run 'repair-prefix.sh' if you need to back up and recreate the prefix later."
