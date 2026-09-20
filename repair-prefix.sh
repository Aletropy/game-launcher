#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUPS_DIR="$LAUNCHER_DIR/backups"

OLD_PREFIX_NAME="Prefix"
if [ -f "$LAUNCHER_DIR/.prefix-name" ]; then
    read -r OLD_PREFIX_NAME < "$LAUNCHER_DIR/.prefix-name"
fi
OLD_PREFIX="$LAUNCHER_DIR/$OLD_PREFIX_NAME"

SAVE_DIRS=(
    "AppData/Local"
    "AppData/LocalLow"
    "AppData/Roaming"
    "Documents"
    "Saved Games"
)

read_input() {
    local prompt="$1"
    local var="$2"
    local -n ref="$var"
    read -r -p "$prompt" ref
}

confirm() {
    local prompt="$1"
    local default="${2:-n}"
    local answer
    read -r -p "$prompt" answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy]$ ]]
}

dir_has_content() {
    [ -d "$1" ] && [ -n "$(ls -A "$1" 2>/dev/null)" ]
}

backup_saves() {
    local dest="$1"
    local src_user="$OLD_PREFIX/pfx/drive_c/users/steamuser"
    local src_programdata="$OLD_PREFIX/pfx/drive_c/ProgramData"
    local found=0

    for dir in "${SAVE_DIRS[@]}"; do
        if dir_has_content "$src_user/$dir"; then
            found=1
            break
        fi
    done
    if dir_has_content "$src_programdata"; then
        found=1
    fi

    if [ "$found" -eq 0 ]; then
        echo "  No save data found in the current prefix."
        return 1
    fi

    mkdir -p "$dest/steamuser"

    for dir in "${SAVE_DIRS[@]}"; do
        src="$src_user/$dir"
        if dir_has_content "$src"; then
            echo "  Backing up steamuser/$dir ..."
            mkdir -p "$dest/steamuser/$(dirname "$dir")"
            cp -a "$src" "$dest/steamuser/$dir"
        fi
    done

    if dir_has_content "$src_programdata"; then
        echo "  Backing up ProgramData ..."
        cp -a "$src_programdata" "$dest/ProgramData"
    fi

    echo "  Backup saved to: $dest"
    return 0
}

restore_saves() {
    local src="$1"
    local dest_user="$2/pfx/drive_c/users/steamuser"
    local dest_programdata="$2/pfx/drive_c/ProgramData"

    if [ ! -d "$src/steamuser" ] && [ ! -d "$src/ProgramData" ]; then
        echo "  Backup contains no restorable save data."
        return 1
    fi

    if [ -d "$src/steamuser" ]; then
        for dir in "${SAVE_DIRS[@]}"; do
            s="$src/steamuser/$dir"
            if [ -d "$s" ]; then
                echo "  Restoring steamuser/$dir ..."
                mkdir -p "$dest_user/$(dirname "$dir")"
                cp -a "$s" "$dest_user/$dir"
            fi
        done
    fi

    if [ -d "$src/ProgramData" ]; then
        echo "  Restoring ProgramData ..."
        mkdir -p "$dest_programdata"
        cp -a "$src/ProgramData/." "$dest_programdata/"
    fi

    echo "  Saves restored from: $src"
    return 0
}

