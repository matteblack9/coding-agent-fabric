# Delegation Rule (CRITICAL)

All work is executed through the `orchestrator/` package. PO creates execution plans via `query(cwd=project/)`, and the executor runs workspace tasks via `query(cwd=workspace/)`. Runtime guidance may come from `AGENTS.md`, `CLAUDE.md`, `.claude/*`, or `opencode.json` depending on the selected runtime.

## Discovery

Discover available projects by running `ls`. Read each project's `AGENTS.md`, `CLAUDE.md`, and `opencode.json` when present to understand it. No hardcoded project lists.

## Decision Tree

1. Specific project task → PO determines phases, executor runs workspaces
2. Cross-project task → Each project runs in parallel via `asyncio.gather`
3. Project structure question → PO investigates with Read/Glob/Grep
4. Ambiguous project → Ask user for clarification
