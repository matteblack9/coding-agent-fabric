---
name: setup-remote-project
description: "Deploys a listener to a remote machine (SSH/kubectl) so the Orchestrator can use that machine's project as a workspace. Execute with /claude-code-tunnels:setup-remote-project."
---

# Setup Remote Project

Deploys a lightweight HTTP listener to a remote machine (SSH) or Kubernetes Pod,
allowing the Orchestrator to use the remote environment's project as a workspace.

Key point: `claude-agent-sdk query(cwd=)` has no timeout. Because the listener calls the SDK directly on the remote machine,
tasks run without time limits, just as they would locally.

## Rules

- **Never proceed without asking the user**
- **Auto-detected values are presented as numbered choices first** — the user only needs to enter a number
- One listener per workspace (multiple workspaces on the same host → use different ports)
- The remote workspace must have a CLAUDE.md for the PO to understand it
- The listener must run continuously (nohup by default, systemd/supervisord recommended)

---

## Step 0: Environment Preflight (CRITICAL)

Connecting a remote project requires a local orchestrator installation and a means of accessing the remote machine (ssh/kubectl).
Check each item in order — **if any check fails, do not proceed to the next step until it is resolved.**

### 0-1. Verify orchestrator.yaml

**Why it is needed**: the remote_workspaces configuration must be registered in this file, and the executor reads remote host information from it.

- Not found → "Please run /claude-code-tunnels:setup-orchestrator first." then **stop**

### 0-2. Verify orchestrator/remote/

**Why it is needed**: `deploy.py` (the remote deployment script) and `listener.py` (the HTTP server to run on the remote machine) must be present for deployment.

```bash
if [ ! -f "orchestrator/remote/deploy.py" ] || [ ! -f "orchestrator/remote/listener.py" ]; then
  echo "orchestrator/remote/ files not found."
fi
```

### 0-3. Verify access tools

**Why they are needed**: ssh or kubectl is required to copy listener.py to the remote machine and execute it.

Auto-detect available tools:
```bash
tools=()
command -v ssh &>/dev/null && tools+=("ssh")
command -v kubectl &>/dev/null && tools+=("kubectl")
```

```
Select the remote access method.
Used to copy and run listener.py on the remote machine.

  [1] ssh       <- detected
  [2] kubectl   <- detected
  [3] Enter manually (different path to ssh/kubectl)

Number:
```

Zero candidates detected → "Could not find ssh or kubectl. Please install one and try again."

### 0-4. Check existing remote_workspaces

**Why it is needed**: display the current registration state to prevent duplicate registration on the same host:port.

```
Currently registered remote workspaces:
  (none)
  — or —
  my-project/backend → 10.0.0.5:9100
  my-project/frontend → 10.0.0.5:9101
```

---

## Step 1: Collect Connection Details

### 1-1. workspace_name

```
What name should the Orchestrator use to identify this remote project?
This name will appear in the execution plan.
Format: project/workspace (e.g. my-project/backend)

Enter:
```

Validation: must contain `/` (project/workspace format).

### 1-2. Collect SSH Details

If the user selected ssh:

```
─────────────────────────────────────────────────────────────────
1. host (required)
   The IP address or hostname of the remote machine. Used to connect to the listener via HTTP.
   Enter:

2. user
   The SSH username.

     [1] $USER   <- current user
     [2] Enter manually

   Number:

3. key_file
   The SSH key file.

     [1] ~/.ssh/id_rsa     <- exists
     [2] ~/.ssh/id_ed25519 <- exists
     [3] Use default key (ssh-agent)
     [4] Enter manually

   Number:
─────────────────────────────────────────────────────────────────
```

SSH key candidates are auto-detected by scanning the `~/.ssh/` directory:
```bash
for f in ~/.ssh/id_rsa ~/.ssh/id_ed25519 ~/.ssh/id_ecdsa; do
  [ -f "$f" ] && echo "$f"
done
```

After input, **immediately run a connection test**:
```bash
ssh $USER@$HOST "echo 'SSH OK'"
```
- Failure → show the error and present re-entry choices

### 1-3. Collect kubectl Details

If the user selected kubectl:

Auto-detect available namespaces/pods and present as choices:

