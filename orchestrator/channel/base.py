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

CONFIRM_KEYWORDS = {"yes", "y", "ok", "confirm", "proceed"}
CANCEL_KEYWORDS = {"cancel", "no", "n"}


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

        # --- State: AWAITING_FOLLOWUP (check whether to end after task completion) ---
        if session.state == SessionState.AWAITING_FOLLOWUP:
            if text_lower in FOLLOWUP_END_KEYWORDS:
                await self._send_and_record(session, callback_info, "Session ended.")
                self._sessions.clear(source_key)
                return
            # Not ending — keep previous conversation context and handle follow-up request
            session.state = SessionState.IDLE

        # --- State: PENDING_EXECUTION_CONFIRM (waiting for execution plan confirmation) ---
        if session.state == SessionState.PENDING_EXECUTION_CONFIRM:
            if text_lower in CONFIRM_KEYWORDS:
                session.add_user_turn(user_text)
                await self._do_execute_plan(session, callback_info)
                return

            if text_lower in CANCEL_KEYWORDS:
                session.add_user_turn(user_text)
                session.pending_plan = None
                session.state = SessionState.IDLE
                await self._send_and_record(session, callback_info, "Cancelled.")
                return

            # Text other than confirm/cancel — discard current plan and treat as new request
            session.pending_plan = None
            session.state = SessionState.IDLE

        # --- State: PENDING_CONFIRM (waiting for confirm/cancel) ---
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
                await self._send_and_record(session, callback_info, "Cancelled.")
                return

            if pending_id:
                self._confirm_gate.remove(pending_id)
                session.pending_request_id = None
            session.state = SessionState.IDLE

        # --- State: IDLE → create new request ---
        session.add_user_turn(user_text)

        # Include previous conversation history as context if available (preserves follow-up context)
        context = session.to_context_string(max_turns=10)
        if len(session.turns) > 1 and context:
            refined_message = (
                f"[Previous conversation context]\n{context}\n\n"
                f"[Current request]\n{user_text}"
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
            f"[{request_id}] Is this correct?\n"
            f"> {user_text}\n\n"
            f'Reply "yes" to proceed or "cancel" to abort.'
        )
        await self._send_and_record(session, callback_info, confirm_msg)

    @staticmethod
    def _format_plan_for_confirm(plan_result: dict, request_id: str) -> str:
        """Format execution plan for user confirmation (2nd confirm)."""
        lines: list[str] = [f"`{request_id}` The following tasks will be executed:\n"]

        for plan in plan_result.get("plans", []):
            project = plan.get("project", "unknown")
            phases = plan.get("phases", [])
            tasks = plan.get("task_per_workspace", {})

            lines.append(f"*Project: {project}*")
            for i, phase_workspaces in enumerate(phases, 1):
                ws_names = ", ".join(phase_workspaces)
                parallel = " (parallel)" if len(phase_workspaces) > 1 else ""
                lines.append(f"Phase {i}: {ws_names}{parallel}")
                for ws in phase_workspaces:
                    task_desc = tasks.get(ws, "")
                    if task_desc:
                        short = task_desc[:120] + "..." if len(task_desc) > 120 else task_desc
                        lines.append(f"  - {ws}: {short}")
            lines.append("")

        lines.append('Do you want to proceed? ("yes" / "cancel")')
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
            await self._send_and_record(session, callback_info, "This request has already been processed.")
            session.state = SessionState.IDLE
            session.pending_request_id = None
            return

        raw_message = req.raw_message
        user_message = req.message

        session.pending_request_id = None
        session.state = SessionState.EXECUTING
        await self._send_and_record(
            session, callback_info, f"`{request_id}` Building execution plan..."
        )

        try:
            from orchestrator.server import plan_request

            plan_result = await plan_request(user_message, raw_message=raw_message)

            # clarification → wait again
            if plan_result.get("status") == "clarification_needed":
                msg = plan_result.get("message", "Additional information is required.")
                session.state = SessionState.IDLE
                await self._send_and_record(session, callback_info, f"`{request_id}` {msg}")
                return

            # direct_answer → forward immediately (no modification, no second confirmation needed)
            if plan_result.get("status") == "direct_answer":
                from orchestrator.server import to_slack_mrkdwn
                msg = to_slack_mrkdwn(plan_result.get("message", ""))
                formatted = (
                    f":speech_balloon: *Request*\n{raw_message}\n\n"
                    f"─────────────────────────\n\n"
                    f":clipboard: *Response*\n{msg}"
                )
                await self._send_and_record(session, callback_info, formatted)
                session.state = SessionState.AWAITING_FOLLOWUP
                await self._send_and_record(session, callback_info, "All done? (reply \"yes\" to end the session)")
                return

            # direct_request (wiki, jira, etc. — project-agnostic) → execute immediately
            if plan_result.get("status") == "direct_request":
                from orchestrator.server import execute_from_plan
                result = await execute_from_plan(
                    plan_result, self.channel_name, callback_info, request_id,
                )
                if result.get("status") == "direct_answer":
                    from orchestrator.server import to_slack_mrkdwn
                    msg = to_slack_mrkdwn(result.get("message", ""))
                    formatted = (
                        f":speech_balloon: *Request*\n{raw_message}\n\n"
                        f"─────────────────────────\n\n"
                        f":clipboard: *Response*\n{msg}"
                    )
                    await self._send_and_record(session, callback_info, formatted)
                session.state = SessionState.AWAITING_FOLLOWUP
                await self._send_and_record(session, callback_info, "All done? (reply \"yes\" to end the session)")
                return

            # planned (workspace modification tasks) → second confirmation required
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
                f":x: *Planning failed* `{request_id}`\n"
                f"```{error_summary}\n{error_detail}```\n"
                f"Try again or request something else."
            )

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
