---
name: setup-orchestrator
description: "Claude-Code-Tunnels(Project Orchestrator) 설치 스킬. 현재 프로젝트 디렉토리에 PO를 설치하고 workspace 인식, 메신저 채널 연동까지 한번에 수행. /claude-code-tunnels:setup-orchestrator 로 실행."
---

# Claude-Code-Tunnels Setup

Claude-Code-Tunnels (Project Orchestrator)를 사용자의 프로젝트 디렉토리에 설치한다.
PO가 하위 프로젝트/workspace를 인식하고 `claude-agent-sdk query(cwd=workspace/)` 로 작업을 위임하는 구조.

## Plugin Source

이 플러그인 디렉토리에 orchestrator 코드와 템플릿이 포함되어 있다.
`PLUGIN_DIR` = 이 SKILL.md의 2단계 상위 디렉토리 (플러그인 루트).

포함 파일: `orchestrator/`, `templates/`, `orchestrator.yaml`, `install.sh`, `requirements.txt`

## Rules

- **사용자에게 묻지 않고 절대 진행하지 않는다** — 모든 환경변수/경로는 반드시 사용자 확인을 받는다
- 단, **자동 탐지된 값은 선택지로 먼저 제시**한다 — 사용자는 번호만 치면 된다
- 원본 코드 로직 수정 금지. 경로/설정만 변경
- 기존 CLAUDE.md 내용 보존. 필요 시 append만
- ARCHIVE/ 디렉토리는 절대 git에 커밋하지 않음

---

## Phase 0: Environment Preflight (CRITICAL — 반드시 먼저 실행)

Orchestrator는 Python 런타임, pip, Claude SDK에 의존한다.
시스템마다 설치 경로와 버전이 다르므로, 설치 전에 현재 환경이 요구사항을 충족하는지 점검한다.
**하나라도 실패하면 → 해결될 때까지 다음 단계로 진행하지 않는다.**

### 0-1. Python 런타임

**왜 필요한가**: orchestrator 전체가 Python으로 작성되어 있고, `claude-agent-sdk`가 Python 3.10+ 을 요구한다.

시스템에서 사용 가능한 Python을 자동 탐지한다:

```bash
candidates=()
for cmd in python3 python python3.12 python3.11 python3.10; do
  full=$(command -v "$cmd" 2>/dev/null) || continue
  ver=$("$full" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null) || continue
  major=${ver%%.*}; minor=${ver#*.}
  if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
    candidates+=("$full ($cmd $ver)")
  fi
done
```

탐지 결과를 **번호 선택지**로 제시:

```
Python 3.10+ 런타임을 선택해주세요.
Orchestrator 코드와 claude-agent-sdk가 이 Python으로 실행됩니다.

  [1] /usr/bin/python3       (python3 3.11.5)   ← 탐지됨
  [2] /usr/local/bin/python3.12 (python3.12 3.12.1) ← 탐지됨
  [3] 직접 입력

번호 또는 경로:
```

- 사용자가 `1` 또는 `2` → 해당 경로를 `PYTHON_CMD`로 설정
- 사용자가 `3` 또는 직접 경로 입력 → 해당 경로의 버전을 확인 후 사용
- 탐지 결과가 0개 → "Python 3.10+ 을 찾지 못했습니다. 직접 경로를 입력해주세요."

### 0-2. pip

**왜 필요한가**: claude-agent-sdk, aiohttp, pyyaml 등 Python 패키지를 설치/확인할 때 사용한다.

```bash
pip_candidates=()
for cmd in "$PYTHON_CMD -m pip" pip3 pip; do
  if $cmd --version &>/dev/null 2>&1; then
    pip_candidates+=("$cmd")
  fi
done
```

```
pip를 선택해주세요. 의존성 패키지 설치에 사용됩니다.

  [1] /usr/bin/python3 -m pip  (pip 23.2.1)   ← 탐지됨
  [2] 직접 입력

번호 또는 경로:
```

### 0-3. Claude Code CLI

**왜 필요한가**: `claude-agent-sdk`가 내부적으로 `claude` CLI 바이너리를 호출한다. CLI가 없으면 `query()` 호출이 실패한다.

```bash
claude_path=$(command -v claude 2>/dev/null)
```

- 찾음 → "Claude CLI 탐지됨: `$claude_path` (`claude --version`). OK?"
- 못 찾음 →
  ```
  Claude CLI를 찾지 못했습니다.
  claude-agent-sdk의 query()는 내부적으로 claude 바이너리를 호출하므로 필수입니다.

    [1] 경로를 직접 입력 (예: ~/.npm/bin/claude)
    [2] 지금 설치 (npm install -g @anthropic-ai/claude-code)
    [3] 나중에 설치 (설치 없이 계속 — 실행 시 에러 발생 가능)

  번호:
  ```

### 0-4. 필수 Python 패키지

