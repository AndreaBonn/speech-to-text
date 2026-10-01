#!/usr/bin/env bash
# Start sbobina with one command on Linux (main platform) and macOS:
# installs uv if missing, prepares the environment and opens the web UI.
# Usage: ./avvia.sh [--port N] [--no-browser]
set -euo pipefail

cd "$(dirname "$0")"

UV_INSTALLER_URL="https://astral.sh/uv/install.sh"
# Default location of the standalone installer on Linux and macOS.
UV_BIN_DIR="$HOME/.local/bin"

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi
    if [ -x "$UV_BIN_DIR/uv" ]; then
        export PATH="$UV_BIN_DIR:$PATH"
        return
    fi
    echo "Serve uv (gestisce Python e le librerie di sbobina) e non è installato."
    printf "Lo installo ora da %s? [S/n] " "$UV_INSTALLER_URL"
    # No terminal to answer (stdin closed): never install without consent.
    if ! read -r answer; then
        echo
        echo "Nessuna risposta possibile qui: installa uv a mano e rilancia ./avvia.sh"
        echo "Istruzioni: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    case "${answer:-S}" in
        [sS]*) ;;
        *)
            echo "Installazione annullata. Istruzioni: https://docs.astral.sh/uv/getting-started/installation/"
            exit 1
            ;;
    esac
    if ! command -v curl >/dev/null 2>&1; then
        echo "Manca curl: installalo (es. 'sudo apt install curl') e rilancia ./avvia.sh"
        exit 1
    fi
    curl -LsSf "$UV_INSTALLER_URL" | sh
    export PATH="$UV_BIN_DIR:$PATH"
}

# Prints gpu, broken (nvidia-smi present but failing) or none.
nvidia_gpu_state() {
    if [ "$(uname -s)" != "Linux" ] || ! command -v nvidia-smi >/dev/null 2>&1; then
        echo none
    elif nvidia-smi -L >/dev/null 2>&1; then
        echo gpu
    else
        echo broken
    fi
}

ensure_uv

# `uv run` syncs the environment on its own and never removes packages, so
# the CUDA extra stays installed once added.
extra_args=()
case "$(nvidia_gpu_state)" in
    gpu)
        echo "Scheda NVIDIA trovata: uso la GPU."
        extra_args=(--extra cuda)
        ;;
    broken)
        echo "La scheda NVIDIA non risponde (driver non caricato?): uso il processore, più lento."
        ;;
    *)
        echo "Nessuna scheda NVIDIA: la trascrizione userà il processore (più lenta)."
        ;;
esac

echo "Preparo l'ambiente (la prima volta può richiedere qualche minuto)..."
# ${a[@]+...} keeps an empty array safe under set -u on bash 3.2 (macOS).
exec uv run ${extra_args[@]+"${extra_args[@]}"} sbobina web "$@"
