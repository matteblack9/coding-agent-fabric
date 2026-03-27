"""Tests for post-setup runtime handoff."""

from __future__ import annotations

from pathlib import Path

from orchestrator.post_setup import (
    build_post_setup_command,
    launch_post_setup_runtime,
    remote_workspace_orchestrator_credentials_root,
    render_post_setup_prompt,
)
from orchestrator.setup_support import WorkspaceOrchestratorCandidate


def test_render_post_setup_prompt_mentions_archive_and_selected_orchestrators(tmp_path):
    archive_path = tmp_path / "ARCHIVE"
    prompt = render_post_setup_prompt(
        po_root=tmp_path,
        archive_path=archive_path,
        default_runtime="codex",
        workspace_orchestrator_candidates=[
            WorkspaceOrchestratorCandidate(
                orchestrator_id="site-api",
                relative_path="services/api",
                score=10,
                selected=True,
                location="ssh",
                remote={"host": "10.0.0.5", "user": "deploy", "root_path": "/srv/site-api"},
            )
        ],
    )

    assert str(remote_workspace_orchestrator_credentials_root(archive_path)) in prompt
    assert "site-api: services/api [ssh]" in prompt
    assert "Use `skills/setup-remote-project/SKILL.md`" in prompt
    assert "Use `skills/setup-remote-workspace/SKILL.md`" in prompt


def test_build_post_setup_command_matches_runtime_conventions():
    assert build_post_setup_command("claude", "hello") == ["claude", "hello"]
    assert build_post_setup_command("cursor", "hello") == ["cursor-agent", "hello"]
    assert build_post_setup_command("codex", "hello") == ["codex", "hello"]
    assert build_post_setup_command("opencode", "hello") == ["opencode", "--prompt", "hello", "."]


def test_launch_post_setup_runtime_creates_credentials_root_and_runs_runtime(monkeypatch, tmp_path):
    recorded: dict[str, object] = {}

    monkeypatch.setattr("orchestrator.post_setup.shutil.which", lambda _: "/usr/bin/codex")

    def fake_run(command, cwd, check):
        recorded["command"] = command
        recorded["cwd"] = cwd
        recorded["check"] = check

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("orchestrator.post_setup.subprocess.run", fake_run)

    launch_post_setup_runtime(
        runtime="codex",
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        workspace_orchestrator_candidates=[],
    )

    assert remote_workspace_orchestrator_credentials_root(tmp_path / "ARCHIVE").is_dir()
    assert recorded["command"][0] == "codex"
    assert recorded["cwd"] == str(tmp_path)
    assert recorded["check"] is False


def test_launch_post_setup_runtime_skips_when_runtime_binary_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("orchestrator.post_setup.shutil.which", lambda _: None)

    launch_post_setup_runtime(
        runtime="cursor",
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        workspace_orchestrator_candidates=[],
    )

    output = capsys.readouterr().out
    assert "Post-setup handoff skipped" in output