**왜 필요한가**: 각 패키지의 역할이 다르다.
- `claude-agent-sdk`: Claude Code를 Python에서 프로그래밍 방식으로 호출하는 핵심 라이브러리
- `aiohttp`: 채널 어댑터(Telegram polling)와 remote listener가 비동기 HTTP를 처리하는 데 사용
- `pyyaml`: orchestrator.yaml 설정 파일 파싱

```bash
declare -A pkg_status
for pkg in claude_agent_sdk aiohttp yaml; do
  if $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
    pkg_status[$pkg]="OK"
  else
    pkg_status[$pkg]="NOT INSTALLED"
  fi
done
```

미설치 패키지가 있으면:
```
다음 패키지가 설치되어 있지 않습니다:
  - claude-agent-sdk (Claude SDK — 없으면 orchestrator가 실행 불가)
  - aiohttp          (비동기 HTTP — 없으면 채널/리모트 연결 불가)

설치 명령: $PIP_CMD install claude-agent-sdk aiohttp pyyaml

  [1] 지금 설치
  [2] 건너뛰기 (나중에 직접 설치)

번호:
```

### Preflight 결과 보고

```
Environment Preflight Results
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Python:            /usr/bin/python3 (3.11.5)         ✓
  pip:               /usr/bin/python3 -m pip (23.2.1)  ✓
  Claude CLI:        /usr/local/bin/claude (1.0.35)    ✓
  claude-agent-sdk:  0.3.0                             ✓
  aiohttp:           3.9.1                             ✓
  pyyaml:            6.0.1                             ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
모든 항목을 통과했습니다. 설정을 시작할까요? (yes/no)
```

---

## Phase 1: 사용자 입력 수집

환경 점검이 끝났으니, 설치 위치와 채널을 결정한다.
가능한 값을 자동 탐지하여 **선택지로 제시**한다. 사용자는 번호만 입력하면 된다.

### 1-1. PROJECT_ROOT

현재 디렉토리와 상위 디렉토리를 후보로 제시:

```bash
cwd=$(pwd)
parent=$(dirname "$cwd")

# 하위 디렉토리가 2개 이상인 경로를 프로젝트 루트 후보로
candidates=()
for d in "$cwd" "$parent"; do
  subdir_count=$(find "$d" -maxdepth 1 -mindepth 1 -type d ! -name '.*' | wc -l)
  if [ "$subdir_count" -ge 1 ]; then
    candidates+=("$d  (하위 ${subdir_count}개 디렉토리)")
  fi
done
```

```
프로젝트 루트 디렉토리를 선택해주세요.
하위 프로젝트/workspace가 이 안에 들어있어야 합니다.

  [1] /home/user/my-projects  (하위 4개 디렉토리)  ← 현재 위치
  [2] /home/user              (하위 7개 디렉토리)  ← 상위
  [3] 직접 입력

번호 또는 절대경로:
```

검증: `test -d` && `test -w`

### 1-2. ARCHIVE_PATH

```
Credential 저장 경로를 선택해주세요.
Slack/Telegram 토큰 등이 이 디렉토리에 저장됩니다. (git 제외)

  [1] $PROJECT_ROOT/ARCHIVE   ← 기본 권장
  [2] 직접 입력

번호 또는 절대경로:
```

### 1-3. CHANNELS

```
연결할 메신저 채널을 선택해주세요.
Orchestrator가 이 채널에서 메시지를 받아 작업을 수행합니다.
복수 선택 가능 — 번호를 쉼표로 구분 (예: 1,3)

  [1] slack      — Slack Socket Mode (공인IP 불필요)
  [2] telegram   — Telegram Bot long polling (공인IP 불필요)
  [3] 나중에 설정 (skip)

번호:
```

### 입력값 검증 (반드시 수행)

```bash
test -d "$PROJECT_ROOT" || echo "ERROR: $PROJECT_ROOT 존재하지 않습니다."
test -w "$PROJECT_ROOT" || echo "ERROR: $PROJECT_ROOT 쓰기 권한 없습니다."
mkdir -p "$ARCHIVE_PATH" 2>/dev/null || echo "ERROR: $ARCHIVE_PATH 생성 실패."
```

**검증 실패 시 → 해당 항목만 다시 선택지 제시. 자동으로 대체값을 정하지 않는다.**

---

## Phase 2: Orchestrator 코드 복사

사용자에게 복사할 파일 목록을 보여주고 확인받는다:

