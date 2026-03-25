# Orchestrator

Claude Agent SDK + `cwd`-based Task Delegation Architecture.

## Architecture Overview

### Agent SDK + cwd
```
Messenger → Python middleware → query(cwd=project/) [PO: routing + dependency resolution]
                                  → query(cwd=workspace/) [per-workspace execution]
```

## Core Design Decisions

1. **Existing CLAUDE.md + .claude/ untouched** — All project/workspace configurations are used as-is.
2. **cwd-based config auto-loading** — `query(cwd="workspace-path")` hierarchically loads the CLAUDE.md + .claude/* at that path.
3. **PO dynamically resolves dependencies** — No static DAG. Phases are determined by analyzing task content on every request.
4. **Python has no business logic** — It only calls `query()` while switching `cwd`.

## Structure

```
orchestrator/
├── __init__.py      # BASE path, extract_json utility
├── po.py            # PO: query(cwd=project/) → execution plan JSON
├── executor.py      # Phase-by-phase workspace query(cwd=workspace/) execution
├── task_log.py      # Task log at .tasks/{date}/{project}/{task_id}_{label}.md
├── server.py        # Entry point: channel routing, ConfirmGate, overall flow
├── scripts/
│   └── cleanup.sh   # Cleanup legacy communication .tasks/ files
└── tests/
    ├── test_executor.py
    ├── test_task_log.py
    └── test_server.py
```

## Installation

```bash
pip install claude-agent-sdk
```

## Usage

```python
import asyncio
from orchestrator.server import handle_request

result = asyncio.run(handle_request(
    user_message="Add a health check API to the new-place server",
    channel="cli",
    callback_info={},
))
```

### Using ConfirmGate

```python
from orchestrator.server import ConfirmGate

gate = ConfirmGate()
gate.create_request("req-1", "add health check", "works", {"bot_id": "..."})

# After user confirms:
result = await gate.confirm("req-1")
```

## Testing

```bash
python -m pytest orchestrator/tests/ -v
```

## Adding a New Workspace

Create a `CLAUDE.md` + `.claude/` directory inside the workspace folder — that is all.
The PO auto-discovers it via `ls` and reading CLAUDE.md.

## Cleaning Up Legacy .tasks/

After migration is complete:
```bash
# Dry run first (prints targets without deleting)
bash orchestrator/scripts/cleanup.sh /home1/irteam/naver/project/.tasks

# Delete after verifying
bash orchestrator/scripts/cleanup.sh /home1/irteam/naver/project/.tasks --execute
```
