---
name: connect-slack
description: "Slack 채널을 Claude-Code-Tunnels Orchestrator에 연결하는 스킬. Slack App 생성 가이드, Socket Mode 설정, credential 입력, 연결 테스트까지 수행. /claude-code-tunnels:connect-slack 으로 실행."
---

# Connect Slack Channel

기존 Claude-Code-Tunnels Orchestrator에 Slack 채널을 추가 연결한다.
Socket Mode(WebSocket)로 연결하므로 공인 IP나 callback URL이 필요 없다.

## Rules

- **사용자에게 묻지 않고 절대 진행하지 않는다**
- **자동 탐지된 값은 선택지로 먼저 제시** — 사용자는 번호만 치면 된다
- 기존 credentials 파일이 있으면 덮어쓰기 전에 반드시 사용자에게 확인
- credential 파일은 `key : value` 형식 (콜론 양쪽 공백)
- ARCHIVE/ 디렉토리는 git에 커밋하지 않음

---

## Step 0: Environment Preflight (CRITICAL)

Slack 연결에는 orchestrator 설치, pip 패키지, credential 파일이 필요하다.
아래 항목을 순서대로 확인하고, **하나라도 실패하면 해결될 때까지 다음 단계로 진행하지 않는다.**

### 0-1. orchestrator.yaml 확인

**왜 필요한가**: Slack 어댑터는 orchestrator.yaml에서 채널 활성화 여부와 ARCHIVE 경로를 읽는다. 이 파일이 없으면 어댑터 초기화가 실패한다.

```bash
if [ ! -f "orchestrator.yaml" ]; then
  echo "orchestrator.yaml이 없습니다."
  echo "먼저 /claude-code-tunnels:setup-orchestrator 를 실행해주세요."
  # → 여기서 중단
fi
```

### 0-2. ARCHIVE_PATH 확인

**왜 필요한가**: Slack credential(app_id, bot_token 등)이 `ARCHIVE/slack/credentials`에 저장된다.

```bash
ARCHIVE_PATH=$(python3 -c "import yaml; print(yaml.safe_load(open('orchestrator.yaml')).get('archive', 'ARCHIVE'))")
```

```
Credential 저장 경로를 확인합니다.

  [1] $ARCHIVE_PATH   ← orchestrator.yaml에서 읽은 값
  [2] 직접 입력

번호:
```

### 0-3. pip + 패키지 확인

**왜 필요한가**: `slack-bolt`(Socket Mode 핸들러)과 `slack-sdk`(Web API 클라이언트)가 필요하다. 없으면 `from slack_bolt import ...`에서 ImportError 발생.

```bash
$PYTHON_CMD -c "import slack_bolt" 2>/dev/null  # slack-bolt
$PYTHON_CMD -c "import slack_sdk" 2>/dev/null   # slack-sdk
```

미설치 시:
```
Slack 연결에 필요한 패키지가 설치되어 있지 않습니다:
  - slack-bolt  (Socket Mode 연결 및 이벤트 핸들링)
  - slack-sdk   (Slack Web API 호출 — 메시지 전송)

  [1] 지금 설치 ($PIP_CMD install slack-bolt slack-sdk)
  [2] 건너뛰기 (직접 설치 후 계속)

번호:
```

### 0-4. 기존 credential 확인

**왜 필요한가**: 이미 Slack 설정이 되어 있다면 덮어쓸지 결정해야 한다.

```bash
if [ -f "$ARCHIVE_PATH/slack/credentials" ]; then
  echo "기존 credentials 발견"
fi
```

기존 파일이 있으면:
```
기존 Slack credentials가 이미 존재합니다:
  app_id:           A0123...
  bot_token:        xoxb-...

  [1] 덮어쓰기 (새로 입력)
  [2] 기존 값 유지 (설정만 업데이트)
  [3] 중단

번호:
```

---

## Step 1: Slack App 생성 가이드

Slack App이 아직 없는 경우 안내:

```
Slack App Setup:
1. https://api.slack.com/apps → Create New App → "From scratch"
2. 이름 지정, workspace 선택
3. Settings → Socket Mode → Enable Socket Mode
   - App-level token 생성 (xapp-...) — connections:write scope
4. Event Subscriptions → Enable Events
   - Subscribe: message.channels, app_mention
5. OAuth & Permissions → Bot Token Scopes:
   - chat:write, channels:history, app_mentions:read
6. Install App to Workspace
7. Bot Token (xoxb-...) 복사

준비가 되셨나요? (yes — credential 입력 시작 / no — 가이드 상세 설명)
```

---

## Step 2: Credential 수집 (6개 필드)

**반드시 사용자에게 하나씩 물어본다. 빈 값을 허용하지 않는다.**

각 필드를 물어볼 때 **왜 필요한지 한 줄 설명**을 덧붙인다:

```
─────────────────────────────────────────────────────────────────
1. app_id
   Slack App 설정의 Basic Information 페이지에 표시됩니다.
   형식: A로 시작 (예: A0123456789)
   입력:

2. client_id
   Basic Information → App Credentials 에 표시됩니다.
   형식: 숫자.숫자 (예: 1234567890.1234567890)
   입력:

3. client_secret
   같은 App Credentials 섹션에 표시됩니다. Show 버튼을 눌러 복사하세요.
   입력:

4. signing_secret
   같은 App Credentials 섹션. 봇으로 들어온 요청의 무결성 검증에 사용됩니다.
   입력:

5. app_level_token
   Settings → Basic Information → App-Level Tokens 에서 생성합니다.
   Socket Mode 연결 시 인증에 사용됩니다.
   형식: xapp- 로 시작
   검증: xapp- 로 시작하지 않으면 → "형식이 올바르지 않습니다. xapp- 로 시작하는 전체 토큰을 입력해주세요."
   입력:

6. bot_token
   OAuth & Permissions → Bot User OAuth Token 입니다.
   메시지 전송(chat_postMessage)에 사용됩니다.
   형식: xoxb- 로 시작
   검증: xoxb- 로 시작하지 않으면 → "형식이 올바르지 않습니다."
   입력:
─────────────────────────────────────────────────────────────────
```

수집 완료 후 요약:
```
입력된 Slack Credentials:
  app_id:           A0123456789
  client_id:        1234567890.1234567890
  client_secret:    ****
  signing_secret:   ****
  app_level_token:  xapp-1-...
  bot_token:        xoxb-...

이대로 저장할까요? (yes/no)
```

---

## Step 3: 설정 저장

사용자 확인 후:

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

orchestrator.yaml 업데이트:
```yaml
channels:
  slack:
    enabled: true
```

---

## Step 4: 연결 테스트

```bash
cd $PROJECT_ROOT && ./start-orchestrator.sh --fg &
sleep 5
# 로그에서 "Slack channel starting (Socket Mode)..." 확인
```

- 성공 → "Slack 연결 완료. Slack에서 봇에게 메시지를 보내 테스트해보세요."
- 실패 → 에러 로그를 사용자에게 보여주고 원인 분석. 자동 재시도하지 않음.

## Credential File Format

```
app_id : A0123456789
client_id : 1234567890.1234567890
client_secret : abcdef1234567890
signing_secret : abcdef1234567890
app_level_token : xapp-1-A0123-1234567890-abcdef
bot_token : xoxb-1234567890-1234567890-abcdef
```
