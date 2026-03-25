"""Task log writer — records execution results to .tasks/{date}/{project}/."""

import shutil
from datetime import datetime
from pathlib import Path

from orchestrator import BASE

TASKS_DIR_NAME = ".tasks"
MAX_DATE_FOLDERS = 30


def _is_date_folder(name: str) -> bool:
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _enforce_retention(tasks_dir: Path) -> None:
    if not tasks_dir.exists():
        return

    date_folders = sorted(
        [d for d in tasks_dir.iterdir() if d.is_dir() and _is_date_folder(d.name)],
        key=lambda d: d.name,
    )

    while len(date_folders) > MAX_DATE_FOLDERS:
        oldest = date_folders.pop(0)
        shutil.rmtree(oldest)


def _determine_status(results: dict[str, dict]) -> str:
    has_fail = any(
        r.get("test_result") == "fail" or "error" in r for r in results.values()
    )
    all_fail = all(
        r.get("test_result") == "fail" or "error" in r for r in results.values()
    )

    if all_fail:
        return "failure"
    if has_fail:
        return "partial_failure"
    return "success"


async def write_task_log(
    task_id: str,
    task_label: str,
    project: str,
    channel: str,
    original_request: str,
    phases: list[list[str]],
    results: dict[str, dict],
    started_at: datetime,
    base_dir: Path | None = None,
) -> Path:
    """Write a markdown task log file and enforce retention."""
    base = base_dir or BASE
    tasks_dir = base / TASKS_DIR_NAME
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    log_dir = tasks_dir / date_str / project
    log_dir.mkdir(parents=True, exist_ok=True)

    time_prefix = now.strftime("%H%M")
    log_path = log_dir / f"{time_prefix}_{task_label}.md"
    status = _determine_status(results)

    lines = [
        "---",
        f"task_id: {task_id}",
        f"project: {project}",
        f"channel: {channel}",
        f"requested: {started_at.isoformat()}",
        f"completed: {now.isoformat()}",
        f"status: {status}",
        "---",
        "",
        "## Request",
        f"```\n{original_request}\n```",
        "",
        "## Execution Plan",
    ]

    for i, phase_workspaces in enumerate(phases, 1):
        ws_str = ", ".join(phase_workspaces)
        if i == 1:
            lines.append(f"- Phase {i}: {ws_str} (독립)")
        else:
            lines.append(f"- Phase {i}: {ws_str} (이전 phase 결과 반영)")

    lines.extend(["", "## Results"])

    for workspace, result in results.items():
        error = result.get("error")
        test_result = "fail" if error else result.get("test_result", "skip")
        lines.append(f"\n### {workspace} [{test_result}]")

        changed = result.get("changed_files", [])
        if changed:
            lines.append(f"- changed: {', '.join(changed)}")

        summary = result.get("summary", "")
        if summary:
            lines.append(f"\n#### Summary\n{summary}")
        else:
            lines.append("\n#### Summary\n(결과 없음)")

        downstream = result.get("downstream_context", "")
        if downstream:
            lines.append(f"- downstream: {downstream}")

        if error:
            lines.append(f"\n#### Error Detail")
            lines.append(f"```\n{error}\n```")

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _enforce_retention(tasks_dir)

    return log_path