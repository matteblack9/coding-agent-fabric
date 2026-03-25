# Orchestrator 구조 문서

Slack 메시지를 예시로, 사용자 메시지가 들어와서 결과가 돌아가기까지의 전체 흐름.

---

## 1. 디렉토리 구조

```
orchestrator/
├── main.py              # 엔트리포인트 — 모든 채널 기동
├── server.py            # ConfirmGate + handle_request + send_to_channel
├── po.py                # PO Agent — 실행 계획 수립
├── executor.py          # Workspace별 작업 실행
├── task_log.py          # .tasks/ 작업 이력 기록
└── channel/
    ├── slack.py          # Slack 어댑터 (Socket Mode)
    └── telegram.py       # Telegram 어댑터 (Long Polling)
```

---

## 2. 기동 (main.py)

`python3.11 -m orchestrator.main` 실행 시 **단일 프로세스**에서 모든 채널이 뜬다.

```python
# main.py 핵심

async def main() -> None:
    confirm_gate = ConfirmGate()          # 확인 대기 저장소

    slack_ch = SlackChannel(confirm_gate)  # Slack Socket Mode
    tg_ch = TelegramChannel(confirm_gate)  # Telegram Long Polling

    register_channel("slack", slack_ch)    # server.py 레지스트리에 등록
    register_channel("telegram", tg_ch)

    slack_task = asyncio.create_task(slack_ch.start())
    tg_task = asyncio.create_task(tg_ch.start())

    await stop_event.wait()                # SIGINT/SIGTERM까지 대기
```

기동 후 상태:
- Slack: WebSocket 연결 (Socket Mode, 포트 없음)
- Telegram: Long Polling (포트 없음)

---

## 3. Slack 메시지 수신 흐름 (전체 — 2단계 확인)

```
사용자 (Slack)
  │
  │  "new-place 서버에 health check API 추가해줘"
  ▼
Slack 서버 (api.slack.com)
  │
  │  Socket Mode WebSocket 이벤트
  │  Payload: { type: "message", text: "...", user: "...", channel: "..." }
  ▼
┌─────────────────────────────────────────────────────────────┐
│ [STEP 1] base.py — BaseChannel._handle_text                 │
│                                                             │
│ ┌─ 세션 조회/생성 (SessionStore)                              │
│ ├─ ConfirmGate에 요청 등록                                   │
│ └─ 1차 확인 메시지 전송                                       │
│    State: IDLE → PENDING_CONFIRM                             │
└─────────────────────────────────────────────────────────────┘
  │
  │  Slack Web API → 사용자에게:
  │  "이렇게 이해했는데 맞나요?
  │   > new-place 서버에 health check API 추가해줘
  │   진행하려면 '확인', 취소하려면 '취소'를 입력해주세요."
  ▼
사용자: "확인" (1차 확인)
  │
  │  Socket Mode 이벤트 (다시)
  ▼
┌─────────────────────────────────────────────────────────────┐
│ [STEP 2] base.py — _do_confirm (Phase 1: 계획 수립)          │
│                                                             │
│ ┌─ ConfirmGate에서 요청 atomic pop                           │
│ ├─ server.plan_request() 호출                                │
│ │   ├─ Router Agent: 대상 프로젝트 식별                       │
│ │   └─ PO Agent: 실행 계획(phases) 수립                       │
│ └─ 실행 계획을 사용자에게 보여주고 2차 확인 요청                 │
│    State: PENDING_CONFIRM → PENDING_EXECUTION_CONFIRM        │
└─────────────────────────────────────────────────────────────┘
  │
  │  Slack Web API → 사용자에게:
  │  "다음 작업을 수행합니다:
  │   프로젝트: new-place
  │   Phase 1: server
  │     - server: GET /health 엔드포인트 추가
  │   진행하시겠습니까? ('확인' / '취소')"
  ▼
사용자: "확인" (2차 확인)
  │
  │  Socket Mode 이벤트 (다시)
  ▼
┌─────────────────────────────────────────────────────────────┐
│ [STEP 3] base.py — _do_execute_plan (Phase 2: 실행)          │
│                                                             │
│ ┌─ session.pending_plan에서 계획 꺼내기                       │
│ ├─ server.execute_from_plan() 호출                           │
│ │   ├─ Executor: phase별 workspace 작업 실행                  │
│ │   └─ Task Log: .tasks/에 기록                              │
│ └─ 결과 포맷팅 후 채널에 전송                                  │
│    State: PENDING_EXECUTION_CONFIRM → AWAITING_FOLLOWUP      │
└─────────────────────────────────────────────────────────────┘
  │
  │  Slack Web API → 결과 + "작업을 끝낼까요?"
  ▼
사용자: "네" → 세션 종료 (컨텍스트 초기화)
사용자: (다른 텍스트) → 이전 맥락 유지하고 후속 작업 처리
```

---

## 4. 각 STEP 상세

### STEP 1: 메시지 수신 + 1차 확인 — `base.py`

Slack/Telegram에서 메시지가 `_handle_text`로 들어온다. 세션을 조회하고 ConfirmGate에 등록 후 1차 확인 메시지를 보낸다.

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

