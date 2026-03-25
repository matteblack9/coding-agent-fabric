---
name: setup-remote-workspace
description: "원격 장비의 특정 workspace 하나를 Orchestrator에 연결하는 스킬. setup-remote-project와 유사하지만 단일 workspace 단위로 설정. /claude-code-tunnels:setup-remote-workspace 로 실행."
---

# Setup Remote Workspace

원격 장비의 특정 workspace 하나를 Orchestrator에 연결한다.
`/claude-code-tunnels:setup-remote-project`와 동일한 listener를 사용하되, 단일 workspace 단위로 등록.

## Difference from setup-remote-project

| | setup-remote-project | setup-remote-workspace |
|---|---|---|
| 대상 | 프로젝트 전체 (하위 workspace 포함) | 특정 workspace 1개 |
| 등록 | 프로젝트 구조를 PO가 인식 | workspace를 직접 지정하여 등록 |
| 사용 시점 | 프로젝트 전체를 원격으로 옮길 때 | 기존 프로젝트에 원격 workspace를 추가할 때 |

## Rules

- **사용자에게 묻지 않고 절대 진행하지 않는다**
- **자동 탐지된 값은 선택지로 먼저 제시** — 사용자는 번호만 치면 된다
- listener 1개당 workspace 1개 (같은 호스트 → 다른 포트 사용)
- 원격 workspace에 CLAUDE.md가 있어야 PO가 이해할 수 있음

---

## Step 0: Environment Preflight (CRITICAL)

단일 workspace를 원격 listener에 연결하려면 orchestrator 설치와 접속 수단이 필요하다.
**하나라도 실패하면 해결될 때까지 다음 단계로 진행하지 않는다.**

### 0-1. orchestrator.yaml 확인

**왜 필요한가**: remote_workspaces 배열에 새 workspace를 추가해야 한다.

- 없으면 → "먼저 /claude-code-tunnels:setup-orchestrator 를 실행해주세요." 후 **중단**

### 0-2. orchestrator/remote/ 확인

**왜 필요한가**: deploy.py와 listener.py가 있어야 원격 배포가 가능하다.

### 0-3. 기존 remote_workspaces 확인

**왜 필요한가**: 같은 host:port에 중복 등록을 방지하고, 기존 포트와 겹치지 않는 포트를 추천할 수 있다.

```
현재 등록된 원격 workspace:
  my-project/backend  → 10.0.0.5:9100
  my-project/frontend → 10.0.0.5:9101

새 workspace를 추가합니다.
```

### 0-4. 접속 도구 확인

사용 가능한 도구를 자동 탐지:

```
원격 접속 방법을 선택해주세요.

  [1] ssh       ← 탐지됨
  [2] kubectl   ← 탐지됨

번호:
```

---

## Step 1: 대상 식별

### 1-1. project

로컬 프로젝트 디렉토리를 자동 탐지하여 선택지로 제시:

```bash
# orchestrator.yaml의 root 아래 디렉토리 목록
root=$(python3 -c "import yaml; print(yaml.safe_load(open('orchestrator.yaml')).get('root','.'))")
ls "$root"  # 제외: orchestrator, ARCHIVE, .tasks, .claude, .git, 숨김폴더
```

```
이 workspace가 속한 프로젝트를 선택해주세요.
로컬에 같은 이름의 프로젝트 디렉토리가 있어야 PO가 인식합니다.

  [1] my-project
  [2] another-project
  [3] 직접 입력

번호:
```

### 1-2. workspace

```
workspace 이름을 입력해주세요.
execution plan에서 이 이름으로 표시됩니다.
orchestrator.yaml에는 "$PROJECT/$WORKSPACE" 로 등록됩니다.

입력 (예: data-pipeline):
```

### 결과 미리보기

```
등록될 이름: my-project/data-pipeline

맞나요? (yes/no)
```

---

## Step 2: 연결 정보 수집

### SSH 선택 시

```
─────────────────────────────────────────────────────────────────
1. host (필수)
   listener에 HTTP로 연결할 원격 장비입니다.
   입력:

2. user
     [1] $USER   ← 현재 사용자
     [2] 직접 입력
   번호:

3. key_file
     [1] ~/.ssh/id_rsa       ← 존재함
     [2] ~/.ssh/id_ed25519   ← 존재함
     [3] 기본 key 사용
     [4] 직접 입력
   번호:
─────────────────────────────────────────────────────────────────
```

SSH key 후보 자동 탐지: `~/.ssh/` 스캔.
입력 완료 후 **즉시 연결 테스트**: `ssh $USER@$HOST "echo OK"`

### kubectl 선택 시

namespace → pod → container 순서로 자동 탐지 선택지 제시 (setup-remote-project과 동일).

---

## Step 3: Remote Workspace 경로

```
원격 장비에서 workspace가 위치한 절대경로를 입력해주세요.

입력 (예: /home/user/my-project/data-pipeline):
```

검증: 원격에서 `test -d` 로 존재 확인.

listener 포트 — 기존 등록 포트와 겹치지 않는 후보 자동 계산:

```bash
# 이미 사용 중인 포트 확인
used_ports=(9100 9101)  # orchestrator.yaml에서 같은 host의 포트
next_port=9102          # 다음 사용 가능 포트
```

```
listener 포트를 선택해주세요.
같은 호스트(10.0.0.5)에 이미 9100, 9101이 등록되어 있습니다.

  [1] 9102   ← 다음 번호, 사용 가능
  [2] 9103   ← 사용 가능
  [3] 직접 입력

번호:
```

인증 토큰:
```
  [1] 설정 안 함
  [2] 토큰 입력

번호:
```

---

## Step 4: 원격 환경 사전 확인 (CRITICAL)

**왜 필요한가**: listener가 원격에서 Python + claude-agent-sdk + aiohttp을 사용한다.

```
원격 환경 확인 결과:
  Python:            3.11.5            ✓
  claude-agent-sdk:  0.3.0             ✓
  aiohttp:           3.9.1             ✓

  [1] 계속 진행
  — 또는 미설치 항목이 있으면 —
  [1] 원격에서 지금 설치
  [2] 직접 설치 후 계속

번호:
```

---

## Step 5: 배포 & 등록

배포 요약:
```
배포 요약:
  workspace:  my-project/data-pipeline
  대상:       irteam@10.0.0.5
  경로:       /home/user/my-project/data-pipeline
  포트:       9102
  토큰:       (없음)

진행할까요? (yes/no)
```

확인 후 배포 + orchestrator.yaml 업데이트:
```yaml
remote_workspaces:
  - name: my-project/backend
    host: 10.0.0.5
    port: 9100
  - name: my-project/frontend
    host: 10.0.0.5
    port: 9101
  - name: my-project/data-pipeline    # ← 새로 추가
    host: 10.0.0.5
    port: 9102
    token: ""
```

---

## Step 6: 검증

```bash
curl http://$HOST:$LISTENER_PORT/health
# 기대: {"status": "ok", "cwd": "...", "port": 9102}
```

- 성공 → "원격 workspace 연결 완료. PO가 execution plan에 이 workspace를 포함하면 자동으로 원격 실행됩니다."
- 실패 → 에러 내용 보여주고 원인 분석. 자동 재시도하지 않음.

## 로그 확인

```bash
ssh $USER@$HOST cat /tmp/claude-listener-$LISTENER_PORT.log
kubectl exec $POD -n $NAMESPACE -- cat /tmp/claude-listener-$LISTENER_PORT.log
```