```bash
PLUGIN_DIR="<이 플러그인 루트 경로>"

echo "다음 파일들을 $PROJECT_ROOT 에 복사합니다:"
echo "  orchestrator/    ← Python 패키지 (PO, executor, router, channels)"
echo "  .claude/rules/   ← delegation, task-log, notification rules"
echo "  start-orchestrator.sh ← 시작 스크립트 ($PYTHON_CMD 사용)"
echo "진행할까요? (yes/no)"

# 사용자 확인 후:
cp -r $PLUGIN_DIR/orchestrator/ $PROJECT_ROOT/orchestrator/
mkdir -p $PROJECT_ROOT/.claude/rules/
cp $PLUGIN_DIR/templates/rules/*.md $PROJECT_ROOT/.claude/rules/

# start-orchestrator.sh — PYTHON_CMD 반영
sed "s|python3|$PYTHON_CMD|g" $PLUGIN_DIR/templates/start-orchestrator.sh.template \
  > $PROJECT_ROOT/start-orchestrator.sh
chmod +x $PROJECT_ROOT/start-orchestrator.sh
```

---

## Phase 3: orchestrator.yaml 생성

사용자 입력값으로 생성 후, 내용을 보여주고 확인:

```yaml
root: $PROJECT_ROOT
archive: $ARCHIVE_PATH
channels:
  slack:
    enabled: true/false
  telegram:
    enabled: true/false
remote_workspaces: []
```

---

## Phase 4: CLAUDE.md 설정

- 없으면 → `$PLUGIN_DIR/templates/CLAUDE.md.template` 기반 생성
- 있는데 Orchestrator 언급 없으면 → orchestrator 섹션 append
- 이미 있으면 → skip

---

## Phase 5: Workspace 탐색

하위 디렉토리를 자동 탐지하여 체크리스트로 제시:

```bash
ls $PROJECT_ROOT/   # 제외: orchestrator/, ARCHIVE/, .tasks/, .claude/, .git/, 숨김폴더
```

```
발견된 하위 디렉토리입니다.
Workspace로 등록할 항목을 선택해주세요 (번호를 쉼표로 구분, 전체: all):

  [1] project-a/        (CLAUDE.md 있음)
  [2] project-b/        (CLAUDE.md 있음)
  [3] project-c/        (CLAUDE.md 없음 — 기본 생성됨)
  [4] data-scripts/     (CLAUDE.md 없음 — 기본 생성됨)

번호 (예: 1,2,3 또는 all):
```

CLAUDE.md가 없는 workspace는 기본 생성 여부를 안내한다.

---

## Phase 6: 채널 설정

선택된 채널에 따라 해당 채널 skill을 순서대로 실행:
- Slack → `/claude-code-tunnels:connect-slack`
- Telegram → `/claude-code-tunnels:connect-telegram`

의존성 설치 (사용자에게 목록 보여주고 확인):
```
설치할 패키지:
  기본:  claude-agent-sdk aiohttp pyyaml
  Slack: slack-bolt slack-sdk

명령어: $PIP_CMD install claude-agent-sdk aiohttp pyyaml slack-bolt slack-sdk

  [1] 설치 진행
  [2] 건너뛰기 (직접 설치)

번호:
```

---

## Phase 7: 테스트 & 완료

```bash
cd $PROJECT_ROOT && ./start-orchestrator.sh --fg &
sleep 3
# Slack: 로그에서 "Socket Mode" 확인
# Telegram: 로그에서 bot username 확인
```

**테스트 실패 시 → 에러 메시지와 함께 사용자에게 상황 설명. 자동 재시도하지 않는다.**

최종 요약:
```
Setup Complete!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Project Root:  /home/user/my-projects
  Archive:       /home/user/my-projects/ARCHIVE
  Python:        /usr/bin/python3 (3.11.5)
  Channels:      slack ✓, telegram ✗
  Workspaces:    project-a, project-b, project-c

생성된 파일:
  orchestrator/          ← Python 패키지
  orchestrator.yaml      ← 설정 파일
  start-orchestrator.sh  ← 시작 스크립트
  .claude/rules/         ← delegation rules
  CLAUDE.md              ← PO 설명

다음 단계:
  ./start-orchestrator.sh              ← 백그라운드 시작
  ./start-orchestrator.sh --fg         ← 포그라운드 (디버그)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Credential File Format

모든 credential 파일은 동일한 형식:
```
key : value
```
콜론 양쪽에 반드시 공백. bot_token에 콜론이 포함되어도 첫 ` : ` 기준으로만 split.

## 파일 구조 (설치 후)

```
PROJECT_ROOT/
├── orchestrator/          ← PO, executor, router, channels
│   ├── __init__.py
│   ├── main.py
│   ├── server.py
│   ├── po.py
│   ├── executor.py
│   ├── router.py
│   ├── channel/           ← Slack, Telegram adapters
│   └── remote/            ← listener, deploy helpers
├── orchestrator.yaml      ← 설정 파일
├── start-orchestrator.sh  ← 시작 스크립트
├── CLAUDE.md              ← PO용 프로젝트 설명
├── .claude/rules/         ← delegation, task-log, notification rules
├── ARCHIVE/               ← credentials (git 제외)
├── .tasks/                ← 작업 이력 로그
├── project-a/             ← workspace
│   └── CLAUDE.md
└── project-b/             ← workspace
    └── CLAUDE.md
```
