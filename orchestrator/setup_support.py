"""Helpers for setup discovery, config rendering, and installer bootstrap."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from orchestrator import BLOCKED_DIRS

PO_MARKERS = ("orchestrator.yaml", "orchestrator", "start-orchestrator.sh", "ARCHIVE", ".tasks")
CODE_MARKERS = (".git", "package.json", "pyproject.toml", "go.mod", "Cargo.toml", "requirements.txt")
WORKSPACE_BONUS_MARKERS = CODE_MARKERS + ("README.md",)
WORKSPACE_PENALTY_NAMES = {"docs", "scripts", "assets", "tmp", "node_modules", "dist", "build"}
SETUP_SUPPORT_DIRS = {"skills", "templates", "scripts"}
SETUP_EXCLUDED_DIRS = BLOCKED_DIRS | {"bridge", ".venv", "node_modules", "__pycache__"} | SETUP_SUPPORT_DIRS
DEFAULT_ROLE_RUNTIMES = {
    "router": "claude",
    "planner": "claude",
    "executor": "claude",
    "direct_handler": "claude",
    "repair": "claude",
}
RUNTIME_CHOICES = ("claude", "cursor", "codex", "opencode")
ORCHESTRATOR_APPENDIX_START = "<!-- PROJECT_ORCHESTRATOR_INTEGRATION:START -->"
ORCHESTRATOR_APPENDIX_END = "<!-- PROJECT_ORCHESTRATOR_INTEGRATION:END -->"


@dataclass(slots=True)
class FolderAnalysis:
    kind: str
    cwd: Path
    suggested_po_root: Path
    reasons: list[str] = field(default_factory=list)
    alternative_roots: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceCandidate:
    workspace_id: str
    relative_path: str
    score: int
    markers: list[str] = field(default_factory=list)
    selected: bool = True
    runtime: str = "claude"
    mode: str = "local"
    remote: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspaceOrchestratorCandidate:
    orchestrator_id: str
    relative_path: str
    score: int
    markers: list[str] = field(default_factory=list)
    selected: bool = True
    location: str = "local"
    remote: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class BinaryStatus:
    name: str
    available: bool
    path: str = ""
    version: str = ""
    details: str = ""


@dataclass(slots=True)
class EnvironmentReport:
    binaries: dict[str, BinaryStatus]
    codex_auth: str
    opencode_provider_count: int
    opencode_provider_status: str


@dataclass(slots=True)
class SetupSummary:
    po_root: Path
    archive_path: Path
    config_path: Path
    start_script_path: Path
    written_files: list[Path]
    workspace_lines: list[str]
    credential_lines: list[str]
    log_path: str


@dataclass(slots=True)
class SetupPathValidation:
    path: Path
    exists: bool
    looks_like_po_root: bool
    conflicts_with_invalid_target: bool
    error: str = ""
    summary: str = ""


def load_setup_config(po_root: Path) -> dict:
    """Load orchestrator.yaml from a candidate PO root."""
    config_path = po_root / "orchestrator.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_setup_input_path(raw: str, cwd: Path, default: Path) -> tuple[Path | None, str | None]:
    """Resolve a setup path input against cwd and the current default."""
    candidate = (raw or str(default)).strip()
    if not candidate:
        return None, "A directory path is required."

    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (cwd / path).resolve()
    else:
        path = path.resolve()

    if path.exists() and not path.is_dir():
        return None, f"Path is not a directory: {path}"
    return path, None


def validate_setup_target_path(path: Path, target: str) -> SetupPathValidation:
    """Validate a resolved setup path and describe how it will be used."""
    invalid_target_names = SETUP_EXCLUDED_DIRS | {"bridge"}
    if target == "archive":
        invalid_target_names = invalid_target_names - {"ARCHIVE"}
    conflict = path.name in invalid_target_names
    exists = path.exists()
    looks_like_po_root = exists and classify_current_folder(path).kind == "existing_po"

    summary = (
        f"Resolved {target} path: {path}\n"
        f"- Exists: {'yes' if exists else 'no (it will be created during setup)'}\n"
        f"- Looks like an existing Project Orchestrator root: {'yes' if looks_like_po_root else 'no'}\n"
        f"- Conflicts with an obvious invalid target: {'yes' if conflict else 'no'}"
    )

    if conflict:
        return SetupPathValidation(
            path=path,
            exists=exists,
            looks_like_po_root=looks_like_po_root,
            conflicts_with_invalid_target=True,
            error=(
                f"{path} is not a valid {target} target. "
                "Choose a project directory, not an internal support directory."
            ),
            summary=summary,
        )

    return SetupPathValidation(
        path=path,
        exists=exists,
        looks_like_po_root=looks_like_po_root,
        conflicts_with_invalid_target=False,
        summary=summary,
    )


def _is_ignored_workspace_reference(workspace_id: str, relative_path: str) -> bool:
    parts = [part for part in Path(relative_path).parts if part not in {".", ""}]
    leading = parts[0] if parts else relative_path.strip()
    return workspace_id in SETUP_SUPPORT_DIRS or leading in SETUP_SUPPORT_DIRS


def infer_workspace_orchestrator_path(relative_path: str) -> str:
    """Infer the Workspace Orchestrator directory that contains a workspace path."""
    path = Path(relative_path)
    parent = path.parent.as_posix()
    if parent == ".":
        return relative_path.strip()
    return parent


def candidates_from_config(config: dict) -> list[WorkspaceCandidate]:
    """Build setup candidates from an existing workspace registry."""
    candidates: list[WorkspaceCandidate] = []
    workspaces = config.get("workspaces", [])
    if not isinstance(workspaces, list):
        return candidates

    for entry in workspaces:
        if not isinstance(entry, dict):
            continue
        workspace_id = str(entry.get("id") or "").strip()
        relative_path = str(entry.get("path") or "").strip()
        if not workspace_id or not relative_path:
            continue
        if _is_ignored_workspace_reference(workspace_id, relative_path):
            continue
        wo = entry.get("wo", {}) or {}
        candidates.append(
            WorkspaceCandidate(
                workspace_id=workspace_id,
                relative_path=relative_path,
                score=100,
                markers=["configured"],
                selected=True,
                runtime=str(wo.get("runtime") or "claude"),
                mode=str(wo.get("mode") or "local"),
                remote=dict(wo.get("remote") or {}),
            )
        )
    return candidates


def orchestrator_candidates_from_config(config: dict) -> list[WorkspaceOrchestratorCandidate]:
    """Build Workspace Orchestrator candidates by grouping configured workspace paths."""
    orchestrators: list[WorkspaceOrchestratorCandidate] = []
    seen: set[str] = set()

    for workspace in candidates_from_config(config):
        relative_path = infer_workspace_orchestrator_path(workspace.relative_path)
        if not relative_path or relative_path in seen:
            continue
        seen.add(relative_path)
        remote_access = {}
        location = "local"
        if workspace.mode == "remote":
            remote_access = dict((workspace.remote or {}).get("access") or {})
            location = str(remote_access.get("method") or "local")
        orchestrators.append(
            WorkspaceOrchestratorCandidate(
                orchestrator_id=slugify_workspace_id(relative_path.replace("/", "-")),
                relative_path=relative_path,
                score=100,
                markers=["configured"],
                selected=True,
                location=location,
                remote=remote_access,
            )
        )

    return orchestrators


def merge_workspace_candidates(
    configured: list[WorkspaceCandidate],
    discovered: list[WorkspaceCandidate],
) -> list[WorkspaceCandidate]:
    """Prefer configured workspaces, then append any newly discovered ones."""
    merged: list[WorkspaceCandidate] = []
    seen: set[tuple[str, str]] = set()

    for candidate in [*configured, *discovered]:
        key = (candidate.workspace_id, candidate.relative_path)
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)

    return merged


def merge_workspace_orchestrator_candidates(
    configured: list[WorkspaceOrchestratorCandidate],
    discovered: list[WorkspaceOrchestratorCandidate],
) -> list[WorkspaceOrchestratorCandidate]:
    """Prefer configured Workspace Orchestrators, then append newly discovered ones."""
    merged: list[WorkspaceOrchestratorCandidate] = []
    seen: set[tuple[str, str]] = set()

    for candidate in [*configured, *discovered]:
        key = (candidate.orchestrator_id, candidate.relative_path)
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)

    return merged


def _visible_child_directories(path: Path) -> list[Path]:
    children: list[Path] = []
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in SETUP_EXCLUDED_DIRS:
            continue
        children.append(child)
    return children


def _marker_hits(path: Path, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if (path / marker).exists()]


def classify_current_folder(cwd: Path) -> FolderAnalysis:
    """Classify the current directory for setup defaults."""
    po_hits = _marker_hits(cwd, PO_MARKERS)
    code_hits = _marker_hits(cwd, CODE_MARKERS)
    visible_children = _visible_child_directories(cwd)

    if len(po_hits) >= 2:
        return FolderAnalysis(
            kind="existing_po",
            cwd=cwd,
            suggested_po_root=cwd,
            reasons=[f"PO markers found: {', '.join(po_hits)}"],
        )

    if code_hits and not po_hits:
        reasons = [f"Codebase markers found: {', '.join(code_hits)}"]
        alternatives = [cwd.parent] if cwd.parent != cwd else []
        return FolderAnalysis(
            kind="workspace_candidate",
            cwd=cwd,
            suggested_po_root=cwd.parent,
            reasons=reasons,
            alternative_roots=alternatives,
        )

    if len(visible_children) >= 2 and len(code_hits) <= 1:
        return FolderAnalysis(
            kind="new_po_candidate",
            cwd=cwd,
            suggested_po_root=cwd,
            reasons=[f"Found {len(visible_children)} visible child directories and weak code-root markers."],
        )

    alternatives = [cwd, cwd.parent] if cwd.parent != cwd else [cwd]
    return FolderAnalysis(
        kind="unknown",
        cwd=cwd,
        suggested_po_root=cwd,
        reasons=["Folder does not strongly match PO or workspace heuristics."],
        alternative_roots=alternatives,
    )


def slugify_workspace_id(name: str) -> str:
    """Normalize a directory name into a workspace identifier."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-._")
    return slug or "workspace"


