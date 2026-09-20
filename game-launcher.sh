#!/usr/bin/env bash

WRAPPED=0
DRY_RUN=0

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
                EXTRA_VARS+=("$1")
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
        EXTRA_ARGS+=("$arg")
    done
}

# ----------------------------
# Overrides vindos do .conf do jogo
# ----------------------------
# Roda depois do `source "$CONFIG"`, e antes de wrap(): WINEPREFIX, PROTONPATH,
# GAMEID e EXTRA_VARS ja fazem parte da lista de overrides do wrap, entao nada
# precisa ser adicionado la.
resolve_conf_overrides() {
    # Prefixo por jogo. Vazio/ausente mantem o prefixo compartilhado.
    if [ -n "${GAME_PREFIX:-}" ]; then
        case "$GAME_PREFIX" in
            "~/"*) WINEPREFIX="$HOME/${GAME_PREFIX#\~/}" ;;
            /*)    WINEPREFIX="$GAME_PREFIX" ;;
            *)     WINEPREFIX="$BASE_DIR/$GAME_PREFIX" ;;
        esac
    fi

    # Proton por jogo (caminho valido DENTRO do flatpak).
    [ -n "${CUSTOM_PROTON_PATH:-}" ] && PROTONPATH="$CUSTOM_PROTON_PATH"

    # App ID alternativo resolve para GAMEID, que ja e propagado.
    [ -n "${OVERRIDE_APP_ID:-}" ] && GAMEID="$OVERRIDE_APP_ID"

    # Variaveis de ambiente declaradas no .conf.
    # Um item pode conter varios pares separados por espaco (formato antigo),
    # mas so e dividido quando TODOS os pedacos sao KEY=VALUE -- caso
    # contrario FOO="bar baz" perderia o valor.
    if [ "${#extra_vars[@]}" -gt 0 ] 2>/dev/null; then
        local var kv splittable
        for var in "${extra_vars[@]}"; do
            # shellcheck disable=SC2086
            set -- $var
            splittable=1
            [ "$#" -gt 1 ] || splittable=0
            for kv in "$@"; do
                case "$kv" in
                    [A-Za-z_]*=*) ;;
                    *) splittable=0 ;;
                esac
            done
            if [ "$splittable" = 1 ]; then
                for kv in "$@"; do
                    EXTRA_VARS+=("$kv")
                done
            else
                EXTRA_VARS+=("$var")
            fi
        done
    fi

    local key
    for key in PROTON_USE_WINE_SYNC WINEDEBUG RADV_PERFTEST PULSE_LATENCY_MSEC VKD3D_CONFIG; do
        [ -n "${!key:-}" ] && EXTRA_VARS+=("$key=${!key}")
    done

    return 0
}

print_resolved_config() {
    echo "GAME:        ${1:-<none>}"
    echo "PROGRAMPATH: $PROGRAMPATH"
    echo "WINEPREFIX:  $WINEPREFIX"
    echo "PROTONPATH:  $PROTONPATH"
    echo "GAMEID:      $GAMEID"
    echo "USE_GAMESCOPE: $USE_GAMESCOPE"
    echo "EXTRA_ARGS:  ${EXTRA_ARGS[*]}"
    echo "EXTRA_VARS:"
    local var
    for var in "${EXTRA_VARS[@]}"; do
        echo "  - $var"
    done
    echo "ADDITIONAL_DLLS: ${ADDITIONAL_DLLS[*]}"
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

    if ! mkdir -p "$WINEPREFIX" 2>/dev/null; then
        echo "Nao foi possivel criar o prefixo: $WINEPREFIX" >&2
        echo "Se ele esta fora da pasta do launcher ou da home, a Steam" >&2
        echo "Flatpak provavelmente nao enxerga esse caminho." >&2
        exit 1
    fi

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
    GAME_LABEL=""
    if [ "$1" = "-exec" ]; then
        shift
        parse_arguments "$@"
    else
        GAME_LABEL="$1"
        CONFIG="$BASE_DIR/games/$1.conf"
        if [ ! -f "$CONFIG" ]; then
            echo "Configuração não encontrada: $1"
            exit 1
        fi
        source "$CONFIG"
        resolve_conf_overrides
        parse_arguments "$GAME_EXECUTABLE" "${GAME_ARGS[@]}"
    fi

    if (( DRY_RUN )); then
        print_resolved_config "$GAME_LABEL"
        exit 0
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
    if [ "$1" = "--dry-run" ] || [ "$1" = "-n" ]; then
        DRY_RUN=1
        shift
    fi

    if [ -z "$1" ]; then
        echo "Uso: launcher [--dry-run] <jogo> | -exec <exe>"
        echo "Jogos disponíveis:"
        ls "$BASE_DIR/games" 2>/dev/null | sed 's/\.conf//'
        exit 1
    fi
    main_unwrapped "$@"
fi
