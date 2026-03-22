---
name: setup-orchestrator
description: "Full Claude-Code-Tunnels setup. Installs the Project Orchestrator in the current directory, configures environment, discovers workspaces, connects Slack/Telegram channels, and tests the connection. Run with /setup-orchestrator. Use for requests like 'install orchestrator', 'setup PO', 'setup orchestrator'."
---

# Claude-Code-Tunnels Setup

Installs Claude-Code-Tunnels (Project Orchestrator) into the user's project directory.

## Source Code

Find the plugin installation directory and use it as SOURCE_DIR:

```bash
SOURCE_DIR=$(find ~/.claude/plugins/cache -maxdepth 3 -name "marketplace.json" 2>/dev/null \
  | xargs grep -l "claude-tunnels" 2>/dev/null \
  | head -1 | xargs dirname | xargs dirname)
```

If the above returns empty, try:
```bash
SOURCE_DIR=$(find ~/.claude/plugins/cache -maxdepth 3 -type d -name "claude-tunnels" 2>/dev/null | head -1)
```

Copy `orchestrator/` from SOURCE_DIR after setting it.

## Setup Flow

### Phase 1: Collect User Input

Ask the user for ALL of the following at once:

```
1. PROJECT_ROOT: Absolute path to the project root directory (required)
   - The directory containing your projects/workspaces
   - Example: /home/user/my-projects

2. ARCHIVE_PATH: Credential storage directory (default: PROJECT_ROOT/ARCHIVE)

3. Channels to enable: slack / telegram / multiple (required — must ask)
```

If `$ARGUMENTS` provides PROJECT_ROOT, use it without asking.

### Phase 2: Copy Orchestrator Code

Resolve SOURCE_DIR first (see above), then run:

```bash
# Copy orchestrator package
cp -r SOURCE_DIR/orchestrator/ PROJECT_ROOT/orchestrator/

# Copy rules
mkdir -p PROJECT_ROOT/.claude/rules/
cp SOURCE_DIR/templates/rules/*.md PROJECT_ROOT/.claude/rules/

# Copy start script
cp SOURCE_DIR/templates/start-orchestrator.sh.template PROJECT_ROOT/start-orchestrator.sh
chmod +x PROJECT_ROOT/start-orchestrator.sh
```

### Phase 3: Generate orchestrator.yaml

Create `PROJECT_ROOT/orchestrator.yaml` with the collected settings:

```yaml
root: PROJECT_ROOT
archive: ARCHIVE_PATH
channels:
  slack:
    enabled: true/false
  telegram:
    enabled: true/false
remote_workspaces: []
```

### Phase 4: Setup CLAUDE.md

- If PROJECT_ROOT/CLAUDE.md doesn't exist → create from template
- If it exists but has no "Orchestrator" mention → append orchestrator section
- If it already mentions Orchestrator → skip

### Phase 5: Discover Workspaces

1. `ls PROJECT_ROOT/` — list subdirectories
2. Exclude: orchestrator/, ARCHIVE/, .tasks/, .claude/, .git/, hidden dirs
3. Show workspace candidates to user for confirmation
4. If no workspaces found → ask user

For each confirmed workspace:
- If CLAUDE.md doesn't exist → create basic one with orchestrator integration section
- If CLAUDE.md exists but no "Orchestrator Integration" → append the section
- Don't touch existing .claude/ directories

### Phase 6: Channel Setup

#### Slack
1. Check if ARCHIVE_PATH/slack/credentials exists
2. If not → show Slack App creation guide:
   - Create app at https://api.slack.com/apps
   - Enable Socket Mode
   - Add events: message.channels, app_mention
   - Bot scopes: chat:write, channels:history, app_mentions:read
   - Install to workspace
3. Collect: app_id, client_id, client_secret, signing_secret, app_level_token, bot_token
4. Create credential file

#### Telegram
1. Check if ARCHIVE_PATH/telegram/credentials exists
2. If not → show BotFather guide:
   - Open @BotFather on Telegram
   - Send /newbot, follow prompts
   - Copy the bot token
3. Collect: bot_token, optionally allowed_users (comma-separated)
4. Create credential file

Auto-install dependencies:
```bash
pip install claude-agent-sdk aiohttp pyyaml
pip install slack-bolt slack-sdk        # if Slack
# Telegram uses aiohttp (already installed)
```

### Phase 7: Test & Finish

Start orchestrator and test:
```bash
cd PROJECT_ROOT && ./start-orchestrator.sh --fg &
sleep 3
# Slack: check logs for "Socket Mode" connection
# Telegram: check logs for bot username
```

Show final summary with created files tree and next steps.

## Rules

- Preserve original code logic. Only change paths/config.
- Preserve existing CLAUDE.md content. Only append.
- Never commit ARCHIVE/. Ensure .gitignore has it.
- Always confirm with user before proceeding.
- If location unclear, ask user.
