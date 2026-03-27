"""Tests for setup discovery and config rendering."""

from pathlib import Path

from orchestrator.setup_support import (
    ORCHESTRATOR_APPENDIX_END,
    ORCHESTRATOR_APPENDIX_START,
    WorkspaceCandidate,
    classify_current_folder,
    final_instruction_text,
    render_orchestrator_config,
    resolve_setup_input_path,
    suggested_workspace_candidates,
    validate_setup_target_path,
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
                remote={
                    "host": "staging.internal",
                    "port": 9200,
                    "token": "abc123",
                    "access": {
                        "method": "kubernetes",
                        "namespace": "apps",
                        "pod": "staging-api-0",
                        "cwd": "/workspace/staging",
                    },
                },
            ),
        ],
    )

    assert "runtime:" in config
    assert "router: claude" in config
    assert "planner: claude" in config
    assert "executor: codex" in config
    assert "id: backend" in config
    assert "runtime: opencode" in config
    assert "host: staging.internal" in config
    assert "method: kubernetes" in config
    assert "remote_workspaces:" in config


def test_render_config_sets_router_and_planner_to_default_runtime(tmp_path):
    config = render_orchestrator_config(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=False,
        telegram_enabled=False,
        default_runtime="codex",
        executor_runtime="cursor",
        candidates=[],
    )

    assert "default: codex" in config
    assert "router: codex" in config
    assert "planner: codex" in config
    assert "executor: cursor" in config


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
    assert "Channel credentials saved:" in instructions


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


def test_write_setup_files_writes_channel_credentials_to_archive(tmp_path):
    summary = write_setup_files(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=True,
        telegram_enabled=True,
        default_runtime="claude",
        executor_runtime="claude",
        candidates=[],
        slack_credentials={
            "app_id": "A012345",
            "client_id": "123456.789012",
            "client_secret": "client-secret",
            "signing_secret": "signing-secret",
            "app_level_token": "xapp-1-xxx",
            "bot_token": "xoxb-xxx",
        },
        telegram_credentials={
            "bot_token": "123456:ABC-DEF1234",
            "allowed_users": "user1,user2",
        },
        python_bin="/usr/bin/python3",
    )

    slack_path = tmp_path / "ARCHIVE" / "slack" / "credentials"
    telegram_path = tmp_path / "ARCHIVE" / "telegram" / "credentials"
    assert slack_path.exists()
    assert telegram_path.exists()
    assert "client_secret : client-secret" in slack_path.read_text(encoding="utf-8")
    assert "bot_token : 123456:ABC-DEF1234" in telegram_path.read_text(encoding="utf-8")
    assert any("slack" in line for line in summary.credential_lines)
    assert any("telegram" in line for line in summary.credential_lines)


def test_write_setup_files_appends_orchestrator_block_to_existing_guidance(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Existing AGENTS\n\nTeam rules.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Existing CLAUDE\n\nClaude-specific notes.\n", encoding="utf-8")

    summary = write_setup_files(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=False,
        telegram_enabled=False,
        default_runtime="codex",
        executor_runtime="codex",
        candidates=[],
        python_bin="/usr/bin/python3",
    )

    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    claude_text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    assert "# Existing AGENTS" in agents_text
    assert "# Existing CLAUDE" in claude_text
    assert ORCHESTRATOR_APPENDIX_START in agents_text
    assert ORCHESTRATOR_APPENDIX_END in agents_text
    assert ORCHESTRATOR_APPENDIX_START in claude_text
    assert ORCHESTRATOR_APPENDIX_END in claude_text
    assert "When an agent receives a task from the Project Orchestrator" in agents_text
    assert "When Claude receives a task from the Project Orchestrator" in claude_text
    assert any(path.name == "AGENTS.md" for path in summary.written_files)
    assert any(path.name == "CLAUDE.md" for path in summary.written_files)


def test_write_setup_files_refreshes_managed_guidance_block_without_duplication(tmp_path):
    original = (
        "# Existing AGENTS\n\n"
        f"{ORCHESTRATOR_APPENDIX_START}\n"
        "old block\n"
        f"{ORCHESTRATOR_APPENDIX_END}\n"
    )
    (tmp_path / "AGENTS.md").write_text(original, encoding="utf-8")

    write_setup_files(
        po_root=tmp_path,
        archive_path=tmp_path / "ARCHIVE",
        slack_enabled=False,
        telegram_enabled=False,
        default_runtime="claude",
        executor_runtime="claude",
        candidates=[],
        python_bin="/usr/bin/python3",
    )

    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_text.count(ORCHESTRATOR_APPENDIX_START) == 1
    assert agents_text.count(ORCHESTRATOR_APPENDIX_END) == 1
    assert "old block" not in agents_text


def test_suggested_workspace_candidates_excludes_support_directories(tmp_path):
    (tmp_path / "orchestrator.yaml").write_text("root: test\n")
    (tmp_path / "orchestrator").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "package.json").write_text("{}\n")

    candidates = suggested_workspace_candidates(tmp_path)

    assert [candidate.relative_path for candidate in candidates] == ["backend"]


def test_suggested_workspace_candidates_prefers_existing_config(tmp_path):
    (tmp_path / "orchestrator").mkdir()
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "backend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "services" / "backend" / "package.json").write_text("{}\n")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "pyproject.toml").write_text("[project]\nname='frontend'\n")
    (tmp_path / "orchestrator.yaml").write_text(
        "workspaces:\n"
        "  - id: backend\n"
        "    path: services/backend\n"
        "    wo:\n"
        "      runtime: codex\n"
        "      mode: remote\n",
        encoding="utf-8",
    )

    candidates = suggested_workspace_candidates(tmp_path)

    assert candidates[0].workspace_id == "backend"
    assert candidates[0].runtime == "codex"
    assert candidates[0].mode == "remote"
    assert any(candidate.workspace_id == "frontend" for candidate in candidates)


def test_resolve_setup_input_path_supports_relative_paths(tmp_path):
    resolved, error = resolve_setup_input_path("./po-root", tmp_path, tmp_path / "default-po")

    assert error is None
    assert resolved == (tmp_path / "po-root").resolve()


def test_validate_setup_target_path_rejects_support_directories(tmp_path):
    invalid_path = tmp_path / "skills"

    validation = validate_setup_target_path(invalid_path, "orchestrator")

    assert validation.conflicts_with_invalid_target is True
    assert validation.error
    assert "invalid target" in validation.summary.lower()
