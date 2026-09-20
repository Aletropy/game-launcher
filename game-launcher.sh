#!/usr/bin/env bash

WRAPPED=0

# ----------------------------
# Defaults globais
# ----------------------------
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
FLATPAK_ID="com.valvesoftware.Steam"

GAMEID="${GAMEID:-480}"

PREFIX_NAME="Prefix"
PREFIX_NAME_FILE="$BASE_DIR/.prefix-name"
if [ -f "$PREFIX_NAME_FILE" ]; then
    read -r PREFIX_NAME < "$PREFIX_NAME_FILE"
fi

WINEPREFIX="${WINEPREFIX:-$BASE_DIR/$PREFIX_NAME}"
PROTONPATH="${PROTONPATH:-/app/share/steam/compatibilitytools.d/Proton-GE}"
PROTON_VERB="${PROTON_VERB:-run}"

PROGRAMPATH=""
GAME_ARGS=()

EXTRA_VARS=()
EXTRA_ARGS=()
ADDITIONAL_DLLS=()

USE_GAMESCOPE="${USE_GAMESCOPE:-0}"
GAMESCOPE_W="${GAMESCOPE_W:-1280}"
GAMESCOPE_H="${GAMESCOPE_H:-720}"
GAMESCOPE_W_OUT="${GAMESCOPE_W_OUT:-1920}"
GAMESCOPE_H_OUT="${GAMESCOPE_H_OUT:-1080}"
GAMESCOPE_ARGS="${GAMESCOPE_ARGS:--f -e}"   # -f: fullscreen, -e: Steam integration

# ----------------------------
# Argument parsing
# ----------------------------
parse_arguments() {
    while :
    do
        case "$1" in
            --)
                shift
                break
                ;;
            *=*)
                EXTRA_VARS+=("${1@Q}")
                shift
                ;;
            *)
                break
                ;;
        esac
    done

    PROGRAMPATH="$1"
    shift

    for arg in "$@"; do
        EXTRA_ARGS+=("${arg@Q}")
    done
}

# ----------------------------
# Wrapper auto-reescrevente
# ----------------------------
wrap() {
    # <-- ADDITIONAL_DLLS incluído na lista abaixo
    local overrides=(
        PROGRAMPATH GAMEID WINEPREFIX PROTONPATH PROTON_VERB
        EXTRA_ARGS EXTRA_VARS WRAPPED ADDITIONAL_DLLS
        USE_GAMESCOPE GAMESCOPE_W GAMESCOPE_H GAMESCOPE_W_OUT GAMESCOPE_H_OUT GAMESCOPE_ARGS
    )
    local WRAPPED=1

    sed -E -f <(
        for ov in "${overrides[@]}"; do
            declare -n ref="$ov"
            local val

            if [[ "$(declare -p "$ov")" =~ "declare -a" ]]; then
                val="${ref[*]@Q}"
            else
                val="${ref@Q}"
            fi

            val="${val//\\/\\\\}"
            val="${val//&/\\&}"
            val="${val//|/\\|}"

            if [[ "$(declare -p "$ov")" =~ "declare -a" ]]; then
                printf 's|^%s=.*$|%s=(%s)|\n' "$ov" "$ov" "$val"
            else
                printf 's|^%s=.*$|%s=%s|\n' "$ov" "$ov" "$val"
            fi
        done
    ) "$0"
}

