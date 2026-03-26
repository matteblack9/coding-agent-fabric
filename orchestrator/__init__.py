"""Orchestrator shared config and JSON helpers."""

import json
import logging
import os
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BLOCKED_DIRS = {"ARCHIVE", ".tasks", "orchestrator", ".claude", ".opencode", ".git"}


def get_config_path() -> Path:
    """Return the active orchestrator config path."""
    override = os.environ.get("ORCHESTRATOR_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "orchestrator.yaml"


def _load_config() -> dict:
    """Load orchestrator.yaml from the configured project root."""
    config_path = get_config_path()
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


CONFIG = _load_config()
BASE = Path(CONFIG.get("root", str(Path(__file__).resolve().parent.parent)))
ARCHIVE_PATH = Path(CONFIG.get("archive", str(BASE / "ARCHIVE")))


def reload_config() -> dict:
    """Reload configuration from disk and refresh derived paths."""
    global CONFIG
    global BASE
    global ARCHIVE_PATH

    CONFIG = _load_config()
    BASE = Path(CONFIG.get("root", str(Path(__file__).resolve().parent.parent)))
    ARCHIVE_PATH = Path(CONFIG.get("archive", str(BASE / "ARCHIVE")))
    return CONFIG


def uses_workspace_registry() -> bool:
    """Return whether the explicit workspace registry is enabled."""
    return bool(CONFIG.get("workspaces"))


def configured_workspaces() -> list[dict]:
    """Return configured workspaces."""
    workspaces = CONFIG.get("workspaces", [])
    return workspaces if isinstance(workspaces, list) else []


def get_workspace_entry(workspace_id: str) -> dict | None:
    """Return a configured workspace entry by id."""
    for entry in configured_workspaces():
        if entry.get("id") == workspace_id:
            return entry
    return None


def resolve_workspace_path(
    project: str,
    workspace: str,
    base_dir: Path | None = None,
) -> Path:
    """Resolve workspace path from config registry or legacy directory layout."""
    base = base_dir or BASE
    if workspace == ".":
        return (base if project in ("", ".") else base / project).resolve()

    entry = get_workspace_entry(workspace)
    if entry:
        path = entry.get("path", workspace)
        path_obj = Path(path)
        resolved = (path_obj if path_obj.is_absolute() else base / path_obj).resolve()
        return resolved

    return (base / project / workspace).resolve()


def resolve_remote_workspace_config(workspace: str) -> dict | None:
    """Resolve remote workspace config from new or legacy schema."""
    entry = get_workspace_entry(workspace)
    if entry:
        wo = entry.get("wo", {}) or {}
        if wo.get("mode") == "remote":
            remote = dict(wo.get("remote", {}) or {})
            remote["runtime"] = wo.get("runtime")
            return remote

    for legacy in CONFIG.get("remote_workspaces", []):
        if legacy.get("name") == workspace:
            return legacy
    return None


def resolve_runtime_name(role: str, workspace_id: str | None = None) -> str:
    """Resolve runtime using workspace > role > global default > claude."""
    runtime_cfg = CONFIG.get("runtime", {}) or {}
    if workspace_id:
        entry = get_workspace_entry(workspace_id)
        if entry:
            wo_runtime = (((entry.get("wo") or {})).get("runtime"))
            if wo_runtime:
                return str(wo_runtime).strip().lower()

    role_runtime = ((runtime_cfg.get("roles") or {})).get(role)
    if role_runtime:
        return str(role_runtime).strip().lower()
    return str(runtime_cfg.get("default", "claude")).strip().lower()


def list_workspace_ids(base_dir: Path | None = None) -> list[str]:
    """List known workspaces from config registry or filesystem."""
    if uses_workspace_registry():
        return [entry["id"] for entry in configured_workspaces() if entry.get("id")]

    base = base_dir or BASE
    candidates = []
    for child in sorted(base.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or child.name in BLOCKED_DIRS or child.name.startswith("."):
            continue
        candidates.append(child.name)
    return candidates


def is_valid_workspace_identifier(
    workspace_id: str,
    project_dir: Path,
) -> bool:
    """Validate workspace id against registry or legacy filesystem layout."""
    if workspace_id in BLOCKED_DIRS or "/" in workspace_id or "\\" in workspace_id or ".." in workspace_id:
        return False
    if get_workspace_entry(workspace_id):
        return True
    candidate = project_dir / workspace_id
    return candidate.is_dir()


def extract_json(text: str) -> dict:
    """Extract JSON object from text, handling markdown code fences and mixed text.

    Tries multiple strategies:
    1. Direct JSON parse
    2. Markdown code fence extraction
    3. Brace-matching (tries all top-level {} pairs, not just the first)
    """
    text = text.strip()

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Markdown code fence
    for match in re.finditer(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL):
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue

    # Strategy 3: Find all top-level {} pairs and try each
    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and depth > 0:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidates.append(text[start : i + 1])
                start = -1

    # Try candidates from largest to smallest (largest is most likely the full response)
    for candidate in sorted(candidates, key=len, reverse=True):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"No valid JSON found in response (length={len(text)})")


async def repair_json(raw_text: str, expected_keys: list[str] | None = None) -> dict | None:
    """Last-resort: use haiku to extract JSON from a malformed response.

    Returns parsed dict on success, None on failure.
    """
    from orchestrator.runtime import RuntimeInvocation, execute_runtime

    keys_hint = ""
    if expected_keys:
        keys_hint = f"\nExpected top-level keys: {', '.join(expected_keys)}"

    system = (
        "You are a JSON extractor. Find and return the JSON object from the input text.\n"
        "- If the text contains valid JSON, extract it exactly.\n"
        "- If the JSON is malformed, infer the intent and restore it as valid JSON.\n"
        "- Output only the JSON. No explanation, no code fences, no quotes — pure JSON only.\n"
        f"{keys_hint}"
    )

    try:
        result = await execute_runtime(
            RuntimeInvocation(
                role="repair",
                cwd=str(BASE),
                prompt=raw_text[:4000],
                system_prompt=system,
                max_turns=1,
                permission_mode="bypassPermissions",
                model="haiku",
                sandbox_mode="read-only",
                approval_policy="never",
                network_access_enabled=False,
            )
        )
        if result.final_text:
            return extract_json(result.final_text)
    except Exception:
        logger.warning("repair_json failed", exc_info=True)

    return None