# → "이렇게 이해했는데 맞나요? > ... 진행하려면 '확인', 취소하려면 '취소'"
```

### STEP 2: 1차 확인 → 계획 수립 + 2차 확인 — `base.py → server.py`

사용자가 "확인"을 보내면 `_do_confirm`이 호출된다. ConfirmGate에서 요청을 atomic pop하고, `plan_request()`로 실행 계획만 수립한다 (실행은 안함).

```python
# base.py — _do_confirm (State: PENDING_CONFIRM → PENDING_EXECUTION_CONFIRM)

req = self._confirm_gate.remove(request_id)  # atomic pop
plan_result = await plan_request(req.message, raw_message=req.raw_message)

# plan_result["status"]:
#   "clarification_needed" → 추가 정보 요청
#   "direct_answer" → PO 직접 답변 (수정 없음)
#   "direct_request" → wiki/jira 등 (바로 실행)
#   "planned" → workspace 수정 작업 → 2차 확인 필요
```

`plan_request()`는 `server.py`에 있으며, Router Agent + PO Agent를 호출:
```python
# server.py — plan_request()

route = await route_request(user_message)     # 대상 프로젝트 식별
plan = await get_execution_plan(refined, project=proj)  # 실행 계획 수립
return {"status": "planned", "plans": [plan], ...}
```

workspace 수정 작업인 경우 계획을 세션에 저장하고 2차 확인 메시지를 보낸다:
```python
session.pending_plan = {**plan_result, "request_id": request_id, ...}
session.state = SessionState.PENDING_EXECUTION_CONFIRM

# → "다음 작업을 수행합니다:
#    프로젝트: new-place
#    Phase 1: server
#      - server: GET /health 엔드포인트 추가
#    진행하시겠습니까? ('확인' / '취소')"
```

### STEP 3: 2차 확인 → 실행 — `base.py → server.py`

사용자가 다시 "확인"을 보내면 `_do_execute_plan`이 호출된다.

```python
# base.py — _do_execute_plan (State: PENDING_EXECUTION_CONFIRM → AWAITING_FOLLOWUP)

plan_result = session.pending_plan
result = await execute_from_plan(plan_result, channel, callback_info, request_id)
```

`execute_from_plan()`은 `server.py`에 있으며, `_run_single_project()`를 호출:
```python
# server.py — execute_from_plan() → _run_single_project()

results = await execute_phases(project, phases, tasks)  # executor.py
await write_task_log(...)                                 # task_log.py
```

### STEP 4: 작업 종료 확인 — `base.py`

결과 전송 후 "작업을 끝낼까요?"를 묻는다.

```python
# State: AWAITING_FOLLOWUP

# 사용자 "네" / "ㅇㅇ" / "ok" → 세션 클리어 (이전 대화 망각)
if text_lower in FOLLOWUP_END_KEYWORDS:
    self._sessions.clear(source_key)

# 다른 텍스트 → 이전 맥락 유지하고 후속 요청으로 처리
session.state = SessionState.IDLE  # fall through to new request
```

### 보조 상세: Executor + Task Log + 결과 전송

**Executor** (`executor.py`): Phase별로 workspace 작업을 실행. 같은 phase는 병렬.
```python
async def execute_phases(project, phases, tasks, ...):
    for phase in phases:
        coros = [run_workspace(project, ws, tasks[ws], upstream_context) for ws in phase]
        results = await asyncio.gather(*coros, return_exceptions=True)
```

**Task Log** (`task_log.py`): `.tasks/{date}/{project}/{task_id}_{label}.md`에 기록.

**결과 전송**: `send_to_channel()` → 채널 어댑터의 `send()` → Web API 호출.

---

## 5. Telegram은 어떻게 다른가

Telegram도 동일한 흐름이지만, 수신 방식만 다르다:

| | Slack | Telegram |
|---|---|---|
| **수신** | Socket Mode (WebSocket, 포트 없음) | Long Polling (포트 없음) |
| **인증** | Bot OAuth Token (`xoxb-...`) | Bot Token (`bot:...`) |
| **송신** | Web API (`api.slack.com`) | Bot API (`api.telegram.org`) |
| **ConfirmGate** | 동일 | 동일 |
| **handle_request** | 동일 | 동일 |

---

## 6. Credential 위치

```
ARCHIVE/
├── slack/credentials     # app_id, bot_token, signing_secret, app_level_token
└── telegram/credentials  # bot_token
```

---

## 7. 한 줄 요약

```
메시지 수신 (채널 어댑터)
  → 1차 확인: "이렇게 이해했는데 맞나요?"
  → 사용자 "확인"
  → plan_request(): Router + PO Agent로 실행 계획 수립
  → 2차 확인: "다음 작업을 수행합니다: ... 진행하시겠습니까?"
  → 사용자 "확인"
  → execute_from_plan(): Executor 실행 + Task Log 기록
  → 결과 전송 + "작업을 끝낼까요?"
  → "네" → 세션 종료 (이전 대화 망각) / 다른 텍스트 → 후속 작업 처리
```