# ----------------------------
# Execution inside Flatpak
# ----------------------------
run_game() {
    local _WINEPREFIX="$WINEPREFIX"
    local _PROGRAMPATH="$PROGRAMPATH"
    local _GAMEID="$GAMEID"
    local _PROTONPATH="$PROTONPATH"

    # Real steam ambient
    while read -r -d '' line; do
        export "$line"
    done < /proc/2/environ

    WINEPREFIX="$_WINEPREFIX"
    PROGRAMPATH="$_PROGRAMPATH"
    GAMEID="$_GAMEID"
    PROTONPATH="$_PROTONPATH"

    export WINEPREFIX

    for var in "${EXTRA_VARS[@]}"; do
        export "$var"
    done

    mkdir -p "$WINEPREFIX"

    EXEC_DIR="$(dirname "$PROGRAMPATH")"
    cd "$EXEC_DIR" || exit 1

    # ----------------------------
    # DLL overrides
    # ----------------------------
    dlls=(
        "OnlineFix64=n,b"
        "SteamOverlay64=n,b"
        "SteamOverlay32=n,b"
        "Custom=n,b"
        "steam_api=n,b"
        "steam_api64=n,b"
        "version=n,b"
        "winmm=n,b"
        "winhttp=n,b"
        "dnet=n,b"
    )

    # <-- Merge das DLLs adicionais do .conf
    dlls+=("${ADDITIONAL_DLLS[@]}")

    export WINEDLLOVERRIDES="$(IFS=';'; echo "${dlls[*]}")${WINEDLLOVERRIDES:+:$WINEDLLOVERRIDES}"

    # ----------------------------
    # Steam / Proton env
    # ----------------------------
    export STEAM_COMPAT_APP_ID="$GAMEID"
    export SteamAppId="$GAMEID"
    export SteamGameId="$GAMEID"

    export STEAM_COMPAT_DATA_PATH="$WINEPREFIX"
    export STEAM_COMPAT_SHADER_PATH="$WINEPREFIX/shadercache"
    export STEAM_COMPAT_TOOL_PATHS="$PROTONPATH"
    export STEAM_COMPAT_MOUNTS="$STEAM_COMPAT_TOOL_PATHS"
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="/var/data/Steam"
    export LD_PRELOAD=":/var/data/Steam/ubuntu12_32/gameoverlayrenderer.so:/var/data/Steam/ubuntu12_64/gameoverlayrenderer.so"

    #export PROTON_USE_WINED3D=1
    export PROTON_LOG=1

    GAMESCOPE_CMD=()
    if [ "$USE_GAMESCOPE" = "1" ]; then
        GAMESCOPE_CMD=(
            gamescope
            -w "$GAMESCOPE_W"
            -h "$GAMESCOPE_H"
            -W "$GAMESCOPE_W_OUT"
            -H "$GAMESCOPE_H_OUT"
            ${GAMESCOPE_ARGS}
            --
        )
    fi

    # ----------------------------
    # Exec Proton
    # ----------------------------
    exec "${GAMESCOPE_CMD[@]}" "$PROTONPATH/proton" "$PROTON_VERB" "$PROGRAMPATH" "${EXTRA_ARGS[@]}"
}

# ----------------------------
# Modo externo (host)
# ----------------------------
main_unwrapped() {
    if [ "$1" = "-exec" ]; then
        shift
        parse_arguments "$@"
    else
        CONFIG="$BASE_DIR/games/$1.conf"
        if [ ! -f "$CONFIG" ]; then
            echo "Configuração não encontrada: $1"
            exit 1
        fi
        source "$CONFIG"
        parse_arguments "$GAME_EXECUTABLE" "${GAME_ARGS[@]}"
    fi

    STEAM_PID=$(flatpak ps | awk 'tolower($3) ~ /steam/ {print $2}' | sort -n | head -n1)

    # CORRIGIDO: Adicionado espaço entre o if e o [
    if [ -z "$STEAM_PID" ]; then
        echo "Steam Flatpak não está rodando."
        exit 1
    fi

    echo "Entrando no container da Steam (PID $STEAM_PID)"
    flatpak enter "$STEAM_PID" bash < <(wrap)
}

# ----------------------------
# Dispatcher
# ----------------------------
if (( WRAPPED )); then
    run_game "$@"
else
    # CORRIGIDO: Adicionado espaço entre o if e o[
    if [ -z "$1" ]; then
        echo "Uso: launcher <jogo> | -exec <exe>"
        echo "Jogos disponíveis:"
        ls "$BASE_DIR/games" 2>/dev/null | sed 's/\.conf//'
        exit 1
    fi
    main_unwrapped "$@"
fi
