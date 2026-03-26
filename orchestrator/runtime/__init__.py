"""Runtime-neutral execution layer for Claude, Cursor, Codex, and OpenCode."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from orchestrator import resolve_runtime_name
from orchestrator.runtime.bridge import get_bridge_daemon

logger = logging.getLogger(__name__)
CURSOR_CLI_TIMEOUT_SECONDS = 30 * 60


@dataclass(slots=True)
class RuntimeInvocation:
    role: str
    cwd: str
    prompt: str
    system_prompt: str | None = None
    runtime: str | None = None
    workspace_id: str | None = None
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    allowed_tools: list[str] | None = None
    setting_sources: list[str] | None = None
    permission_mode: str | None = None
    output_schema: dict | None = None
    sandbox_mode: str | None = None
    approval_policy: str | None = None
    network_access_enabled: bool | None = None
    skip_git_repo_check: bool = True
    additional_directories: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeExecution:
    runtime: str
    final_text: str
    items: list | None = None
    usage: dict | None = None
    raw: dict | None = None


async def execute_runtime(invocation: RuntimeInvocation) -> RuntimeExecution:
    runtime = invocation.runtime or resolve_runtime_name(
        invocation.role,
        workspace_id=invocation.workspace_id,
    )
    if runtime == "claude":
        return await _execute_claude(invocation)
    if runtime == "cursor":
        return await asyncio.to_thread(_execute_cursor, invocation)
    return await _execute_bridge(invocation, runtime)


async def _execute_claude(invocation: RuntimeInvocation) -> RuntimeExecution:
    options = ClaudeAgentOptions(
        cwd=invocation.cwd,
        system_prompt=invocation.system_prompt,
        max_turns=invocation.max_turns,
        allowed_tools=invocation.allowed_tools,
        setting_sources=invocation.setting_sources,
        permission_mode=invocation.permission_mode,
        model=invocation.model,
        effort=invocation.effort,
    )

    collected_texts: list[str] = []
    final_result: str | None = None
    async for message in query(prompt=invocation.prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    collected_texts.append(block.text)
        elif isinstance(message, ResultMessage) and message.result:
            final_result = message.result

    return RuntimeExecution(
        runtime="claude",
        final_text=final_result or (collected_texts[-1] if collected_texts else ""),
        items=collected_texts,
        raw={"messages": collected_texts, "result": final_result},
    )


async def _execute_bridge(
    invocation: RuntimeInvocation,
    runtime: str,
) -> RuntimeExecution:
    daemon = await get_bridge_daemon()
    result = await daemon.request(
        "run",
        {
            "runtime": runtime,
            "cwd": invocation.cwd,
            "prompt": invocation.prompt,
            "systemPrompt": invocation.system_prompt,
            "model": invocation.model,
            "reasoningEffort": invocation.effort,
            "outputSchema": invocation.output_schema,
            "sandboxMode": invocation.sandbox_mode,
            "approvalPolicy": invocation.approval_policy,
            "networkAccessEnabled": invocation.network_access_enabled,
            "skipGitRepoCheck": invocation.skip_git_repo_check,
            "additionalDirectories": invocation.additional_directories,
        },
    )
    return RuntimeExecution(
        runtime=runtime,
        final_text=result.get("finalText", ""),
        items=result.get("items"),
        usage=result.get("usage"),
        raw=result,
    )


def _combine_cli_prompt(system_prompt: str | None, prompt: str) -> str:
    """Flatten system + user prompts for CLIs without a dedicated system channel."""
    if not system_prompt:
        return prompt
    return (
        "# System Instructions\n"
        f"{system_prompt.strip()}\n\n"
        "# User Request\n"
        f"{prompt.strip()}"
    )


def extract_cursor_final_text(raw: str) -> tuple[str, list[dict]]:
    """Extract the final assistant text from Cursor CLI JSON output."""
    text = (raw or "").strip()
    if not text:
        return "", []

    payloads: list[dict] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            payloads = [parsed]
        elif isinstance(parsed, list):
            payloads = [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)

    if not payloads:
        return text, []

    for payload in reversed(payloads):
        if payload.get("is_error"):
            message = payload.get("error") or payload.get("message") or payload.get("result")
            raise RuntimeError(str(message or "Cursor CLI returned an error."))

        for key in ("result", "text", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), payloads

    return text, payloads


def _execute_cursor(invocation: RuntimeInvocation) -> RuntimeExecution:
    """Execute the task with the local Cursor CLI."""
    prompt = _combine_cli_prompt(invocation.system_prompt, invocation.prompt)
    command = [
        "cursor-agent",
        "--print",
        "--output-format",
        "json",
        "--force",
        prompt,
    ]

    try:
        proc = subprocess.run(
            command,
            cwd=invocation.cwd,
            capture_output=True,
            text=True,
            timeout=CURSOR_CLI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("cursor-agent not found. Install Cursor CLI first.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"cursor-agent timed out after {CURSOR_CLI_TIMEOUT_SECONDS // 60} minutes."
        ) from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    raw_output = stdout or stderr
    if proc.returncode != 0:
        message = stderr or stdout or f"cursor-agent failed ({proc.returncode})"
        raise RuntimeError(message)

    final_text, payloads = extract_cursor_final_text(raw_output)
    return RuntimeExecution(
        runtime="cursor",
        final_text=final_text,
        items=payloads,
        raw={"stdout": stdout, "stderr": stderr, "events": payloads},
    )
