# Claude-Code-Tunnels Channel Setup Guide

How to connect Slack and Telegram channels to the orchestrator.

---

## Common Prerequisites

### 1. Install Dependencies

```bash
pip install claude-agent-sdk aiohttp pyyaml
```

### 2. Configure orchestrator.yaml

Place in the project root (parent directory of orchestrator/).

```yaml
root: /path/to/your/projects
archive: /path/to/your/projects/ARCHIVE

channels:
  slack:
    enabled: false
  telegram:
    enabled: false

remote_workspaces: []
```

### 3. Credential Directory Structure

```
ARCHIVE/
├── slack/
│   └── credentials
└── telegram/
    └── credentials
```

All credential files use `key : value` format (one space on each side of the colon):

```
key1 : value1
key2 : value2
```

---

## Slack Channel Setup

### Step 1: Create a Slack App

1. Go to https://api.slack.com/apps
2. **Create New App** → **From scratch**
3. Choose an app name and workspace, then create

### Step 2: Enable Socket Mode

Socket Mode uses WebSocket, so no public URL is needed.

1. Left menu **Settings → Socket Mode** → toggle **Enable Socket Mode** ON
2. Generate an App-Level Token:
   - Token Name: `orchestrator` (any name)
   - Scope: add `connections:write`
   - Click **Generate**
   - Copy the generated `xapp-1-...` token → use as `app_level_token`

### Step 3: Bot Token Scopes (OAuth & Permissions)

Left menu **Features → OAuth & Permissions** → **Scopes → Bot Token Scopes**, add:

| Scope | Purpose |
|-------|---------|
| `chat:write` | Send messages |
| `channels:history` | Read channel messages |
| `groups:history` | Read private channel messages |
| `im:history` | Read DM messages |
| `mpim:history` | Read group DM messages |
| `app_mentions:read` | Receive @mention events |

### Step 4: Event Subscriptions

1. Left menu **Features → Event Subscriptions** → toggle **Enable Events** ON
2. Under **Subscribe to bot events**, add:
   - `message.channels` — public channel messages
   - `message.groups` — private channel messages
   - `message.im` — DM messages
   - `app_mention` — @mentions

### Step 5: Install to Workspace

1. Left menu **Settings → Install App** → **Install to Workspace**
2. Approve permissions
3. Copy the **Bot User OAuth Token** (`xoxb-...`)

### Step 6: Write Credential File

`ARCHIVE/slack/credentials`:

```
app_id : A0XXXXXXXXX
client_id : 1234567890.9876543210
client_secret : your-client-secret
signing_secret : your-signing-secret
app_level_token : xapp-1-XXXXXXXXXXX
bot_token : xoxb-XXXXXXXXXXX
```

Where to find each value:
- `app_id`: Settings → Basic Information → App ID
- `client_id`, `client_secret`: Settings → Basic Information → App Credentials
- `signing_secret`: Settings → Basic Information → App Credentials → Signing Secret
- `app_level_token`: Settings → Basic Information → App-Level Tokens
- `bot_token`: Features → OAuth & Permissions → Bot User OAuth Token

### Step 7: User Allowlist

Add allowed Slack User IDs to the `ALLOWED_USERS` set in `orchestrator/channel/slack.py`:

```python
ALLOWED_USERS: set[str] = {
    "U04K5QVP03Z",  # example user
    # ... add more
}
```

**How to find User ID:**
1. Click a user's profile in Slack → **⋮ More** → **Copy member ID**
2. Or use the Slack API: `https://api.slack.com/methods/users.list/test`

**Set to empty `set()` to allow all users** (for testing environments).

### Step 8: Invite Bot to Channel

The bot must be a member of the channel to receive messages:

```
/invite @botname
```

Or add via Channel Settings → Integrations → Apps.

### Step 9: Enable

In `orchestrator.yaml`:

```yaml
channels:
  slack:
    enabled: true
```

### Verify

```bash
python -m orchestrator.main
```

If you see `Slack channel starting (Socket Mode)...` in the logs, it is working.
Send the bot a DM or @mention it in a channel to test.

---

## Telegram Channel Setup

### Step 1: Create a Bot with BotFather

