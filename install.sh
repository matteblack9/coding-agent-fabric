#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "======================================"
echo "  Claude-Code-Tunnels Plugin Installer"
echo "======================================"
echo ""
echo "Plugin source: $PLUGIN_DIR"
echo ""

# Step 1: Install Python dependencies
echo "[1/2] Installing Python dependencies..."
pip install claude-agent-sdk aiohttp pyyaml 2>/dev/null || {
    echo "  pip install failed. Please install manually:"
    echo "    pip install claude-agent-sdk aiohttp pyyaml"
}

# Step 2: Verify
echo "[2/2] Verifying installation..."

if python3 -c "import claude_agent_sdk" 2>/dev/null; then
    echo "  claude-agent-sdk: OK"
else
    echo "  claude-agent-sdk: NOT FOUND (install with: pip install claude-agent-sdk)"
fi

if python3 -c "import aiohttp" 2>/dev/null; then
    echo "  aiohttp: OK"
else
    echo "  aiohttp: NOT FOUND"
fi

if python3 -c "import yaml" 2>/dev/null; then
    echo "  pyyaml: OK"
else
    echo "  pyyaml: NOT FOUND"
fi

echo ""
echo "======================================"
echo "  Installation complete!"
echo "======================================"
echo ""
echo "Usage as Claude Code plugin:"
echo "  claude --plugin-dir $PLUGIN_DIR"
echo ""
echo "Skills available (namespaced as /claude-code-tunnels:<skill>):"
echo "  /claude-code-tunnels:setup-orchestrator"
echo "  /claude-code-tunnels:connect-slack"
echo "  /claude-code-tunnels:connect-telegram"
echo "  /claude-code-tunnels:setup-remote-project"
echo "  /claude-code-tunnels:setup-remote-workspace"
echo ""
echo "Or manually copy orchestrator code:"
echo "  1. cp -r $PLUGIN_DIR/orchestrator/ ./orchestrator/"
echo "  2. cp $PLUGIN_DIR/orchestrator.yaml ./orchestrator.yaml"
echo "  3. Edit orchestrator.yaml with your paths"
echo "  4. cp $PLUGIN_DIR/templates/start-orchestrator.sh.template ./start-orchestrator.sh"
echo "  5. ./start-orchestrator.sh"
echo ""
