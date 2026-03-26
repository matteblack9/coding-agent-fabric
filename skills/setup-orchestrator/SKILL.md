---
name: setup-orchestrator
description: "Bootstrap the Project Orchestrator and launch the setup TUI. Execute with /claude-code-tunnels:setup-orchestrator."
---

# Setup Orchestrator

Use this skill when the user wants to install or reconfigure the Project Orchestrator.

## Workflow

1. Run `./install.sh` from the plugin root if `.venv/` or Node dependencies are missing.
2. Launch the setup TUI with `.venv/bin/python -m orchestrator.setup_tui`.
3. Let the TUI decide whether the current folder looks like:
   - an existing `PO` root
   - a new `PO` candidate
   - a single `Workspace`
4. In the TUI, confirm or edit:
   - `PO root`
   - `ARCHIVE` path
   - channel enablement
   - default runtime and executor runtime
   - workspace to WO mappings
5. After the TUI writes `orchestrator.yaml`, follow the final instructions it prints:
   - `./start-orchestrator.sh --fg`
   - `./start-orchestrator.sh`

## Notes

- The TUI generates `orchestrator.yaml`, `start-orchestrator.sh`, `CLAUDE.md`, and `AGENTS.md` when missing.
- `claude` remains the default runtime.
- `codex` and `opencode` require working Node.js dependencies and local credentials/provider setup.
