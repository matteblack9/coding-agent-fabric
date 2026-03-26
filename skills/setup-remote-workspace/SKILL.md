---
name: setup-remote-workspace
description: "Skill for connecting a single workspace on a remote machine to the Orchestrator. Similar to setup-remote-project but operates at the individual workspace level. Execute with /claude-code-tunnels:setup-remote-workspace."
---

# Setup Remote Workspace

Connects a single workspace on a remote machine to the Orchestrator.
Uses the same listener as `/claude-code-tunnels:setup-remote-project`, but registers at the individual workspace level.

## Difference from setup-remote-project

| | setup-remote-project | setup-remote-workspace |
|---|---|---|
| Target | Entire project (including sub-workspaces) | A single specific workspace |
| Registration | PO discovers the project structure | Workspace is specified and registered directly |
| When to use | Moving an entire project to a remote machine | Adding a remote workspace to an existing project |

## Rules

- **Never proceed without asking the user**
- **Auto-detected values are presented as numbered choices first** — the user only needs to enter a number
- One listener per workspace (same host → use a different port)
- The remote workspace should expose guidance the PO can inspect: `AGENTS.md` for Cursor/Codex/OpenCode, `.cursor/rules` or `.cursorrules` for Cursor, `CLAUDE.md` or `.claude/` for Claude, and `opencode.json`/`.opencode/` when OpenCode-specific config is needed

---

## Step 0: Environment Preflight (CRITICAL)

Connecting a single workspace to a remote listener requires the orchestrator to be installed and an access method to be available.
**If any check fails, do not proceed to the next step until it is resolved.**

### 0-1. Verify orchestrator.yaml

**Why it is needed**: a new workspace must be added to the remote_workspaces array.

- Not found → "Please run /claude-code-tunnels:setup-orchestrator first." then **stop**

### 0-2. Verify orchestrator/remote/

**Why it is needed**: deploy.py and listener.py must be present for remote deployment.

### 0-3. Check existing remote_workspaces

**Why it is needed**: prevents duplicate registration on the same host:port, and allows recommending a port that does not conflict with existing ones.

```
Currently registered remote workspaces:
  my-project/backend  → 10.0.0.5:9100
  my-project/frontend → 10.0.0.5:9101

Adding a new workspace.
```

### 0-4. Verify access tools

Auto-detect available tools:

```
Select the remote access method.

  [1] ssh       <- detected
  [2] kubectl   <- detected

Number:
```

---

## Step 1: Identify Target

### 1-1. project

Auto-detect local project directories and present as choices:

```bash
# List directories under the root in orchestrator.yaml
root=$(python3 -c "import yaml; print(yaml.safe_load(open('orchestrator.yaml')).get('root','.'))")
ls "$root"  # exclude: orchestrator, ARCHIVE, .tasks, .claude, .cursor, .opencode, .git, hidden folders
```

```
Select the project this workspace belongs to.
A project directory with the same name must exist locally for the PO to recognize it.

  [1] my-project
  [2] another-project
  [3] Enter manually

Number:
```

### 1-2. workspace

```
Enter the workspace name.
This name will appear in the execution plan.
It will be registered in orchestrator.yaml as "$PROJECT/$WORKSPACE".

Enter (e.g. data-pipeline):
```

### Preview

```
Name to be registered: my-project/data-pipeline

Is this correct? (yes/no)
```

---

## Step 2: Collect Connection Details

### If SSH is selected

```
─────────────────────────────────────────────────────────────────
1. host (required)
   The remote machine to connect to via HTTP for the listener.
   Enter:

2. user
     [1] $USER   <- current user
     [2] Enter manually
   Number:

3. key_file
     [1] ~/.ssh/id_rsa       <- exists
     [2] ~/.ssh/id_ed25519   <- exists
     [3] Use default key
     [4] Enter manually
   Number:
─────────────────────────────────────────────────────────────────
```

SSH key candidates auto-detected by scanning `~/.ssh/`.
After input, **immediately run a connection test**: `ssh $USER@$HOST "echo OK"`

### If kubectl is selected

Present auto-detected choices in the order: namespace → pod → container (same as setup-remote-project).

---

## Step 3: Remote Workspace Path

```
Enter the absolute path where the workspace is located on the remote machine.

Enter (e.g. /home/user/my-project/data-pipeline):
```

Validation: verify existence on the remote machine with `test -d`.

Listener port — auto-calculate candidates that do not conflict with already-registered ports:

```bash
# Check already-used ports
used_ports=(9100 9101)  # ports for the same host in orchestrator.yaml
next_port=9102          # next available port
```

```
Select the listener port.
Ports 9100 and 9101 are already registered for the same host (10.0.0.5).

  [1] 9102   <- next in sequence, available
  [2] 9103   <- available
  [3] Enter manually

Number:
```

Auth token:
```
  [1] No authentication
  [2] Enter a token

Number:
```

---

## Step 4: Remote Environment Pre-check (CRITICAL)

**Why it is needed**: the listener uses Python + aiohttp on the remote machine, plus runtime-specific executors such as `claude-agent-sdk` for Claude or `cursor-agent` / `codex` / `opencode` CLIs for the other runtimes.

```
Remote environment check results:
  Python:            3.11.5            ✓
  claude-agent-sdk:  0.3.0             ✓
  aiohttp:           3.9.1             ✓

  [1] Continue
  — or if any items are missing —
  [1] Install on remote now
  [2] Install manually and continue

Number:
```

---

## Step 5: Deploy & Register

Deployment summary:
```
Deployment summary:
  workspace:  my-project/data-pipeline
  Target:     irteam@10.0.0.5
  Path:       /home/user/my-project/data-pipeline
  Port:       9102
  Token:      (none)

Proceed? (yes/no)
```

After confirmation, deploy + update orchestrator.yaml:
```yaml
remote_workspaces:
  - name: my-project/backend
    host: 10.0.0.5
    port: 9100
  - name: my-project/frontend
    host: 10.0.0.5
    port: 9101
  - name: my-project/data-pipeline    # <- newly added
    host: 10.0.0.5
    port: 9102
    token: ""
```

---

## Step 6: Validation

```bash
curl http://$HOST:$LISTENER_PORT/health
# Expected: {"status": "ok", "cwd": "...", "port": 9102}
```

- Success → "Remote workspace connection complete. When the PO includes this workspace in the execution plan, tasks will run remotely automatically."
- Failure → show the error details and analyze the cause. Do not retry automatically.

## Viewing Logs

```bash
ssh $USER@$HOST cat /tmp/claude-listener-$LISTENER_PORT.log
kubectl exec $POD -n $NAMESPACE -- cat /tmp/claude-listener-$LISTENER_PORT.log
```