def score_workspace_candidate(path: Path) -> tuple[int, list[str]]:
    """Score a directory as a workspace candidate."""
    score = 0
    markers: list[str] = []

    for marker in WORKSPACE_BONUS_MARKERS:
        if (path / marker).exists():
            markers.append(marker)
            score += 2 if marker != "README.md" else 1

    if path.name.lower() in WORKSPACE_PENALTY_NAMES:
        score -= 4
        markers.append(f"penalty:{path.name.lower()}")

    nested_dirs = len([child for child in path.iterdir() if child.is_dir() and not child.name.startswith(".")])
    if nested_dirs >= 2:
        score += 1

    return score, markers


def discover_workspace_candidates(po_root: Path, source_cwd: Path | None = None) -> list[WorkspaceCandidate]:
    """Discover immediate child workspace candidates for a PO root."""
    candidates: list[WorkspaceCandidate] = []
    source_cwd = source_cwd or po_root

    for child in _visible_child_directories(po_root):
        score, markers = score_workspace_candidate(child)
        relative_path = child.relative_to(po_root).as_posix()
        candidates.append(
            WorkspaceCandidate(
                workspace_id=slugify_workspace_id(relative_path.replace("/", "-")),
                relative_path=relative_path,
                score=score,
                markers=markers,
                selected=score >= 0,
            )
        )

    if not candidates and source_cwd.exists() and source_cwd != po_root:
        try:
            relative_path = source_cwd.relative_to(po_root).as_posix()
        except ValueError:
            return candidates
        score, markers = score_workspace_candidate(source_cwd)
        candidates.append(
            WorkspaceCandidate(
                workspace_id=slugify_workspace_id(source_cwd.name),
                relative_path=relative_path,
                score=score,
                markers=markers,
                selected=True,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.relative_path))
    return candidates


