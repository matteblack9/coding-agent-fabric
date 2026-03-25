---
name: connect-slack
description: "Skill for connecting a Slack channel to the Claude-Code-Tunnels Orchestrator. Guides Slack App creation, configures Socket Mode, collects credentials, and verifies the connection. Execute with /claude-code-tunnels:connect-slack."
---

# Connect Slack Channel

Adds a Slack channel to an existing Claude-Code-Tunnels Orchestrator.
Connects via Socket Mode (WebSocket), so no public IP or callback URL is required.

## Rules

- **Never proceed without asking the user**
- **Auto-detected values are presented as numbered choices first** — the user only needs to enter a number
- If an existing credentials file is found, always confirm with the user before overwriting
- Credential files use the `key : value` format (spaces on both sides of the colon)
- The ARCHIVE/ directory must not be committed to git

---

## Step 0: Environment Preflight (CRITICAL)

Connecting Slack requires the orchestrator to be installed, pip packages present, and a credentials file.
Check each item in order — **if any check fails, do not proceed to the next step until it is resolved.**

### 0-1. Verify orchestrator.yaml

**Why it is needed**: the Slack adapter reads channel activation status and the ARCHIVE path from orchestrator.yaml. Without this file, adapter initialization will fail.

```bash
if [ ! -f "orchestrator.yaml" ]; then
  echo "orchestrator.yaml not found."
  echo "Please run /claude-code-tunnels:setup-orchestrator first."
  # -> stop here
fi
```

### 0-2. Verify ARCHIVE_PATH

**Why it is needed**: Slack credentials (app_id, bot_token, etc.) are stored in `ARCHIVE/slack/credentials`.

```bash
ARCHIVE_PATH=$(python3 -c "import yaml; print(yaml.safe_load(open('orchestrator.yaml')).get('archive', 'ARCHIVE'))")
```

```
Confirming credential storage path.

  [1] $ARCHIVE_PATH   <- value read from orchestrator.yaml
  [2] Enter manually

Number:
```

### 0-3. Verify pip + packages

**Why they are needed**: `slack-bolt` (Socket Mode handler) and `slack-sdk` (Web API client) are required. Without them, `from slack_bolt import ...` will raise an ImportError.

```bash
$PYTHON_CMD -c "import slack_bolt" 2>/dev/null  # slack-bolt
$PYTHON_CMD -c "import slack_sdk" 2>/dev/null   # slack-sdk
```

If not installed:
```
The following packages required for Slack connection are not installed:
  - slack-bolt  (Socket Mode connection and event handling)
  - slack-sdk   (Slack Web API calls — message sending)

  [1] Install now ($PIP_CMD install slack-bolt slack-sdk)
  [2] Skip (install manually and continue)

Number:
```

### 0-4. Check for existing credentials

**Why it is needed**: if Slack is already configured, the user must decide whether to overwrite the existing setup.

```bash
if [ -f "$ARCHIVE_PATH/slack/credentials" ]; then
  echo "Existing credentials found"
fi
```

If an existing file is found:
```
Existing Slack credentials already exist:
  app_id:           A0123...
  bot_token:        xoxb-...

  [1] Overwrite (enter new values)
  [2] Keep existing values (update configuration only)
  [3] Cancel

Number:
```

---

## Step 1: Slack App Setup Guide

If no Slack App exists yet, provide guidance:

```
Slack App Setup:
1. https://api.slack.com/apps → Create New App → "From scratch"
2. Set a name and select your workspace
3. Settings → Socket Mode → Enable Socket Mode
   - Generate an App-level token (xapp-...) — connections:write scope
4. Event Subscriptions → Enable Events
   - Subscribe: message.channels, app_mention
5. OAuth & Permissions → Bot Token Scopes:
   - chat:write, channels:history, app_mentions:read
6. Install App to Workspace
7. Copy the Bot Token (xoxb-...)

Are you ready? (yes — start entering credentials / no — show detailed guide)
```

---

## Step 2: Collect Credentials (6 fields)

**Ask the user for each field one at a time. Empty values are not accepted.**

Accompany each field prompt with **a one-line explanation of why it is needed**:

```
─────────────────────────────────────────────────────────────────
1. app_id
   Shown on the Basic Information page of your Slack App settings.
   Format: starts with A (e.g. A0123456789)
   Enter:

2. client_id
   Shown under Basic Information → App Credentials.
   Format: number.number (e.g. 1234567890.1234567890)
   Enter:

3. client_secret
   Shown in the same App Credentials section. Click Show to copy it.
   Enter:

4. signing_secret
   Same App Credentials section. Used to verify the integrity of incoming bot requests.
   Enter:

5. app_level_token
   Generate under Settings → Basic Information → App-Level Tokens.
   Used for authentication when establishing the Socket Mode connection.
   Format: starts with xapp-
   Validation: if it does not start with xapp- → "Invalid format. Please enter the full token starting with xapp-."
   Enter:

6. bot_token
   Found under OAuth & Permissions → Bot User OAuth Token.
   Used to send messages (chat_postMessage).
   Format: starts with xoxb-
   Validation: if it does not start with xoxb- → "Invalid format."
   Enter:
─────────────────────────────────────────────────────────────────
```

Summary after collection:
```
Slack Credentials entered:
  app_id:           A0123456789
  client_id:        1234567890.1234567890
  client_secret:    ****
  signing_secret:   ****
  app_level_token:  xapp-1-...
  bot_token:        xoxb-...

Save with these values? (yes/no)
```

---

## Step 3: Save Configuration

After user confirmation:

```bash
mkdir -p $ARCHIVE_PATH/slack/

cat > $ARCHIVE_PATH/slack/credentials << 'EOF'
app_id : $APP_ID
client_id : $CLIENT_ID
client_secret : $CLIENT_SECRET
signing_secret : $SIGNING_SECRET
app_level_token : $APP_LEVEL_TOKEN
bot_token : $BOT_TOKEN
EOF
```

Update orchestrator.yaml:
```yaml
channels:
  slack:
    enabled: true
```

---

## Step 4: Connection Test

```bash
cd $PROJECT_ROOT && ./start-orchestrator.sh --fg &
sleep 5
# Confirm "Slack channel starting (Socket Mode)..." in the logs
```

- Success → "Slack connection complete. Send a message to the bot in Slack to test it."
- Failure → show the error log to the user and analyze the cause. Do not retry automatically.

## Credential File Format

```
app_id : A0123456789
client_id : 1234567890.1234567890
client_secret : abcdef1234567890
signing_secret : abcdef1234567890
app_level_token : xapp-1-A0123-1234567890-abcdef
bot_token : xoxb-1234567890-1234567890-abcdef
```
