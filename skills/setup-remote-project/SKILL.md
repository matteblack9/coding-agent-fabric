---
name: setup-remote-project
description: "원격 장비(SSH/kubectl)에 listener를 배포하여 Orchestrator가 해당 장비의 프로젝트를 workspace로 사용 가능하게 설정. /claude-code-tunnels:setup-remote-project 로 실행."
---

# Setup Remote Project

원격 장비(SSH) 또는 Kubernetes Pod에 lightweight HTTP listener를 배포하여,
Orchestrator가 원격 환경의 프로젝트를 workspace로 사용할 수 있게 한다.

핵심: `claude-agent-sdk query(cwd=)` 는 타임아웃이 없다. listener가 원격에서 SDK를 직접 호출하므로
로컬 실행과 동일하게 시간 제한 없이 작업이 수행된다.

## Rules

- **사용자에게 묻지 않고 절대 진행하지 않는다**
- **자동 탐지된 값은 선택지로 먼저 제시** — 사용자는 번호만 치면 된다
- listener 1개당 workspace 1개 (같은 호스트에 여러 workspace → 다른 포트)
- 원격 workspace에 CLAUDE.md가 있어야 PO가 이해할 수 있음
- listener는 지속 실행 필요 (nohup 기본, systemd/supervisord 권장)

---

## Step 0: Environment Preflight (CRITICAL)

원격 프로젝트 연결에는 로컬 orchestrator 설치와 원격 장비로의 접근 수단(ssh/kubectl)이 필요하다.
아래 항목을 순서대로 확인하고, **하나라도 실패하면 해결될 때까지 다음 단계로 진행하지 않는다.**

### 0-1. orchestrator.yaml 확인

**왜 필요한가**: remote_workspaces 설정을 이 파일에 등록해야 하고, executor가 여기서 원격 호스트 정보를 읽는다.

- 없으면 → "먼저 /claude-code-tunnels:setup-orchestrator 를 실행해주세요." 후 **중단**

### 0-2. orchestrator/remote/ 확인

**왜 필요한가**: `deploy.py`(원격 배포 스크립트)와 `listener.py`(원격에서 실행될 HTTP 서버)가 있어야 배포가 가능하다.

```bash
if [ ! -f "orchestrator/remote/deploy.py" ] || [ ! -f "orchestrator/remote/listener.py" ]; then
  echo "orchestrator/remote/ 파일이 없습니다."
fi
```

### 0-3. 접속 도구 확인

**왜 필요한가**: listener.py를 원격에 복사하고 실행하려면 ssh 또는 kubectl이 필요하다.

사용 가능한 도구를 자동 탐지:
```bash
tools=()
command -v ssh &>/dev/null && tools+=("ssh")
command -v kubectl &>/dev/null && tools+=("kubectl")
```

```
원격 접속 방법을 선택해주세요.
listener.py를 원격 장비에 복사하고 실행하는 데 사용됩니다.

  [1] ssh       ← 탐지됨
  [2] kubectl   ← 탐지됨
  [3] 직접 입력 (다른 경로의 ssh/kubectl)

번호:
```

탐지 결과가 0개 → "ssh 또는 kubectl을 찾지 못했습니다. 설치 후 다시 시도해주세요."

### 0-4. 기존 remote_workspaces 확인

**왜 필요한가**: 같은 호스트:포트로 중복 등록을 방지하기 위해 현재 등록 상태를 보여준다.

```
현재 등록된 원격 workspace:
  (없음)
  — 또는 —
  my-project/backend → 10.0.0.5:9100
  my-project/frontend → 10.0.0.5:9101
```

---

## Step 1: 연결 정보 수집

### 1-1. workspace_name

```
Orchestrator에서 이 원격 프로젝트를 어떤 이름으로 식별할까요?
execution plan에서 이 이름으로 표시됩니다.
형식: project/workspace (예: my-project/backend)

입력:
```

검증: `/`가 포함되어야 함 (project/workspace 형태).

### 1-2. SSH 정보 수집

사용자가 ssh를 선택한 경우:

```
─────────────────────────────────────────────────────────────────
1. host (필수)
   원격 장비의 IP 또는 hostname입니다. listener에 HTTP로 연결할 때 사용됩니다.
   입력:

2. user
   SSH 접속 사용자명입니다.

     [1] $USER   ← 현재 사용자
     [2] 직접 입력

   번호:

3. key_file
   SSH key 파일입니다.

     [1] ~/.ssh/id_rsa     ← 존재함
     [2] ~/.ssh/id_ed25519 ← 존재함
     [3] 기본 key 사용 (ssh-agent)
     [4] 직접 입력

   번호:
─────────────────────────────────────────────────────────────────
```

SSH key 후보는 `~/.ssh/` 디렉토리를 스캔하여 자동 탐지:
```bash
for f in ~/.ssh/id_rsa ~/.ssh/id_ed25519 ~/.ssh/id_ecdsa; do
  [ -f "$f" ] && echo "$f"
done
```

