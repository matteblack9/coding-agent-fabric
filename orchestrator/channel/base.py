"""Base channel adapter: shared confirm/cancel flow + session + user text refinement."""

from __future__ import annotations

import logging
import traceback
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TYPE_CHECKING

from orchestrator.channel.session import (
    FOLLOWUP_END_KEYWORDS,
    Session,
    SessionState,
    SessionStore,
)

if TYPE_CHECKING:
    from orchestrator.server import ConfirmGate

logger = logging.getLogger(__name__)

CONFIRM_KEYWORDS = {"확인", "진행", "yes", "y", "ok", "ㅇㅇ", "네", "ㄱㄱ", "ㄱ"}
CANCEL_KEYWORDS = {"취소", "cancel", "no", "n", "아니", "ㄴㄴ", "ㄴ"}


def load_credential_file(path: Path) -> dict[str, str]:
    """Parse a key : value credential file into a dict."""
    data: dict[str, str] = {}
    for line in path.read_text().strip().splitlines():
        if " : " not in line:
            continue
        key, value = line.split(" : ", 1)
        data[key.strip()] = value.strip()
    return data


def split_message(text: str, max_len: int = 2000) -> list[str]:
    """Split long messages at newlines to stay under max_len."""
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_idx = remaining.rfind("\n", 0, max_len)
        if split_idx == -1 or split_idx < max_len // 2:
            split_idx = max_len
        chunks.append(remaining[:split_idx])
        remaining = remaining[split_idx:].lstrip("\n")
    return chunks