```bash
# namespace list
kubectl get namespaces -o jsonpath='{.items[*].metadata.name}' 2>/dev/null
```

```
Select a namespace.

  [1] default
  [2] my-namespace
  [3] production
  [4] Enter manually

Number:
```

Pod list after namespace selection:
```bash
kubectl get pods -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' 2>/dev/null
```

```
Select a Pod.

  [1] my-app-abc123
  [2] my-app-def456
  [3] Enter manually

Number:
```

Container (for multi-container pods):
```bash
kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.spec.containers[*].name}' 2>/dev/null
```

kubeconfig:
```
  [1] ~/.kube/config   <- default
  [2] Enter manually

Number:
```

Connection test: `kubectl exec $POD -n $NAMESPACE -- echo 'K8s OK'`

---

## Step 2: Remote Workspace Path

```
Enter the absolute path where the project is located on the remote machine.
The listener will run claude-agent-sdk query(cwd=) from this path.

Enter (e.g. /home/user/my-project):
```

Validation — verify the path exists on the remote machine:
```bash
ssh $USER@$HOST "test -d $REMOTE_CWD && echo OK || echo FAIL"
```

Listener port:
```bash
# Auto-detect available ports on the remote machine
for p in 9100 9101 9102; do
  ssh $USER@$HOST "ss -tlnp 2>/dev/null | grep -q ':${p} '" || available+=("$p")
done
```

```
Select the listener port.
The executor will send HTTP requests to this port.

  [1] 9100   <- available
  [2] 9101   <- available
  [3] Enter manually

Number:
```

Auth token:
```
Would you like to set up Bearer token authentication on the listener?
When configured, only the orchestrator will be able to access the listener.

  [1] No authentication (not needed on an internal network)
  [2] Enter a token

Number:
```

---

## Step 3: Remote Environment Pre-check (CRITICAL)

**Why it is needed**: the listener uses Python + claude-agent-sdk + aiohttp on the remote machine. If any of these is missing, execution will fail.

```bash
# Check remote Python
ssh $USER@$HOST "python3 --version"

# Check remote packages
ssh $USER@$HOST "python3 -c 'import claude_agent_sdk'" 2>/dev/null
ssh $USER@$HOST "python3 -c 'import aiohttp'" 2>/dev/null
```

```
Remote environment check results:
  Python:            3.11.5            ✓
  claude-agent-sdk:  OK                ✓
  aiohttp:           NOT INSTALLED     ✗

Some packages are not installed.

  [1] Install on remote now (run pip install via ssh)
  [2] Install manually and continue
  [3] Ignore and continue (errors may occur when the listener starts)

Number:
```

---

## Step 4: Deploy Listener

Show deployment summary and confirm:
```
Deployment summary:
  Target:     $USER@$HOST
  Path:       $REMOTE_CWD/.claude-listener.py
  Port:       $LISTENER_PORT
  Token:      (set / none)

listener.py will be copied to the remote machine and started.
Proceed? (yes/no)
```

Deployment steps:
1. Copy listener.py to the remote machine (`remote_cwd/.claude-listener.py`)
2. Kill any existing listener process
3. Start with nohup (log: `/tmp/claude-listener-{port}.log`)
4. Automatically run a health check (up to 6 attempts, 2 seconds apart)

---

## Step 5: Register in orchestrator.yaml & Validate

```yaml
remote_workspaces:
  - name: $WORKSPACE_NAME
    host: $HOST
    port: $LISTENER_PORT
    token: "$LISTENER_TOKEN"
```

Validation:
```bash
curl http://$HOST:$LISTENER_PORT/health
# Expected: {"status": "ok", "cwd": "$REMOTE_CWD", "port": $LISTENER_PORT}
```

- Success → "Remote project connection complete."
- Failure → show the error details and analyze the cause. Do not retry automatically.

## Listener API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Check status |
| `/execute` | POST | Execute a task. Body: `{"task": "...", "upstream_context": {}}` |

## Viewing Logs

```bash
ssh $USER@$HOST cat /tmp/claude-listener-$LISTENER_PORT.log
kubectl exec $POD -n $NAMESPACE -- cat /tmp/claude-listener-$LISTENER_PORT.log
```
