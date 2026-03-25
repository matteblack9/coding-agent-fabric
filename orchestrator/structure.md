# Orchestrator Structure Document

End-to-end flow from an incoming user message to a returned result, using Slack as the example channel.

---

## 1. Directory Structure

```
orchestrator/
├── main.py              # Entry point — starts all channels
├── server.py            # ConfirmGate + handle_request + send_to_channel
├── po.py                # PO Agent — builds the execution plan
├── executor.py          # Runs tasks per workspace
├── task_log.py          # Records task history under .tasks/
└── channel/
    ├── slack.py          # Slack adapter (Socket Mode)
    └── telegram.py       # Telegram adapter (Long Polling)
```

---

## 2. Startup (main.py)

Running `python3.11 -m orchestrator.main` starts all channels in a **single process**.

```python
# main.py — core

async def main() -> None:
    confirm_gate = ConfirmGate()          # pending-confirmation store

    slack_ch = SlackChannel(confirm_gate)  # Slack Socket Mode
    tg_ch = TelegramChannel(confirm_gate)  # Telegram Long Polling

    register_channel("slack", slack_ch)    # register in server.py registry
    register_channel("telegram", tg_ch)

    slack_task = asyncio.create_task(slack_ch.start())
    tg_task = asyncio.create_task(tg_ch.start())

    await stop_event.wait()                # wait until SIGINT/SIGTERM
```

After startup:
- Slack: WebSocket connection (Socket Mode, no open port)
- Telegram: Long Polling (no open port)

---

## 3. Slack Message Reception Flow (Full — Two-Step Confirmation)

```
User (Slack)
  │
  │  "Add a health check API to the new-place server"
  ▼
Slack server (api.slack.com)
  │
  │  Socket Mode WebSocket event
  │  Payload: { type: "message", text: "...", user: "...", channel: "..." }
  ▼
┌─────────────────────────────────────────────────────────────┐
│ [STEP 1] base.py — BaseChannel._handle_text                 │
│                                                             │
│ ┌─ Lookup / create session (SessionStore)                   │
│ ├─ Register request in ConfirmGate                          │
│ └─ Send first confirmation message                          │
│    State: IDLE → PENDING_CONFIRM                            │
└─────────────────────────────────────────────────────────────┘
  │
  │  Slack Web API → user:
  │  "Is this what you meant?
  │   > Add a health check API to the new-place server
  │   Type 'confirm' to proceed or 'cancel' to abort."
  ▼
User: "confirm" (first confirmation)
  │
  │  Socket Mode event (again)
  ▼
┌─────────────────────────────────────────────────────────────┐
│ [STEP 2] base.py — _do_confirm (Phase 1: plan)              │
│                                                             │
│ ┌─ Atomic pop of request from ConfirmGate                   │
│ ├─ Call server.plan_request()                               │
│ │   ├─ Router Agent: identify target projects               │
│ │   └─ PO Agent: build execution plan (phases)              │
│ └─ Show execution plan to user and request second confirm   │
│    State: PENDING_CONFIRM → PENDING_EXECUTION_CONFIRM       │
└─────────────────────────────────────────────────────────────┘
  │
  │  Slack Web API → user:
  │  "The following tasks will be performed:
  │   Project: new-place
  │   Phase 1: server
  │     - server: Add GET /health endpoint
  │   Do you want to proceed? ('confirm' / 'cancel')"
  ▼
User: "confirm" (second confirmation)
  │
  │  Socket Mode event (again)
  ▼
┌─────────────────────────────────────────────────────────────┐
│ [STEP 3] base.py — _do_execute_plan (Phase 2: execution)    │
│                                                             │
│ ┌─ Retrieve plan from session.pending_plan                  │
│ ├─ Call server.execute_from_plan()                          │
│ │   ├─ Executor: run workspace tasks phase by phase         │
│ │   └─ Task Log: write record to .tasks/                    │
│ └─ Format results and send to channel                       │
│    State: PENDING_EXECUTION_CONFIRM → AWAITING_FOLLOWUP     │
└─────────────────────────────────────────────────────────────┘
  │
  │  Slack Web API → results + "Shall we wrap up?"
  ▼
User: "yes" → session ends (context cleared)
User: (other text) → follow-up request handled with context retained
```

---

## 4. Step Details

### STEP 1: Message received + first confirmation — `base.py`

A message from Slack/Telegram arrives at `_handle_text`. The session is looked up, the request is registered in ConfirmGate, and a first confirmation message is sent.

