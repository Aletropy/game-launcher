#!/bin/bash

STEAM_COMPATDATA="$HOME/.var/app/com.valvesoftware.Steam/.steam/steam/steamapps/compatdata"
MASTER_PREFIX="$(cd "$(dirname "$0")" && pwd)/Prefix"
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

echo "Steam Flatpak Migration complete."
