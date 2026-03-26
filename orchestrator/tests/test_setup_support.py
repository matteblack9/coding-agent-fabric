"""Tests for setup discovery and config rendering."""

from pathlib import Path

from orchestrator.setup_support import (
    WorkspaceCandidate,
    classify_current_folder,
    final_instruction_text,
    render_orchestrator_config,
    write_setup_files,
)


def test_classify_existing_po(tmp_path):
    (tmp_path / "orchestrator.yaml").write_text("root: test\n")
    (tmp_path / "orchestrator").mkdir()

    analysis = classify_current_folder(tmp_path)

    assert analysis.kind == "existing_po"
    assert analysis.suggested_po_root == tmp_path


def test_classify_workspace_candidate(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}\n")

    analysis = classify_current_folder(tmp_path)

    assert analysis.kind == "workspace_candidate"
    assert analysis.suggested_po_root == tmp_path.parent


def test_render_config_contains_workspace_registry(tmp_path):
    config = render_orchestrator_config(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=True,
        telegram_enabled=False,
        default_runtime="claude",
        executor_runtime="codex",
        candidates=[
            WorkspaceCandidate(
                workspace_id="backend",
                relative_path="backend",
                score=4,
                runtime="codex",
                mode="local",
            ),
            WorkspaceCandidate(
                workspace_id="staging",
                relative_path="services/staging",
                score=4,
                runtime="opencode",
                mode="remote",
            ),
        ],
    )

    assert "runtime:" in config
    assert "executor: codex" in config
    assert "id: backend" in config
    assert "runtime: opencode" in config
    assert "remote_workspaces:" in config


def test_write_setup_files_creates_scripts_and_guidance(tmp_path):
    summary = write_setup_files(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=False,
        telegram_enabled=True,
        default_runtime="claude",
        executor_runtime="codex",
        candidates=[
            WorkspaceCandidate(
                workspace_id="backend",
                relative_path="backend",
                score=4,
                runtime="codex",
                mode="local",
            )
        ],
        python_bin="/usr/bin/python3",
    )

    assert summary.config_path.exists()
    assert summary.start_script_path.exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "opencode.json").exists()

    instructions = final_instruction_text(summary)
    assert "./start-orchestrator.sh --fg" in instructions
    assert "python -m orchestrator.setup_tui" in instructions


def test_write_setup_files_creates_opencode_files_when_selected(tmp_path):
    summary = write_setup_files(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=False,
        telegram_enabled=True,
        default_runtime="claude",
        executor_runtime="claude",
        candidates=[
            WorkspaceCandidate(
                workspace_id="staging",
                relative_path="services/staging",
                score=4,
                runtime="opencode",
                mode="local",
            )
        ],
        python_bin="/usr/bin/python3",
    )

    assert (tmp_path / "opencode.json").exists()
    assert (tmp_path / ".opencode" / "README.md").exists()
    assert (tmp_path / ".opencode" / "skills").is_dir()
    assert any(path.name == "opencode.json" for path in summary.written_files)


def test_write_setup_files_does_not_create_cursor_specific_files(tmp_path):
    summary = write_setup_files(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=False,
        telegram_enabled=True,
        default_runtime="claude",
        executor_runtime="cursor",
        candidates=[
            WorkspaceCandidate(
                workspace_id="frontend",
                relative_path="frontend",
                score=4,
                runtime="cursor",
                mode="local",
            )
        ],
        python_bin="/usr/bin/python3",
    )

    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "opencode.json").exists()
    assert not (tmp_path / ".opencode").exists()
    assert any(path.name == "AGENTS.md" for path in summary.written_files)