list_backups() {
    if [ ! -d "$BACKUPS_DIR" ]; then
        return 1
    fi
    local i=0
    local -a names=()
    for dir in "$BACKUPS_DIR"/*/; do
        [ -d "$dir" ] || continue
        names+=("$(basename "$dir")")
    done

    if [ "${#names[@]}" -eq 0 ]; then
        return 1
    fi

    echo "Available backups:"
    for name in "${names[@]}"; do
        i=$((i + 1))
        local label=""
        if [ -d "$BACKUPS_DIR/$name/steamuser" ]; then
            label=" (contains saves)"
        fi
        printf "  %d) %s%s\n" "$i" "$name" "$label"
    done

    echo ""
    read_input "Select a backup [1-$i]: " choice
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$i" ]; then
        echo "Invalid selection."
        return 2
    fi

    SELECTED_BACKUP="$BACKUPS_DIR/${names[$((choice - 1))]}"
    echo "Selected: $SELECTED_BACKUP"
    return 0
}

print_header() {
    echo "=== Prefix Repair Wizard ==="
    echo ""
    echo "Launcher root:  $LAUNCHER_DIR"
    echo "Current prefix: $OLD_PREFIX"
    echo ""
}

print_menu() {
    echo "Step 1 - What do you want to do?"
    echo "  1) Backup current saves, then repair prefix"
    echo "  2) Repair prefix, restoring from an existing backup"
    echo "  3) Fresh start - repair without any backup or restore"
    echo ""
    read_input "Enter choice [1-3]: " WIZARD_CHOICE
    if ! [[ "$WIZARD_CHOICE" =~ ^[1-3]$ ]]; then
        echo "Invalid choice."
        exit 1
    fi
}

choose_prefix_name() {
    echo ""
    echo "Step 2 - Prefix folder name"
    read_input "  Enter prefix folder name [$OLD_PREFIX_NAME]: " NEW_PREFIX_NAME
    if [ -z "$NEW_PREFIX_NAME" ]; then
        NEW_PREFIX_NAME="$OLD_PREFIX_NAME"
    fi

    if [[ ! "$NEW_PREFIX_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
        echo "  Invalid prefix name. Use letters, numbers, '.', '_' or '-'."
        exit 1
    fi
}

ask_restore() {
    echo ""
    echo "Step 3 - Restore saves"
    if confirm "  Restore saves into the new prefix? (Y/n): " y; then
        DO_RESTORE=1
    else
        DO_RESTORE=0
        echo "  OK, saves will not be copied into the new prefix."
    fi
}

confirm_plan() {
    echo ""
    echo "=== Summary ==="
    echo "  Action:        $ACTION_LABEL"
    echo "  Prefix name:   $NEW_PREFIX_NAME"
    echo "  Backup source: $BACKUP_SOURCE_LABEL"
    echo "  Restore saves: $([ "$DO_RESTORE" -eq 1 ] && echo "Yes" || echo "No")"
    echo ""
    echo "  WARNING: This will DELETE the current prefix folder:"
    echo "  $OLD_PREFIX"
    if [ "$OLD_PREFIX" != "$LAUNCHER_DIR/$NEW_PREFIX_NAME" ]; then
        echo "  and create a new one at:"
        echo "  $LAUNCHER_DIR/$NEW_PREFIX_NAME"
    fi
    echo ""
    if ! confirm "  Proceed? (y/N): "; then
        echo "Aborted."
        exit 1
    fi
}

execute() {
    echo ""
    echo "=== Executing ==="

    NEW_PREFIX="$LAUNCHER_DIR/$NEW_PREFIX_NAME"

    echo "Step 1: Recreating prefix..."
    rm -rf "$OLD_PREFIX"
    mkdir -p "$NEW_PREFIX"

    if [ "$DO_RESTORE" -eq 1 ] && [ -n "$RESTORE_FROM" ]; then
        echo "Step 2: Restoring saves into new prefix..."
        restore_saves "$RESTORE_FROM" "$NEW_PREFIX" || echo "  (nothing was restored)"
    fi

    if [ "$NEW_PREFIX_NAME" != "Prefix" ]; then
        printf '%s\n' "$NEW_PREFIX_NAME" > "$LAUNCHER_DIR/.prefix-name"
        echo "Step 3: Wrote .prefix-name = $NEW_PREFIX_NAME"
    elif [ -f "$LAUNCHER_DIR/.prefix-name" ]; then
        rm -f "$LAUNCHER_DIR/.prefix-name"
        echo "Step 3: Removed .prefix-name (using default 'Prefix')"
    fi

    echo ""
    echo "=== Done ==="
    if [ "$DO_RESTORE" -eq 1 ] && [ -n "$RESTORE_FROM" ]; then
        echo "Backup preserved at: $RESTORE_FROM"
    fi
    echo "Launch a game to let Proton populate the new prefix."
}

# =====================
# Wizard
# =====================
print_header
print_menu

WIZARD_CHOICE="${WIZARD_CHOICE:-}"
RESTORE_FROM=""
DO_RESTORE=0

case "$WIZARD_CHOICE" in
    1)
        ACTION_LABEL="Create new backup + repair"
        echo ""
        echo "Creating a new backup of current saves..."
        TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
        NEW_BACKUP="$BACKUPS_DIR/$TIMESTAMP"
        if backup_saves "$NEW_BACKUP"; then
            RESTORE_FROM="$NEW_BACKUP"
            BACKUP_SOURCE_LABEL="$NEW_BACKUP (new)"
            choose_prefix_name
            ask_restore
        else
            echo "  No save data found. Proceeding with a fresh prefix."
            BACKUP_SOURCE_LABEL="None (no saves found)"
            choose_prefix_name
            DO_RESTORE=0
        fi
        ;;
    2)
        ACTION_LABEL="Restore from existing backup"
        echo ""
        if ! list_backups; then
            echo "No backups available or invalid selection."
            echo "Run the wizard again and choose option 1 to create a backup first."
            exit 1
        fi
        RESTORE_FROM="$SELECTED_BACKUP"
        BACKUP_SOURCE_LABEL="$RESTORE_FROM"
        choose_prefix_name
        ask_restore
        ;;
    3)
        ACTION_LABEL="Fresh start (no backup, no restore)"
        BACKUP_SOURCE_LABEL="None"
        choose_prefix_name
        DO_RESTORE=0
        ;;
esac

confirm_plan
execute
