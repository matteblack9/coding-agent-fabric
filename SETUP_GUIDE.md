# claude-code-tunnels Setup Guide

This guide covers the current setup flow:

```bash
./install.sh
.venv/bin/python -m orchestrator.setup_tui
./start-orchestrator.sh --fg
```

## What the Setup TUI Does

The setup TUI is the primary installer now. It:

1. Checks whether the current folder already looks like a `PO` root
2. Suggests a `PO root`, `ARCHIVE` path, and workspace candidates
3. Creates a `WO` for each selected workspace
4. Lets you choose runtime defaults and channel enablement
5. Writes `orchestrator.yaml`, `start-orchestrator.sh`, `CLAUDE.md`, and `AGENTS.md` when needed
6. Shows the exact commands to run in foreground or background

## Folder Heuristics

The TUI classifies the current folder into one of four modes:

- `existing_po`: the folder already contains at least two PO markers such as `orchestrator.yaml`, `orchestrator/`, `start-orchestrator.sh`, `ARCHIVE/`, or `.tasks/`
- `new_po_candidate`: the folder has multiple visible child directories and weak code-root markers
- `workspace_candidate`: the folder looks like a single codebase because it contains markers such as `.git`, `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, or `requirements.txt`
- `unknown`: neither side is strongly implied, so the TUI proposes `cwd` and `parent` as candidates

If the current folder looks like a PO root, the TUI automatically proposes:

- `PO root = cwd`
- `ARCHIVE = <cwd>/ARCHIVE`
- workspace candidates from immediate child directories excluding `orchestrator`, `ARCHIVE`, `.tasks`, `.claude`, `.git`, and hidden directories

## Runtime Model

The control plane stays in Python. Workspace execution can use:

- `claude`: Python `claude-agent-sdk`
- `codex`: Node bridge with `@openai/codex-sdk`
- `opencode`: Node bridge with `@opencode-ai/sdk`

Default runtime behavior:

- `router = claude`
- `planner = claude`
- `executor = claude` unless changed in the TUI
- `direct_handler = claude`
- `repair = claude`

Each workspace gets a `WO` entry:

```yaml
workspaces:
  - id: backend
    path: backend
    wo:
      runtime: codex
      mode: local
```

Remote example:

```yaml
workspaces:
  - id: staging
    path: services/staging
    wo:
      runtime: opencode
      mode: remote
      remote:
        host: 10.0.0.5
        port: 9100
        token: ""
```

## Slack Setup

1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable Socket Mode and generate an app-level token with `connections:write`
3. Add bot scopes:
   - `chat:write`
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
   - `app_mentions:read`
4. Enable event subscriptions for:
   - `message.channels`
   - `message.groups`
   - `message.im`
   - `app_mention`
5. Install the app to the target workspace
6. Save credentials under `ARCHIVE/slack/credentials`

Credential file format:

```text
app_id : A0XXXXXXXXX
client_id : 1234567890.9876543210
client_secret : your-client-secret
signing_secret : your-signing-secret
app_level_token : xapp-1-XXXXXXXXXXX
bot_token : xoxb-XXXXXXXXXXX
```

Then enable Slack in the TUI or in `orchestrator.yaml`:

```yaml
channels:
  slack:
    enabled: true
```

## Telegram Setup

1. Create a bot with [@BotFather](https://t.me/botfather)
2. Save credentials under `ARCHIVE/telegram/credentials`

Credential file format:

```text
bot_token : 123456789:ABCdefGHIjklMNOpqrsTUVwxyz
allowed_users : username1, username2
```

Then enable Telegram in the TUI or in `orchestrator.yaml`:

```yaml
channels:
  telegram:
    enabled: true
```

## Running

Foreground:

```bash
./start-orchestrator.sh --fg
```

Background:

```bash
./start-orchestrator.sh
```

Reconfigure:

```bash
.venv/bin/python -m orchestrator.setup_tui
```

## Remote Listener

The remote listener accepts:

- `LISTENER_CWD`
- `LISTENER_PORT`
- `LISTENER_TOKEN`
- `LISTENER_RUNTIME`

Health endpoint:

```bash
curl http://host:9100/health
```

Execute endpoint:

```bash
curl -X POST http://host:9100/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"task":"deploy staging","runtime":"codex","upstream_context":{}}'
```

## Verification Checklist

- `.venv/bin/python -m pytest orchestrator/tests -q`
- `node --test`
- `codex login status`
- `opencode providers list`
- `./start-orchestrator.sh --fg`
