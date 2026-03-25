# Orchestrator

Claude Agent SDK + `cwd` 기반 Task Delegation 아키텍처.

## 아키텍처 개요

### Agent SDK + cwd)
```
메신저 → Python 미들웨어 → query(cwd=project/) [PO: 라우팅+dependency 판단]
                              → query(cwd=workspace/) [각 workspace 실행]
```
## 핵심 설계 결정

1. **기존 CLAUDE.md + .claude/ 무변경** — 모든 프로젝트/workspace의 기존 설정을 그대로 활용
2. **cwd 기반 설정 자동 로드** — `query(cwd="workspace경로")`가 해당 경로의 CLAUDE.md + .claude/* 를 계층적으로 로드
3. **PO가 dependency를 동적 판단** — 정적 DAG 없음. 매 요청마다 작업 내용을 분석하여 phases 결정
4. **Python은 비즈니스 로직을 모름** — cwd만 바꿔가며 query() 호출

## 구조

```
orchestrator/
├── __init__.py      # BASE path, extract_json 유틸리티
├── po.py            # PO: query(cwd=project/) → execution plan JSON
├── executor.py      # phase별 workspace query(cwd=workspace/) 실행
├── task_log.py      # 작업 로그 .tasks/{date}/{project}/{task_id}_{label}.md
├── server.py        # 진입점: 채널 라우팅, ConfirmGate, 전체 흐름
├── scripts/
│   └── cleanup.sh   # 기존 통신용 .tasks/ 파일 정리
└── tests/
    ├── test_executor.py
    ├── test_task_log.py
    └── test_server.py
```

## 설치

```bash
pip install claude-agent-sdk
```

## 실행

```python
import asyncio
from orchestrator.server import handle_request

result = asyncio.run(handle_request(
    user_message="new-place 서버에 health check API 추가해줘",
    channel="cli",
    callback_info={},
))
```

### ConfirmGate 사용

```python
from orchestrator.server import ConfirmGate

gate = ConfirmGate()
gate.create_request("req-1", "health check 추가", "works", {"bot_id": "..."})

# 사용자 confirm 후:
result = await gate.confirm("req-1")
```

## 테스트

```bash
python -m pytest orchestrator/tests/ -v
```

## 새 workspace 추가

workspace 폴더에 `CLAUDE.md` + `.claude/` 생성 → 끝.
PO가 `ls`와 CLAUDE.md 읽기를 통해 자동 발견한다.

## 기존 .tasks/ 정리

마이그레이션 완료 후:
```bash
# 먼저 dry-run (삭제 대상만 출력)
bash orchestrator/scripts/cleanup.sh /home1/irteam/naver/project/.tasks

# 확인 후 실제 삭제
bash orchestrator/scripts/cleanup.sh /home1/irteam/naver/project/.tasks --execute
```