```python
# base.py — _handle_text (State: IDLE → PENDING_CONFIRM)

session.add_user_turn(user_text)

request_id = uuid.uuid4().hex[:8]
self._confirm_gate.create_request(
    request_id=request_id,
    message=refined_message,
    channel=self.channel_name,
    callback_info=callback_info,
    raw_message=user_text,
)
session.pending_request_id = request_id
session.state = SessionState.PENDING_CONFIRM

# → "Is this what you meant? > ... Type 'confirm' to proceed or 'cancel' to abort."
```

### STEP 2: First confirmation → plan + second confirmation — `base.py → server.py`

When the user sends "confirm", `_do_confirm` is called. The request is atomically popped from ConfirmGate, and `plan_request()` builds the execution plan only (no execution yet).

```python
# base.py — _do_confirm (State: PENDING_CONFIRM → PENDING_EXECUTION_CONFIRM)

req = self._confirm_gate.remove(request_id)  # atomic pop
plan_result = await plan_request(req.message, raw_message=req.raw_message)

# plan_result["status"]:
#   "clarification_needed" → request additional information
#   "direct_answer" → PO answers directly (no modification)
#   "direct_request" → wiki/jira etc. (execute immediately)
#   "planned" → workspace modification task → requires second confirmation
```

`plan_request()` lives in `server.py` and calls the Router Agent + PO Agent:
```python
# server.py — plan_request()

route = await route_request(user_message)     # identify target projects
plan = await get_execution_plan(refined, project=proj)  # build execution plan
return {"status": "planned", "plans": [plan], ...}
```

For workspace modification tasks the plan is saved to the session and a second confirmation message is sent:
```python
session.pending_plan = {**plan_result, "request_id": request_id, ...}
session.state = SessionState.PENDING_EXECUTION_CONFIRM

# → "The following tasks will be performed:
#    Project: new-place
#    Phase 1: server
#      - server: Add GET /health endpoint
#    Do you want to proceed? ('confirm' / 'cancel')"
```

### STEP 3: Second confirmation → execution — `base.py → server.py`

When the user sends "confirm" again, `_do_execute_plan` is called.

```python
# base.py — _do_execute_plan (State: PENDING_EXECUTION_CONFIRM → AWAITING_FOLLOWUP)

plan_result = session.pending_plan
result = await execute_from_plan(plan_result, channel, callback_info, request_id)
```

`execute_from_plan()` lives in `server.py` and calls `_run_single_project()`:
```python
# server.py — execute_from_plan() → _run_single_project()

results = await execute_phases(project, phases, tasks)  # executor.py
await write_task_log(...)                                 # task_log.py
```

### STEP 4: Session end confirmation — `base.py`

After sending results, the bot asks "Shall we wrap up?".

```python
# State: AWAITING_FOLLOWUP

# User "yes" / "ok" / "done" → clear session (forget previous conversation)
if text_lower in FOLLOWUP_END_KEYWORDS:
    self._sessions.clear(source_key)

# Other text → retain context and handle as a follow-up request
session.state = SessionState.IDLE  # fall through to new request
```

### Supporting Detail: Executor + Task Log + Result Dispatch

**Executor** (`executor.py`): Runs workspace tasks phase by phase. Tasks in the same phase run in parallel.
```python
async def execute_phases(project, phases, tasks, ...):
    for phase in phases:
        coros = [run_workspace(project, ws, tasks[ws], upstream_context) for ws in phase]
        results = await asyncio.gather(*coros, return_exceptions=True)
```

**Task Log** (`task_log.py`): Writes records to `.tasks/{date}/{project}/{task_id}_{label}.md`.

**Result dispatch**: `send_to_channel()` → channel adapter's `send()` → Web API call.

---

## 5. How Telegram Differs

Telegram follows the same flow; only the reception mechanism differs:

| | Slack | Telegram |
|---|---|---|
| **Reception** | Socket Mode (WebSocket, no open port) | Long Polling (no open port) |
| **Auth** | Bot OAuth Token (`xoxb-...`) | Bot Token (`bot:...`) |
| **Send** | Web API (`api.slack.com`) | Bot API (`api.telegram.org`) |
| **ConfirmGate** | same | same |
| **handle_request** | same | same |

---

## 6. Credential Locations

```
ARCHIVE/
├── slack/credentials     # app_id, bot_token, signing_secret, app_level_token
└── telegram/credentials  # bot_token
```

---

## 7. One-Line Summary

```
Receive message (channel adapter)
  → First confirmation: "Is this what you meant?"
  → User: "confirm"
  → plan_request(): Router + PO Agent build execution plan
  → Second confirmation: "The following tasks will be performed: ... Do you want to proceed?"
  → User: "confirm"
  → execute_from_plan(): Executor runs + Task Log written
  → Send results + "Shall we wrap up?"
  → "yes" → session ends (context cleared) / other text → follow-up request handled
```
