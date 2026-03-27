"""Post-setup runtime handoff for remote Workspace Orchestrator onboarding."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from orchestrator.setup_support import WorkspaceOrchestratorCandidate

POST_SETUP_CREDENTIALS_DIR = "remote-workspace-orchestrators"


def remote_workspace_orchestrator_credentials_root(archive_path: Path) -> Path:
    """Return the directory used for remote Workspace Orchestrator credentials."""
    return archive_path / POST_SETUP_CREDENTIALS_DIR


def format_selected_orchestrators(candidates: list[WorkspaceOrchestratorCandidate]) -> str:
    """Render selected Workspace Orchestrators for the post-setup prompt."""
    selected = [candidate for candidate in candidates if candidate.selected]
    if not selected:
        return "- (none selected)"

    lines: list[str] = []
    for candidate in selected:
        location = candidate.location or "local"
        line = f"- {candidate.orchestrator_id}: {candidate.relative_path} [{location}]"
        remote = candidate.remote or {}
        if location == "ssh":
            host = str(remote.get("host") or "").strip()
            user = str(remote.get("user") or "").strip()
            root_path = str(remote.get("root_path") or "").strip()
            extras = ", ".join(part for part in [f"user={user}" if user else "", f"host={host}" if host else "", f"root={root_path}" if root_path else ""] if part)
            if extras:
                line = f"{line} {extras}"
        elif location == "kubernetes":
            namespace = str(remote.get("namespace") or "").strip()
            pod = str(remote.get("pod") or "").strip()
            root_path = str(remote.get("root_path") or "").strip()
            extras = ", ".join(part for part in [f"namespace={namespace}" if namespace else "", f"pod={pod}" if pod else "", f"root={root_path}" if root_path else ""] if part)
            if extras:
                line = f"{line} {extras}"
        lines.append(line)
    return "\n".join(lines)


def render_post_setup_prompt(
    *,
    po_root: Path,
    archive_path: Path,
    default_runtime: str,
    workspace_orchestrator_candidates: list[WorkspaceOrchestratorCandidate],
) -> str:
    """Build the initial prompt for the post-setup runtime handoff."""
    credentials_root = remote_workspace_orchestrator_credentials_root(archive_path)
    selected_orchestrators = format_selected_orchestrators(workspace_orchestrator_candidates)
    return (
        f"You are continuing setup for the Project Orchestrator root at {po_root}.\n\n"
        f"The selected default runtime is `{default_runtime}`.\n"
        "Continue the setup as an interactive follow-up focused on remote Workspace Orchestrators.\n\n"
        "Your job:\n"
        "1. Ask the user whether they have any remote Workspace Orchestrators that should be connected now.\n"
        "2. Review the selected Workspace Orchestrators from the completed setup:\n"
        f"{selected_orchestrators}\n"
        "3. If the user wants a remote Workspace Orchestrator, collect only the SSH or Kubernetes access details needed to connect.\n"
        f"4. Write those connection details under {credentials_root}/<workspace-orchestrator-id>/credentials using `key : value` lines.\n"
        "5. Never print secret values back to the user after they are entered.\n"
        "6. Use `skills/setup-remote-project/SKILL.md` when the whole project or Workspace Orchestrator is remote.\n"
        "7. Use `skills/setup-remote-workspace/SKILL.md` when only one workspace under an otherwise local Workspace Orchestrator should run remotely.\n"
        "8. Install the remote listener in the remote Workspace Orchestrator directory and update `orchestrator.yaml` so the orchestrator can execute through it.\n"
        "9. Validate listener health before finishing.\n\n"
        "If the user has no remote Workspace Orchestrators to configure, say so clearly and stop."
    )


def build_post_setup_command(runtime: str, prompt: str) -> list[str]:
    """Return the interactive CLI command used for the post-setup handoff."""
    runtime_name = (runtime or "").strip().lower()
    if runtime_name == "claude":
        return ["claude", prompt]
    if runtime_name == "cursor":
        return ["cursor-agent", prompt]
    if runtime_name == "codex":
        return ["codex", prompt]
    if runtime_name == "opencode":
        return ["opencode", "--prompt", prompt, "."]
    raise ValueError(f"Unsupported runtime for post-setup handoff: {runtime}")


def launch_post_setup_runtime(
    *,
    runtime: str,
    po_root: Path,
    archive_path: Path,
    workspace_orchestrator_candidates: list[WorkspaceOrchestratorCandidate],
) -> None:
    """Launch the selected default runtime for remote Workspace Orchestrator follow-up."""
    runtime_name = (runtime or "").strip().lower()
    if not runtime_name:
        return

    command = build_post_setup_command(
        runtime_name,
        render_post_setup_prompt(
            po_root=po_root,
            archive_path=archive_path,
            default_runtime=runtime_name,
            workspace_orchestrator_candidates=workspace_orchestrator_candidates,
        ),
    )
    binary = command[0]
    if shutil.which(binary) is None:
        print(f"Post-setup handoff skipped: `{binary}` is not available on this machine.")
        return

    remote_workspace_orchestrator_credentials_root(archive_path).mkdir(parents=True, exist_ok=True)

    print()
    print(f"Opening {runtime_name} to continue remote Workspace Orchestrator setup...")
    print()

    proc = subprocess.run(command, cwd=str(po_root), check=False)
    if proc.returncode != 0:
        print()
        print(
            "Post-setup handoff exited with a non-zero status. "
            "Your setup files were already written, so you can rerun the runtime follow-up manually."
        )
