#!/bin/bash

STEAM_COMPATDATA="$HOME/.local/share/Steam/steamapps/compatdata"
LAUNCHER_DIR="$(cd "$(dirname "$0")" && pwd)"

# Same prefix resolution the launcher uses: an explicit path wins, then
# .prefix-name, then the default. Previously this was hardcoded to
# ./Prefix and ignored .prefix-name entirely.
if [ -n "$1" ]; then
    MASTER_PREFIX="$1"
else
    PREFIX_NAME="Prefix"
    if [ -f "$LAUNCHER_DIR/.prefix-name" ]; then
        read -r PREFIX_NAME < "$LAUNCHER_DIR/.prefix-name"
    fi
    MASTER_PREFIX="$LAUNCHER_DIR/$PREFIX_NAME"
fi
DEST_USER="$MASTER_PREFIX/pfx/drive_c/users/steamuser"

mkdir -p "$DEST_USER/AppData/Local"
mkdir -p "$DEST_USER/AppData/LocalLow"
mkdir -p "$DEST_USER/AppData/Roaming"
mkdir -p "$DEST_USER/Documents"
mkdir -p "$DEST_USER/Saved Games"

for folder in "$STEAM_COMPATDATA"/*; do
    if [ -d "$folder/pfx" ]; then
        APPID=$(basename "$folder")
        SRC_USER="$folder/pfx/drive_c/users/steamuser"
        echo "Migrating saves from AppID: $APPID..."

        if [ -d "$SRC_USER/AppData/Local" ]; then
            rsync -au "$SRC_USER/AppData/Local/" "$DEST_USER/AppData/Local/"
        fi
        if [ -d "$SRC_USER/AppData/LocalLow" ]; then
            rsync -au "$SRC_USER/AppData/LocalLow/" "$DEST_USER/AppData/LocalLow/"
        fi
        if [ -d "$SRC_USER/AppData/Roaming" ]; then
            rsync -au "$SRC_USER/AppData/Roaming/" "$DEST_USER/AppData/Roaming/"
        fi
        if [ -d "$SRC_USER/Documents" ]; then
            rsync -au "$SRC_USER/Documents/" "$DEST_USER/Documents/"
        fi
        if [ -d "$SRC_USER/Saved Games" ]; then
            rsync -au "$SRC_USER/Saved Games/" "$DEST_USER/Saved Games/"
        fi

        SRC_PROGRAMDATA="$folder/pfx/drive_c/ProgramData"
        DEST_PROGRAMDATA="$MASTER_PREFIX/pfx/drive_c/ProgramData"
        if [ -d "$SRC_PROGRAMDATA" ]; then
            mkdir -p "$DEST_PROGRAMDATA"
            rsync -au "$SRC_PROGRAMDATA/" "$DEST_PROGRAMDATA/"
        fi
    fi
done

echo "Steam Native Migration complete."