def discover_workspace_orchestrator_candidates(
    po_root: Path,
    source_cwd: Path | None = None,
) -> list[WorkspaceOrchestratorCandidate]:
    """Discover immediate child directories that can serve as Workspace Orchestrators."""
    candidates: list[WorkspaceOrchestratorCandidate] = []
    source_cwd = source_cwd or po_root

    for child in _visible_child_directories(po_root):
        score, markers = score_workspace_candidate(child)
        relative_path = child.relative_to(po_root).as_posix()
        candidates.append(
            WorkspaceOrchestratorCandidate(
                orchestrator_id=slugify_workspace_id(relative_path.replace("/", "-")),
                relative_path=relative_path,
                score=score,
                markers=markers,
                selected=score >= 0,
            )
        )

    if not candidates and source_cwd.exists() and source_cwd != po_root:
        try:
            relative_path = source_cwd.relative_to(po_root).as_posix()
        except ValueError:
            return candidates
        score, markers = score_workspace_candidate(source_cwd)
        candidates.append(
            WorkspaceOrchestratorCandidate(
                orchestrator_id=slugify_workspace_id(source_cwd.name),
                relative_path=relative_path,
                score=score,
                markers=markers or ["manual"],
                selected=True,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.relative_path))
    return candidates


def suggested_workspace_candidates(cwd: Path) -> list[WorkspaceCandidate]:
    """Return workspace candidates based on current-folder analysis."""
    analysis = classify_current_folder(cwd)
    if analysis.kind == "workspace_candidate" and analysis.suggested_po_root.exists():
        score, markers = score_workspace_candidate(cwd)
        return [
            WorkspaceCandidate(
                workspace_id=slugify_workspace_id(cwd.name),
                relative_path=cwd.relative_to(analysis.suggested_po_root).as_posix(),
                score=score,
                markers=markers,
                selected=True,
            )
        ]
    po_root = analysis.suggested_po_root
    configured = candidates_from_config(load_setup_config(po_root))
    discovered = discover_workspace_candidates(po_root, source_cwd=cwd)
    return merge_workspace_candidates(configured, discovered)


