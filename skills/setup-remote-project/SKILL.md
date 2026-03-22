---
name: setup-remote-project
description: "Deploy a listener on a remote machine (SSH/kubectl) so the Orchestrator can use that machine's project as a workspace. Run with /setup-remote-project. Use for requests like 'connect remote project', 'setup remote project', 'connect SSH project'."
---

# Setup Remote Project

Deploys a listener on a remote machine (SSH) or Kubernetes Pod so the Orchestrator can use the remote environment's project as a workspace.

## How It Works

1. Deploy a lightweight HTTP listener (`listener.py`) on the remote machine
2. The listener receives tasks from the Orchestrator over HTTP
3. The listener runs `claude-agent-sdk query(cwd=workspace/)` locally
4. Results are returned as JSON

## Flow

### Step 1: Connection Method

Ask the user:
- SSH: host, user, (optional) SSH key path
- kubectl: pod name, namespace, (optional) kubeconfig path, (optional) container name

### Step 2: Remote Workspace Info

```
remote_cwd: /path/to/project/on/remote/host
listener_port: 9100 (default)
workspace_name: project-name/workspace-name (how it appears in orchestrator)
```

### Step 3: Deploy Listener

#### Via SSH
```bash
# The deploy script handles:
# 1. Copy listener.py to remote host
# 2. Start listener with nohup
# 3. Verify health check

python3 -c "
from orchestrator.remote.deploy import deploy_via_ssh
deploy_via_ssh(
    host='HOST',
    remote_cwd='REMOTE_CWD',
    port=PORT,
    user='USER',
    key_file='KEY_FILE',
)
"
```

#### Via kubectl
```bash
python3 -c "
from orchestrator.remote.deploy import deploy_via_kubectl
deploy_via_kubectl(
    pod='POD_NAME',
    namespace='NAMESPACE',
    remote_cwd='REMOTE_CWD',
    port=PORT,
    kubeconfig='KUBECONFIG_PATH',
)
"
```

### Step 4: Register in Config

Add to `orchestrator.yaml`:
```yaml
remote_workspaces:
  - name: project/workspace
    host: remote-host-or-pod-ip
    port: 9100
    token: ""
```

### Step 5: Test

```bash
curl http://HOST:PORT/health
```

Should return: `{"status": "ok", "cwd": "/path/to/workspace", "port": 9100}`

## Prerequisites on Remote Host

- Python 3.10+
- claude-agent-sdk installed (`pip install claude-agent-sdk`)
- aiohttp installed (`pip install aiohttp`)
- Claude Code CLI available in PATH

## Rules

- listener.py requires claude-agent-sdk on the remote host
- If SSH key auth fails, suggest password auth or key setup
- Always test health check after deployment
- Port must be accessible from the orchestrator host