class BaseChannel(ABC):
    """Abstract base for channel adapters with shared session + confirm/cancel flow."""

    channel_name: str  # "slack" or "telegram"

    def __init__(self, confirm_gate: ConfirmGate) -> None:
        self._confirm_gate = confirm_gate
        self._sessions = SessionStore()

    @abstractmethod
    async def _send(self, callback_info: Any, text: str) -> None:
        """Send a message back to the user. Subclasses implement transport."""

    async def _send_and_record(self, session: Session, callback_info: Any, text: str) -> None:
        """Send a message and record it as an assistant turn in the session."""
        try:
            await self._send(callback_info, text)
        except Exception:
            logger.exception("Failed to send message via %s", self.channel_name)
        session.add_assistant_turn(text)

    async def _handle_text(
        self,
        user_text: str,
        source_key: str,
        callback_info: dict,
    ) -> None:
        """Session-aware confirm/cancel/new-request flow."""
        if not user_text:
            return

        session = self._sessions.get_or_create(source_key)
        text_lower = user_text.lower()

        # --- State: AWAITING_FOLLOWUP (작업 완료 후 종료 확인) ---
        if session.state == SessionState.AWAITING_FOLLOWUP:
            if text_lower in FOLLOWUP_END_KEYWORDS:
                await self._send_and_record(session, callback_info, "세션을 종료합니다.")
                self._sessions.clear(source_key)
                return
            # 종료하지 않음 → 이전 대화 컨텍스트 유지하고 후속 요청 처리
            session.state = SessionState.IDLE

        # --- State: PENDING_EXECUTION_CONFIRM (실행 계획 확인 대기) ---
        if session.state == SessionState.PENDING_EXECUTION_CONFIRM:
            if text_lower in CONFIRM_KEYWORDS:
                session.add_user_turn(user_text)
                await self._do_execute_plan(session, callback_info)
                return

            if text_lower in CANCEL_KEYWORDS:
                session.add_user_turn(user_text)
                session.pending_plan = None
                session.state = SessionState.IDLE
                await self._send_and_record(session, callback_info, "취소했습니다.")
                return

            # 확인/취소 외 텍스트 → 현재 계획 폐기, 새 요청으로 처리
            session.pending_plan = None
            session.state = SessionState.IDLE

        # --- State: PENDING_CONFIRM (확인/취소 대기) ---
        if session.state == SessionState.PENDING_CONFIRM:
            pending_id = session.pending_request_id

            if pending_id and text_lower in CONFIRM_KEYWORDS:
                session.add_user_turn(user_text)
                await self._do_confirm(session, pending_id, callback_info)
                return

            if pending_id and text_lower in CANCEL_KEYWORDS:
                session.add_user_turn(user_text)
                self._confirm_gate.remove(pending_id)
                session.pending_request_id = None
                session.state = SessionState.IDLE
                await self._send_and_record(session, callback_info, "취소했습니다.")
                return

            if pending_id:
                self._confirm_gate.remove(pending_id)
                session.pending_request_id = None
            session.state = SessionState.IDLE

        # --- State: IDLE → 새 요청 생성 ---
        session.add_user_turn(user_text)

        # 이전 대화 이력이 있으면 컨텍스트로 포함 (후속 요청에서 맥락 유지)
        context = session.to_context_string(max_turns=10)
        if len(session.turns) > 1 and context:
            refined_message = (
                f"[이전 대화 맥락]\n{context}\n\n"
                f"[현재 요청]\n{user_text}"
            )
        else:
            refined_message = user_text

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

        confirm_msg = (
            f"[{request_id}] 이렇게 이해했는데 맞나요?\n"
            f"> {user_text}\n\n"
            f'진행하려면 "확인", 취소하려면 "취소"를 입력해주세요.'
        )
        await self._send_and_record(session, callback_info, confirm_msg)

    @staticmethod
    def _format_plan_for_confirm(plan_result: dict, request_id: str) -> str:
        """Format execution plan for user confirmation (2nd confirm)."""
        lines: list[str] = [f"`{request_id}` 다음 작업을 수행합니다:\n"]

        for plan in plan_result.get("plans", []):
            project = plan.get("project", "unknown")
            phases = plan.get("phases", [])
            tasks = plan.get("task_per_workspace", {})

            lines.append(f"*프로젝트: {project}*")
            for i, phase_workspaces in enumerate(phases, 1):
                ws_names = ", ".join(phase_workspaces)
                parallel = " (병렬)" if len(phase_workspaces) > 1 else ""
                lines.append(f"Phase {i}: {ws_names}{parallel}")
                for ws in phase_workspaces:
                    task_desc = tasks.get(ws, "")
                    if task_desc:
                        short = task_desc[:120] + "..." if len(task_desc) > 120 else task_desc
                        lines.append(f"  - {ws}: {short}")
            lines.append("")

        lines.append('진행하시겠습니까? ("확인" / "취소")')
        return "\n".join(lines)

    async def _do_confirm(
        self,
        session: Session,
        request_id: str,
        callback_info: dict,
    ) -> None:
        """Phase 1: plan request → show plan → ask for execution confirmation."""
        # Atomic pop: get_pending + remove in one step
        req = self._confirm_gate.remove(request_id)
        if req is None:
            await self._send_and_record(session, callback_info, "이미 처리된 요청입니다.")
            session.state = SessionState.IDLE
            session.pending_request_id = None
            return

        raw_message = req.raw_message
        user_message = req.message

        session.pending_request_id = None
        session.state = SessionState.EXECUTING
        await self._send_and_record(
            session, callback_info, f"`{request_id}` 실행 계획 수립 중..."
        )

        try:
            from orchestrator.server import plan_request

            plan_result = await plan_request(user_message, raw_message=raw_message)

            # clarification → 다시 대기
            if plan_result.get("status") == "clarification_needed":
                msg = plan_result.get("message", "추가 정보가 필요합니다.")
                session.state = SessionState.IDLE
                await self._send_and_record(session, callback_info, f"`{request_id}` {msg}")
                return

            # direct_answer → 바로 전달 (수정 없음, 2차 확인 불필요)
            if plan_result.get("status") == "direct_answer":
                from orchestrator.server import to_slack_mrkdwn
                msg = to_slack_mrkdwn(plan_result.get("message", ""))
                formatted = (
                    f":speech_balloon: *요청 사항*\n{raw_message}\n\n"
                    f"─────────────────────────\n\n"
                    f":clipboard: *응답*\n{msg}"
                )
                await self._send_and_record(session, callback_info, formatted)
                session.state = SessionState.AWAITING_FOLLOWUP
                await self._send_and_record(session, callback_info, "작업을 끝낼까요?")
                return

            # direct_request (wiki, jira 등 프로젝트 무관) → 바로 실행
            if plan_result.get("status") == "direct_request":
                from orchestrator.server import execute_from_plan
                result = await execute_from_plan(
                    plan_result, self.channel_name, callback_info, request_id,
                )
                if result.get("status") == "direct_answer":
                    from orchestrator.server import to_slack_mrkdwn
                    msg = to_slack_mrkdwn(result.get("message", ""))
                    formatted = (
                        f":speech_balloon: *요청 사항*\n{raw_message}\n\n"
                        f"─────────────────────────\n\n"
                        f":clipboard: *응답*\n{msg}"
                    )
                    await self._send_and_record(session, callback_info, formatted)
                session.state = SessionState.AWAITING_FOLLOWUP
                await self._send_and_record(session, callback_info, "작업을 끝낼까요?")
                return

            # planned (workspace 수정 작업) → 2차 확인 필요
            if plan_result.get("status") == "planned":
                session.pending_plan = {
                    **plan_result,
                    "request_id": request_id,
                    "callback_info": {**callback_info},
                    "raw_message": raw_message,
                }
                plan_msg = self._format_plan_for_confirm(plan_result, request_id)
                session.state = SessionState.PENDING_EXECUTION_CONFIRM
                await self._send_and_record(session, callback_info, plan_msg)
                return

        except Exception as exc:
            logger.exception("plan_request failed for %s", request_id)
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            error_summary = f"{type(exc).__name__}: {exc}"
            error_detail = "".join(tb[-3:])

            session.state = SessionState.AWAITING_FOLLOWUP

            await self._send_and_record(
                session, callback_info,
                f":x: *계획 수립 실패* `{request_id}`\n"
                f"