def suggested_workspace_candidates_for_root(
    cwd: Path,
    po_root: Path,
) -> list[WorkspaceCandidate]:
    """Return workspace candidates using an explicit PO root."""
    configured = candidates_from_config(load_setup_config(po_root))
    discovered = discover_workspace_candidates(po_root, source_cwd=cwd) if po_root.exists() else []
    if configured or discovered:
        return merge_workspace_candidates(configured, discovered)

    if cwd.exists() and cwd != po_root and cwd.is_dir():
        try:
            relative_path = cwd.relative_to(po_root).as_posix()
        except ValueError:
            return []
        score, markers = score_workspace_candidate(cwd)
        return [
            WorkspaceCandidate(
                workspace_id=slugify_workspace_id(cwd.name),
                relative_path=relative_path,
                score=score,
                markers=markers or ["manual"],
                selected=True,
            )
        ]
    return []


def suggested_workspace_orchestrator_candidates_for_root(
    cwd: Path,
    po_root: Path,
) -> list[WorkspaceOrchestratorCandidate]:
    """Return Workspace Orchestrator candidates using an explicit PO root."""
    configured = orchestrator_candidates_from_config(load_setup_config(po_root))
    discovered = discover_workspace_orchestrator_candidates(po_root, source_cwd=cwd) if po_root.exists() else []
    if configured or discovered:
        return merge_workspace_orchestrator_candidates(configured, discovered)

    if cwd.exists() and cwd != po_root and cwd.is_dir():
        try:
            relative_path = cwd.relative_to(po_root).as_posix()
        except ValueError:
            return []
        score, markers = score_workspace_candidate(cwd)
        return [
            WorkspaceOrchestratorCandidate(
                orchestrator_id=slugify_workspace_id(cwd.name),
                relative_path=relative_path,
                score=score,
                markers=markers or ["manual"],
                selected=True,
            )
        ]
    return []


def workspace_candidates_for_orchestrator(
    po_root: Path,
    orchestrator: WorkspaceOrchestratorCandidate,
    configured_workspaces: list[WorkspaceCandidate] | None = None,
) -> list[WorkspaceCandidate]:
    """Discover actual workspaces inside a selected Workspace Orchestrator directory."""
    configured_workspaces = configured_workspaces or []
    orchestrator_path = (po_root / orchestrator.relative_path).resolve()
    prefix = f"{orchestrator.relative_path}/"

    configured: list[WorkspaceCandidate] = []
    exact_configured = False
    for candidate in configured_workspaces:
        if candidate.relative_path == orchestrator.relative_path:
            configured.append(candidate)
            exact_configured = True
            continue
        if candidate.relative_path.startswith(prefix):
            configured.append(candidate)

    discovered: list[WorkspaceCandidate] = []
    if orchestrator_path.exists() and orchestrator_path.is_dir():
        for child in _visible_child_directories(orchestrator_path):
            score, markers = score_workspace_candidate(child)
            relative_path = child.relative_to(po_root).as_posix()
            discovered.append(
                WorkspaceCandidate(
                    workspace_id=slugify_workspace_id(relative_path.replace("/", "-")),
                    relative_path=relative_path,
                    score=score,
                    markers=markers,
                    selected=score >= 0,
                )
            )

        if not discovered and not exact_configured:
            score, markers = score_workspace_candidate(orchestrator_path)
            discovered.append(
                WorkspaceCandidate(
                    workspace_id=slugify_workspace_id(orchestrator.relative_path.replace("/", "-")),
                    relative_path=orchestrator.relative_path,
                    score=score,
                    markers=markers or ["self"],
                    selected=True,
                )
            )

    merged = merge_workspace_candidates(configured, discovered)
    merged.sort(key=lambda item: (-item.score, item.relative_path))
    return merged


