#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

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

echo "=========================================="
echo "  claude-code-tunnels bootstrap installer"
echo "=========================================="
echo ""
echo "root: $ROOT_DIR"
echo "python: $PYTHON_BIN"
if [[ -n "$NODE_BIN" ]]; then
    echo "node: $NODE_BIN"
else
    echo "node: not found"
fi
if [[ -n "$NPM_BIN" ]]; then
    echo "npm: $NPM_BIN"
else
    echo "npm: not found"
fi
echo ""

echo "[1/3] Creating local virtualenv"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo "[2/3] Installing Python dependencies"
"$VENV_DIR/bin/pip" install -U pip
"$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt" -r "$ROOT_DIR/requirements-dev.txt"

echo "[3/3] Installing Node bridge dependencies"
if [[ -n "$NPM_BIN" ]]; then
    (cd "$ROOT_DIR" && "$NPM_BIN" install)
else
    echo "Skipping npm install because no working npm binary was found."
    echo "Codex/OpenCode runtimes will not work until Node.js and npm are available."
fi

echo ""
echo "Verification"
echo "-----------"
"$VENV_DIR/bin/python" -c "import claude_agent_sdk, aiohttp, yaml, textual; print('python packages: OK')"
if command -v claude >/dev/null 2>&1; then
    echo "claude: $(claude --version | head -1)"
else
    echo "claude: not found"
fi
if command -v cursor-agent >/dev/null 2>&1; then
    echo "cursor-agent: $(cursor-agent --version | head -1)"
else
    echo "cursor-agent: not found"
fi
if command -v codex >/dev/null 2>&1; then
    echo "codex: $(codex --version | head -1)"
    echo "codex auth: $(codex login status | head -1)"
else
    echo "codex: not found"
fi
if command -v opencode >/dev/null 2>&1; then
    echo "opencode: $(opencode --version | tail -1)"
    echo "opencode providers: $(opencode providers list | tail -1)"
else
    echo "opencode: not found"
fi

echo ""
echo "Next step"
echo "---------"
echo "Run the setup TUI from the project root:"
echo "  cd $ROOT_DIR"
echo "  ./.venv/bin/python -m orchestrator.setup_tui"
echo ""
echo "After setup finishes, it will explain:"
echo "  ./start-orchestrator.sh --fg"
echo "  ./start-orchestrator.sh"
