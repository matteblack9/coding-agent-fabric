---
name: setup-remote-workspace
description: "Connect a specific workspace on a remote machine to the Orchestrator. Similar to setup-remote-project but scoped to a single workspace. Run with /setup-remote-workspace. Use for requests like 'connect remote workspace', 'setup remote workspace'."
---

# Setup Remote Workspace

Connects a single specific workspace on a remote machine to the Orchestrator.

## Difference from /setup-remote-project

- `/setup-remote-project`: connects an entire project remotely (including all its workspaces)
- `/setup-remote-workspace`: connects only one specific workspace remotely

## Flow

### Step 1: Identify Target

Ask the user:
```
1. Which project does this workspace belong to?
2. Workspace name (as it will appear in execution plans)
3. Connection method: ssh / kubectl
```

### Step 2: Connection Details

Same as /setup-remote-project:
- SSH: host, user, key path
- kubectl: pod, namespace, kubeconfig, container

### Step 3: Remote Workspace Path

```
remote_cwd: /absolute/path/to/workspace/on/remote
listener_port: 9100 (or next available)
```

### Step 4: Deploy & Register

1. Deploy listener.py to remote host
2. Add entry to orchestrator.yaml remote_workspaces
3. Test health check

### Step 5: Verify Integration

The workspace should now be callable by the orchestrator. When the PO includes this workspace in an execution plan, the executor will call the remote listener instead of local `query(cwd=)`.

## Rules

- One listener per workspace (each on a different port if on the same host)
- Remote workspace must have CLAUDE.md for the PO to understand it
- Ensure the remote listener stays running (consider systemd/supervisord)