1. Open [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token** (`123456:ABC-DEF...`)

### Step 2: Write Credential File

`ARCHIVE/telegram/credentials`:

```
bot_token : 123456789:ABCdefGHIjklMNOpqrsTUVwxyz
allowed_users : username1, username2
```

- `bot_token`: Token issued by BotFather
- `allowed_users`: Comma-separated list of allowed Telegram usernames. Leave empty to allow all users.

### Step 3: Enable

```yaml
channels:
  telegram:
    enabled: true
```

### Verify

When you see `Telegram channel starting (bot: @botname)...` in the logs, it is working.
Send a message to the bot on Telegram to test.

---

## Running the Orchestrator

### Direct

```bash
python -m orchestrator.main
```

### Background

```bash
nohup python -m orchestrator.main > /tmp/orchestrator.log 2>&1 &
```

Or use `start-orchestrator.sh`:

```bash
./start-orchestrator.sh        # background
./start-orchestrator.sh --fg   # foreground
```

### Stop

```bash
kill $(pgrep -f "orchestrator.main")
```

---

## User Interaction Flow

### Session State Machine

```
IDLE → (message received) → PENDING_CONFIRM
  → "confirm" → EXECUTING (plan)
    → read-only / direct answer → AWAITING_FOLLOWUP
    → modification plan → PENDING_EXECUTION_CONFIRM
      → "confirm" → EXECUTING (run) → AWAITING_FOLLOWUP
      → "cancel" → IDLE
  → "cancel" → IDLE
AWAITING_FOLLOWUP
  → "yes"/"done" → session end (IDLE)
  → other message → treated as follow-up request (context retained)
```

### Confirm / Cancel Keywords

| Action | Keywords |
|--------|---------|
| Confirm | `확인`, `진행`, `yes`, `y`, `ok`, `ㅇㅇ`, `네`, `ㄱㄱ`, `ㄱ` |
| Cancel | `취소`, `cancel`, `no`, `n`, `아니`, `ㄴㄴ`, `ㄴ` |
| End session | `네`, `ㅇㅇ`, `yes`, `y`, `ok`, `끝`, `done`, `됐어`, `응`, `ㅇ`, `확인` |

### Two-step Confirm Flow (Code Modification Tasks)

1. **First confirm**: "Is this what you meant?" → user "confirm"
2. **Plan**: Router → PO generates execution plan
3. **Second confirm**: Show execution plan → user "confirm" (only for workspace modification tasks)
4. **Execute**: Executor runs workspaces phase-by-phase in parallel/sequential order
5. **Complete**: Format results and send back to channel

Read-only requests like queries skip the second confirmation and return results directly.

---

## Adding New Projects / Workspaces

1. Create a folder in the project root
2. Write a `CLAUDE.md` inside (role, build commands, test method, etc.)
3. Done — PO auto-discovers via `ls` + reading CLAUDE.md

### Workspace Structure Example

```
my-project/
├── CLAUDE.md              # project overview
├── frontend/
│   ├── CLAUDE.md          # frontend build/test guide
│   └── src/
├── backend/
│   ├── CLAUDE.md          # backend API guide
│   └── src/
└── database/
    ├── CLAUDE.md          # migration guide
    └── migrations/
```

---

## Add a Custom Channel

Inherit from `BaseChannel` and implement just three methods: `_send`, `start`, `stop`.

```python
from orchestrator.channel.base import BaseChannel

class MyChannel(BaseChannel):
    channel_name = "mychannel"

    async def _send(self, callback_info, text):
        # message send logic
        ...

    async def start(self):
        # start receiving messages
        ...

    async def stop(self):
        # cleanup
        ...
```

Register in `main.py`:

```python
if channels_config.get("mychannel", {}).get("enabled"):
    my_ch = MyChannel(confirm_gate)
    register_channel("mychannel", my_ch)
    tasks.append(asyncio.create_task(my_ch.start()))
```

---

## Testing

```bash
python -m pytest orchestrator/tests/ -v
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Slack not connecting | Socket Mode disabled | Toggle Socket Mode ON in Slack App settings |
| Slack messages ignored | User not in `ALLOWED_USERS` | Add User ID or set to empty set |
| Telegram no response | Bad Bot Token | Re-issue token from BotFather |
| JSON parse failure | Agent response format error | Haiku repair pass attempts auto-recovery |