입력 완료 후 **즉시 연결 테스트**:
```bash
ssh $USER@$HOST "echo 'SSH OK'"
```
- 실패 → 에러 보여주고 재입력 선택지 제시

### 1-3. kubectl 정보 수집

사용자가 kubectl을 선택한 경우:

사용 가능한 namespace/pod를 자동 탐지하여 선택지로 제시:

```bash
# namespace 목록
kubectl get namespaces -o jsonpath='{.items[*].metadata.name}' 2>/dev/null
```

```
Namespace를 선택해주세요.

  [1] default
  [2] my-namespace
  [3] production
  [4] 직접 입력

번호:
```

namespace 선택 후 pod 목록:
```bash
kubectl get pods -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' 2>/dev/null
```

```
Pod를 선택해주세요.

  [1] my-app-abc123
  [2] my-app-def456
  [3] 직접 입력

번호:
```

container (multi-container pod인 경우):
```bash
kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.spec.containers[*].name}' 2>/dev/null
```

kubeconfig:
```
  [1] ~/.kube/config   ← 기본
  [2] 직접 입력

번호:
```

연결 테스트: `kubectl exec $POD -n $NAMESPACE -- echo 'K8s OK'`

---

## Step 2: Remote Workspace 경로

```
원격 장비에서 프로젝트가 위치한 절대경로를 입력해주세요.
listener가 이 경로에서 claude-agent-sdk query(cwd=)를 실행합니다.

입력 (예: /home/user/my-project):
```

검증 — 원격에서 경로 존재 확인:
```bash
ssh $USER@$HOST "test -d $REMOTE_CWD && echo OK || echo FAIL"
```

listener 포트:
```bash
# 사용 가능한 포트 자동 탐지 (원격)
for p in 9100 9101 9102; do
  ssh $USER@$HOST "ss -tlnp 2>/dev/null | grep -q ':${p} '" || available+=("$p")
done
```

```
listener 포트를 선택해주세요.
executor가 이 포트로 HTTP 요청을 보냅니다.

  [1] 9100   ← 사용 가능
  [2] 9101   ← 사용 가능
  [3] 직접 입력

번호:
```

인증 토큰:
```
listener에 Bearer 토큰 인증을 설정하시겠습니까?
설정하면 orchestrator만 listener에 접근할 수 있습니다.

  [1] 설정 안 함 (내부망이라 불필요)
  [2] 토큰 입력

번호:
```

---

## Step 3: 원격 환경 사전 확인 (CRITICAL)

**왜 필요한가**: listener는 원격에서 Python + claude-agent-sdk + aiohttp을 사용한다. 하나라도 없으면 실행이 실패한다.

```bash
# 원격 Python 확인
ssh $USER@$HOST "python3 --version"

# 원격 패키지 확인
ssh $USER@$HOST "python3 -c 'import claude_agent_sdk'" 2>/dev/null
ssh $USER@$HOST "python3 -c 'import aiohttp'" 2>/dev/null
```

```
원격 환경 확인 결과:
  Python:            3.11.5            ✓
  claude-agent-sdk:  OK                ✓
  aiohttp:           NOT INSTALLED     ✗

미설치 패키지가 있습니다.

  [1] 원격에서 지금 설치 (ssh로 pip install 실행)
  [2] 직접 설치 후 계속
  [3] 무시하고 계속 (listener 시작 시 에러 발생 가능)

번호:
```

---

## Step 4: Listener 배포

배포 요약 후 확인:
```
배포 요약:
  대상:       $USER@$HOST
  경로:       $REMOTE_CWD/.claude-listener.py
  포트:       $LISTENER_PORT
  토큰:       (설정됨/없음)

listener.py를 원격에 복사하고 실행합니다.
진행할까요? (yes/no)
```

배포 과정:
1. listener.py를 원격에 복사 (`remote_cwd/.claude-listener.py`)
2. 기존 listener가 있으면 kill
3. nohup으로 시작 (로그: `/tmp/claude-listener-{port}.log`)
4. health check 자동 수행 (최대 6회, 2초 간격)

---

## Step 5: orchestrator.yaml 등록 & 검증

```yaml
remote_workspaces:
  - name: $WORKSPACE_NAME
    host: $HOST
    port: $LISTENER_PORT
    token: "$LISTENER_TOKEN"
```

검증:
```bash
curl http://$HOST:$LISTENER_PORT/health
# 기대: {"status": "ok", "cwd": "$REMOTE_CWD", "port": $LISTENER_PORT}
```

- 성공 → "원격 프로젝트 연결 완료."
- 실패 → 에러 내용 보여주고 원인 분석. 자동 재시도하지 않음.

## Listener API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | 상태 확인 |
| `/execute` | POST | task 실행. Body: `{"task": "...", "upstream_context": {}}` |

## 로그 확인

```bash
ssh $USER@$HOST cat /tmp/claude-listener-$LISTENER_PORT.log
kubectl exec $POD -n $NAMESPACE -- cat /tmp/claude-listener-$LISTENER_PORT.log
```