def _run_command(args: list[str], cwd: Path | None = None, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _which_all(name: str) -> list[str]:
    path_value = os.environ.get("PATH", "")
    matches: list[str] = []
    for directory in path_value.split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            matches.append(str(candidate))
    return matches


def find_working_binary(name: str, version_args: list[str]) -> str | None:
    """Return the first executable path that successfully runs."""
    for candidate in _which_all(name):
        try:
            proc = _run_command([candidate] + version_args)
        except Exception:
            continue
        if proc.returncode == 0:
            return candidate
    return None


def _detect_binary(name: str, version_args: list[str]) -> BinaryStatus:
    path = find_working_binary(name, version_args) or shutil.which(name)
    if not path:
        return BinaryStatus(name=name, available=False, details="not found")
    try:
        proc = _run_command([path] + version_args)
        output = (proc.stdout or proc.stderr).strip().splitlines()
        version = output[0] if output else ""
        return BinaryStatus(name=name, available=proc.returncode == 0, path=path, version=version)
    except Exception as exc:  # pragma: no cover - defensive
        return BinaryStatus(name=name, available=True, path=path, details=str(exc))


def detect_environment(cwd: Path | None = None) -> EnvironmentReport:
    """Collect runtime/tooling availability for the setup screen."""
    cwd = cwd or Path.cwd()
    binaries = {
        "python": BinaryStatus(
            name="python",
            available=True,
            path=sys.executable,
            version=sys.version.split()[0],
        ),
        "node": _detect_binary("node", ["--version"]),
        "npm": _detect_binary("npm", ["--version"]),
        "claude": _detect_binary("claude", ["--version"]),
        "cursor": _detect_binary("cursor-agent", ["--version"]),
        "codex": _detect_binary("codex", ["--version"]),
        "opencode": _detect_binary("opencode", ["--version"]),
    }

    codex_auth = "codex unavailable"
    if binaries["codex"].available and binaries["codex"].path:
        try:
            proc = _run_command([binaries["codex"].path, "login", "status"], cwd=cwd)
            codex_auth = (proc.stdout or proc.stderr).strip() or f"exit={proc.returncode}"
        except Exception as exc:  # pragma: no cover - defensive
            codex_auth = f"status check failed: {exc}"

    provider_count = 0
    provider_status = "opencode unavailable"
    if binaries["opencode"].available and binaries["opencode"].path:
        try:
            proc = _run_command([binaries["opencode"].path, "providers", "list"], cwd=cwd)
            output = (proc.stdout or proc.stderr).strip()
            match = re.search(r"(\d+)\s+credentials", output)
            provider_count = int(match.group(1)) if match else 0
            provider_status = output.splitlines()[-1] if output else "providers unavailable"
        except Exception as exc:  # pragma: no cover - defensive
            provider_status = f"provider check failed: {exc}"

    return EnvironmentReport(
        binaries=binaries,
        codex_auth=codex_auth,
        opencode_provider_count=provider_count,
        opencode_provider_status=provider_status,
    )


def environment_summary(report: EnvironmentReport) -> str:
    """Render a short environment summary for TUI display."""
    lines = ["Environment checks:"]
    for key in ("python", "node", "npm", "claude", "cursor", "codex", "opencode"):
        status = report.binaries[key]
        mark = "OK" if status.available else "MISSING"
        details = status.version or status.details
        lines.append(f"- {status.name}: {mark} {details}".rstrip())
    lines.append(f"- codex auth: {report.codex_auth}")
    lines.append(f"- opencode providers: {report.opencode_provider_count} ({report.opencode_provider_status})")
    return "\n".join(lines)


def bootstrap_project_dependencies(po_root: Path, python_bin: str | None = None) -> list[str]:
    """Create a local venv, install Python deps, and install Node deps."""
    python_cmd = python_bin or sys.executable or shutil.which("python3") or "python3"
    venv_dir = po_root / ".venv"
    npm_bin = find_working_binary("npm", ["--version"]) or "npm"
    commands = [
        [python_cmd, "-m", "venv", str(venv_dir)],
        [str(venv_dir / "bin" / "pip"), "install", "-U", "pip"],
        [
            str(venv_dir / "bin" / "pip"),
            "install",
            "-r",
            str(po_root / "requirements.txt"),
            "-r",
            str(po_root / "requirements-dev.txt"),
        ],
        [npm_bin, "install"],
    ]

    outputs: list[str] = []
    for command in commands:
        proc = _run_command(command, cwd=po_root, timeout=600)
        output = (proc.stdout or proc.stderr).strip()
        outputs.append(f"$ {' '.join(command)}")
        if output:
            outputs.append(output.splitlines()[-1])
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{output}")
    return outputs


def build_workspace_entries(
    candidates: list[WorkspaceCandidate],
    default_executor_runtime: str,
) -> tuple[list[dict], list[dict]]:
    """Convert candidate rows into config workspaces and legacy remote entries."""
    workspaces: list[dict] = []
    legacy_remote: list[dict] = []

    for candidate in candidates:
        if not candidate.selected:
            continue

        runtime = candidate.runtime or default_executor_runtime
        wo: dict = {
            "runtime": runtime,
            "mode": candidate.mode or "local",
        }
        if wo["mode"] == "remote":
            remote = {"host": "", "port": 9100, "token": ""}
            remote.update(candidate.remote or {})
            if "port" in remote:
                try:
                    remote["port"] = int(remote["port"])
                except (TypeError, ValueError):
                    remote["port"] = 9100
            wo["remote"] = remote
            legacy_remote.append(
                {
                    "name": candidate.workspace_id,
                    "host": str(remote.get("host", "")),
                    "port": int(remote.get("port", 9100)),
                    "token": str(remote.get("token", "")),
                    "runtime": runtime,
                }
            )
        entry = {
            "id": candidate.workspace_id,
            "path": candidate.relative_path,
            "wo": wo,
        }
        workspaces.append(entry)

    return workspaces, legacy_remote


def render_orchestrator_config(
    po_root: Path,
    archive_path: Path,
    slack_enabled: bool,
    telegram_enabled: bool,
    default_runtime: str,
    executor_runtime: str,
    candidates: list[WorkspaceCandidate],
) -> str:
    """Render orchestrator.yaml content using the new workspace registry."""
    roles = dict(DEFAULT_ROLE_RUNTIMES)
    roles["router"] = default_runtime
    roles["planner"] = default_runtime
    roles["executor"] = executor_runtime
    workspaces, legacy_remote = build_workspace_entries(candidates, executor_runtime)

    config = {
        "root": str(po_root),
        "archive": str(archive_path),
        "runtime": {
            "default": default_runtime,
            "roles": roles,
        },
        "channels": {
            "slack": {"enabled": bool(slack_enabled)},
            "telegram": {"enabled": bool(telegram_enabled)},
        },
        "workspaces": workspaces,
        "remote_workspaces": legacy_remote,
    }
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=False)


