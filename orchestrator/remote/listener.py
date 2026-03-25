"""Remote workspace listener: receives tasks from orchestrator via HTTP and executes locally.

Standalone script — deploy to any remote host with Python 3.10+ and claude-agent-sdk.
Run: LISTENER_CWD=/path/to/workspace LISTENER_PORT=9100 python3 listener.py

Environment variables:
    LISTENER_CWD   — workspace directory (default: cwd)
    LISTENER_PORT   — port to listen on (default: 9100)
    LISTENER_TOKEN  — optional bearer token for auth
"""

import asyncio
import json
import logging
import os
import re

# Remove env vars that interfere with claude-agent-sdk subprocess spawning
for _key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
    os.environ.pop(_key, None)

from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [listener] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE_CWD = os.environ.get("LISTENER_CWD", os.getcwd())
LISTENER_PORT = int(os.environ.get("LISTENER_PORT", "9100"))
LISTENER_TOKEN = os.environ.get("LISTENER_TOKEN", "")

# ── Standalone JSON extraction (mirrors orchestrator/__init__.py) ────────


def extract_json(text: str) -> dict:
    """Extract JSON from text with multiple fallback strategies.

    1. Direct parse
    2. Markdown code fence extraction
    3. Brace-matching (all top-level {} pairs, largest first)
    """
    text = text.strip()

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Markdown code fence
    for match in re.finditer(r"