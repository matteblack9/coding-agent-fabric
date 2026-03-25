"""Input sanitization and prompt injection defense for orchestrator."""

from pathlib import Path


def wrap_user_input(text: str, label: str = "user_message") -> str:
    """Wrap user input in XML tags to isolate it from system instructions.

    This creates a clear boundary between system prompts and user-controlled data,
    making it harder for injected instructions to be interpreted as system-level commands.
    """
    return f"<{label}>\n{text}\n</{label}>"


def validate_project_name(name: str, base_dir: Path) -> bool:
    """Validate that project name corresponds to a real directory and is not a sensitive path."""
    BLOCKED = {"ARCHIVE", ".tasks", "orchestrator", ".claude", ".git"}

    if name in BLOCKED:
        return False

    if "/" in name or "\\" in name or ".." in name:
        return False

    candidate = base_dir / name
    return candidate.is_dir()


def validate_workspace_name(name: str, project_dir: Path) -> bool:
    """Validate that workspace name corresponds to a real directory under the project."""
    BLOCKED = {".claude", ".git", ".tasks", "ARCHIVE"}

    if name in BLOCKED:
        return False

    if "/" in name or "\\" in name or ".." in name:
        return False

    candidate = project_dir / name
    return candidate.is_dir()


def sanitize_downstream_context(context: dict[str, str]) -> dict[str, str]:
    """Sanitize downstream context values to limit injection surface.

    Truncates excessively long values and strips suspicious patterns.
    """
    MAX_CONTEXT_LEN = 1000
    sanitized = {}
    for key, value in context.items():
        if not isinstance(value, str):
            value = str(value)
        sanitized[key] = value[:MAX_CONTEXT_LEN]
    return sanitized