def _render_template(path: Path, replacements: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def render_start_script(po_root: Path, python_bin: str | None = None) -> str:
    """Render start-orchestrator.sh from the template."""
    python_path = python_bin or str((po_root / ".venv" / "bin" / "python").resolve())
    template_path = Path(__file__).resolve().parents[1] / "templates" / "start-orchestrator.sh.template"
    return _render_template(
        template_path,
        {
            "PYTHON_BIN": python_path,
            "LOG_FILE": "/tmp/orchestrator-$(date +%Y%m%d).log",
        },
    )


def render_root_guidance(po_root: Path) -> tuple[str, str]:
    """Render runtime guidance files for the PO root."""
    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    replacements = {"PROJECT_NAME": po_root.name or "Project Orchestrator"}
    claude_md = _render_template(templates_dir / "CLAUDE.md.template", replacements)
    agents_md = _render_template(templates_dir / "AGENTS.md.template", replacements)
    return claude_md, agents_md


def render_orchestrator_integration_appendix(doc_kind: str) -> str:
    """Render a managed guidance block appended to existing agent markdown files."""
    if doc_kind == "claude":
        body = (
            "## Project Orchestrator Integration\n\n"
            "When Claude receives a task from the Project Orchestrator:\n\n"
            "- Treat the request as an orchestrated task scoped to this Project Orchestrator root or its assigned workspace.\n"
            "- Stay inside the assigned workspace boundary unless the instruction explicitly targets the Project Orchestrator root.\n"
            "- Use `orchestrator.yaml`, `AGENTS.md`, and the matching `skills/*/SKILL.md` files as the control-plane contract for setup, channels, and remote listener tasks.\n"
            "- Preserve cross-workspace contracts when a request affects related backend, frontend, or worker projects.\n"
        )
    else:
        body = (
            "## Project Orchestrator Integration\n\n"
            "When an agent receives a task from the Project Orchestrator:\n\n"
            "- Treat the request as an orchestrated task scoped to this Project Orchestrator root or its assigned workspace.\n"
            "- Stay inside the assigned workspace boundary unless the instruction explicitly targets the Project Orchestrator root.\n"
            "- Use `orchestrator.yaml` as the source of truth for workspace ids, runtime selection, and remote/local execution mode.\n"
            "- Read the matching `skills/*/SKILL.md` before changing setup, channel, or remote-listener files.\n"
            "- Preserve contracts across related workspaces instead of making isolated changes that break the wider project graph.\n"
        )
    return f"{ORCHESTRATOR_APPENDIX_START}\n{body}{ORCHESTRATOR_APPENDIX_END}\n"


def upsert_orchestrator_integration_appendix(text: str, appendix: str) -> str:
    """Append or replace the managed orchestrator integration block in a markdown file."""
    managed = appendix.strip()
    pattern = (
        rf"\n*{re.escape(ORCHESTRATOR_APPENDIX_START)}.*?"
        rf"{re.escape(ORCHESTRATOR_APPENDIX_END)}\n*"
    )
    if ORCHESTRATOR_APPENDIX_START in text and ORCHESTRATOR_APPENDIX_END in text:
        updated = re.sub(pattern, f"\n\n{managed}\n", text, flags=re.DOTALL)
        return updated.rstrip() + "\n"
    stripped = text.rstrip()
    if not stripped:
        return managed + "\n"
    return f"{stripped}\n\n{managed}\n"


def _write_guidance_file(path: Path, base_text: str, appendix: str) -> bool:
    """Create or update a guidance markdown file while preserving existing custom content."""
    if path.exists():
        current = path.read_text(encoding="utf-8")
        updated = upsert_orchestrator_integration_appendix(current, appendix)
        if updated == current:
            return False
        path.write_text(updated, encoding="utf-8")
        return True

    path.write_text(upsert_orchestrator_integration_appendix(base_text, appendix), encoding="utf-8")
    return True


def render_opencode_files() -> tuple[str, str]:
    """Render project-local OpenCode config and guidance stub."""
    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    opencode_json = _render_template(templates_dir / "opencode.json.template", {})
    opencode_readme = _render_template(templates_dir / "opencode-README.md.template", {})
    return opencode_json, opencode_readme


def render_credential_file(credentials: dict[str, str]) -> str:
    """Render a channel credential file using key : value lines."""
    lines = [f"{key} : {value}" for key, value in credentials.items() if value != ""]
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def should_initialize_opencode(
    default_runtime: str,
    executor_runtime: str,
    candidates: list[WorkspaceCandidate],
) -> bool:
    """Return True when setup should scaffold project-local OpenCode files."""
    if default_runtime == "opencode" or executor_runtime == "opencode":
        return True
    return any(candidate.selected and candidate.runtime == "opencode" for candidate in candidates)


def write_setup_files(
    po_root: Path,
    archive_path: Path,
    slack_enabled: bool,
    telegram_enabled: bool,
    default_runtime: str,
    executor_runtime: str,
    candidates: list[WorkspaceCandidate],
    slack_credentials: dict[str, str] | None = None,
    telegram_credentials: dict[str, str] | None = None,
    python_bin: str | None = None,
) -> SetupSummary:
    """Write orchestrator config, start script, and root guidance files."""
    po_root.mkdir(parents=True, exist_ok=True)
    archive_path.mkdir(parents=True, exist_ok=True)

    config_path = po_root / "orchestrator.yaml"
    start_script_path = po_root / "start-orchestrator.sh"
    config_text = render_orchestrator_config(
        po_root=po_root,
        archive_path=archive_path,
        slack_enabled=slack_enabled,
        telegram_enabled=telegram_enabled,
        default_runtime=default_runtime,
        executor_runtime=executor_runtime,
        candidates=candidates,
    )
    start_script = render_start_script(po_root=po_root, python_bin=python_bin)
    claude_md, agents_md = render_root_guidance(po_root)
    opencode_json, opencode_readme = render_opencode_files()
    claude_appendix = render_orchestrator_integration_appendix("claude")
    agents_appendix = render_orchestrator_integration_appendix("agents")

    config_path.write_text(config_text, encoding="utf-8")
    start_script_path.write_text(start_script, encoding="utf-8")
    start_script_path.chmod(start_script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    written_files = [config_path, start_script_path]
    credential_lines: list[str] = []
    claude_path = po_root / "CLAUDE.md"
    if _write_guidance_file(claude_path, claude_md, claude_appendix):
        written_files.append(claude_path)

    agents_path = po_root / "AGENTS.md"
    if _write_guidance_file(agents_path, agents_md, agents_appendix):
        written_files.append(agents_path)

    if should_initialize_opencode(default_runtime, executor_runtime, candidates):
        opencode_config_path = po_root / "opencode.json"
        if not opencode_config_path.exists():
            opencode_config_path.write_text(opencode_json, encoding="utf-8")
            written_files.append(opencode_config_path)

        opencode_dir = po_root / ".opencode"
        opencode_dir.mkdir(exist_ok=True)
        opencode_skills_dir = opencode_dir / "skills"
        opencode_skills_dir.mkdir(exist_ok=True)
        opencode_readme_path = opencode_dir / "README.md"
        if not opencode_readme_path.exists():
            opencode_readme_path.write_text(opencode_readme, encoding="utf-8")
            written_files.append(opencode_readme_path)

    if slack_enabled and slack_credentials:
        slack_dir = archive_path / "slack"
        slack_dir.mkdir(parents=True, exist_ok=True)
        slack_path = slack_dir / "credentials"
        slack_path.write_text(render_credential_file(slack_credentials), encoding="utf-8")
        written_files.append(slack_path)
        credential_lines.append(f"- slack: {slack_path}")

    if telegram_enabled and telegram_credentials:
        telegram_dir = archive_path / "telegram"
        telegram_dir.mkdir(parents=True, exist_ok=True)
        telegram_path = telegram_dir / "credentials"
        telegram_path.write_text(render_credential_file(telegram_credentials), encoding="utf-8")
        written_files.append(telegram_path)
        credential_lines.append(f"- telegram: {telegram_path}")

    workspace_lines = [
        f"- {candidate.workspace_id}: {candidate.relative_path} [{candidate.runtime}/{candidate.mode}]"
        for candidate in candidates
        if candidate.selected
    ]
    return SetupSummary(
        po_root=po_root,
        archive_path=archive_path,
        config_path=config_path,
        start_script_path=start_script_path,
        written_files=written_files,
        workspace_lines=workspace_lines,
        credential_lines=credential_lines,
        log_path="/tmp/orchestrator-$(date +%Y%m%d).log",
    )


def final_instruction_text(summary: SetupSummary) -> str:
    """Render the final run instructions shown after setup."""
    workspace_block = "\n".join(summary.workspace_lines) if summary.workspace_lines else "- (none selected)"
    credential_block = "\n".join(summary.credential_lines) if summary.credential_lines else "- (no channel credential files written)"
    return (
        "Setup complete.\n\n"
        f"PO root: {summary.po_root}\n"
        f"Archive: {summary.archive_path}\n"
        f"Config: {summary.config_path}\n"
        f"Start script: {summary.start_script_path}\n"
        f"Log file: {summary.log_path}\n\n"
        "How to run:\n"
        f"- foreground: cd {summary.po_root} && ./start-orchestrator.sh --fg\n"
        f"- background: cd {summary.po_root} && ./start-orchestrator.sh\n"
        f"- reconfigure: cd {summary.po_root} && python -m orchestrator.setup_tui\n\n"
        "Channel credentials saved:\n"
        f"{credential_block}\n\n"
        "Selected workspaces:\n"
        f"{workspace_block}"
    )
