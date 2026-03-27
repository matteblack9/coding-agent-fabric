#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
LOG_FILE="$ROOT_DIR/.setup-bootstrap.log"

find_working_bin() {
    local name="$1"
    shift
    IFS=':' read -r -a dirs <<< "${PATH:-}"
    for dir in "${dirs[@]}"; do
        local candidate="$dir/$name"
        if [[ -x "$candidate" ]] && "$candidate" "$@" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

render_progress() {
    local percent="$1"
    local label="$2"
    local width=30
    local filled=$(( percent * width / 100 ))
    local empty=$(( width - filled ))
    local fill bar
    printf -v fill '%*s' "$filled" ''
    printf -v bar '%*s' "$empty" ''
    fill="${fill// /#}"
    bar="${bar// /-}"
    printf '\r[%s%s] %3d%% %s' "$fill" "$bar" "$percent" "$label"
    if [[ "$percent" -ge 100 ]]; then
        printf '\n'
    fi
}

fail_setup() {
    printf '\nSetup failed. See %s\n' "$LOG_FILE" >&2
    exit 1
}

run_logged() {
    "$@" >>"$LOG_FILE" 2>&1
}

trap fail_setup ERR

: >"$LOG_FILE"

PYTHON_BIN="$(find_working_bin python3 --version || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(find_working_bin python --version || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
    echo "Python 3 is required."
    exit 1
fi

NODE_BIN="$(find_working_bin node --version || true)"
NPM_BIN="$(find_working_bin npm --version || true)"

render_progress 5 "Preparing setup"

render_progress 20 "Creating local environment"
run_logged "$PYTHON_BIN" -m venv "$VENV_DIR"

render_progress 50 "Installing Python dependencies"
run_logged "$VENV_DIR/bin/pip" install -U pip
run_logged "$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt" -r "$ROOT_DIR/requirements-dev.txt"

if [[ -n "$NPM_BIN" ]]; then
    render_progress 75 "Installing bridge dependencies"
    (
        cd "$ROOT_DIR"
        "$NPM_BIN" install
    ) >>"$LOG_FILE" 2>&1
else
    render_progress 75 "Skipping bridge dependencies"
fi

render_progress 90 "Verifying local environment"
run_logged "$VENV_DIR/bin/python" -c "import claude_agent_sdk, aiohttp, yaml, InquirerPy"

render_progress 100 "Opening setup wizard"
(
    cd "$ROOT_DIR"
    exec "$VENV_DIR/bin/python" -m orchestrator.install_flow "$ROOT_DIR"
)
