"""Behavior tests for the prompt-driven setup wizard."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText

from orchestrator.setup_support import BinaryStatus, EnvironmentReport, WorkspaceOrchestratorCandidate
from orchestrator.setup_tui import SetupWizard, WizardBackError, WizardOption


@dataclass
class PromptRecord:
    kind: str
    message: str
    title: str | None = None
    default: object | None = None
    options: list[str] | None = None


class FakePrompter:
    """Deterministic prompter for setup wizard tests."""

    def __init__(self, scripted: list[tuple[str, object]]) -> None:
        self.scripted = list(scripted)
        self.records: list[PromptRecord] = []

    def clear_screen(self) -> None:
        self.records.append(PromptRecord(kind="clear", message=""))

    def intro(self, title: str) -> None:
        self.records.append(PromptRecord(kind="intro", message=title))

    def _render_message(self, message) -> str:
        if isinstance(message, FormattedText):
            fragments = list(message)
        elif isinstance(message, list):
            fragments = message
        else:
            return str(message)

        parts: list[str] = []
        for style, text in fragments:
            if "choice-primary-highlighted" in style:
                parts.append(f"[hl]{text}[/hl]")
            else:
                parts.append(text)
        return "".join(parts)

    def note(self, message, title: str | None = None) -> None:
        self.records.append(PromptRecord(kind="note", message=self._render_message(message), title=title))

    def _format_option(self, option: WizardOption) -> str:
        label = f"[hl]{option.label}[/hl]" if option.highlight else option.label
        return label if not option.hint else f"{label} ({option.hint})"

    def _pop_script(self) -> tuple[str, object]:
        assert self.scripted, "No scripted prompt response left."
        return self.scripted.pop(0)

    def select(self, message: str, options: list[WizardOption], default: str | None = None) -> str:
        self.records.append(
            PromptRecord(
                kind="select",
                message=message,
                default=default,
                options=[self._format_option(option) for option in options],
            )
        )
        kind, value = self._pop_script()
        if kind == "back":
            raise WizardBackError()
        assert kind == "select"
        return str(value)

    def multiselect(self, message: str, options: list[WizardOption], defaults: list[str] | None = None) -> list[str]:
        self.records.append(
            PromptRecord(
                kind="multiselect",
                message=message,
                default=list(defaults or []),
                options=[self._format_option(option) for option in options],
            )
        )
        kind, value = self._pop_script()
        if kind == "back":
            raise WizardBackError()
        assert kind == "multiselect"
        return [str(item) for item in value]

    def text(self, message: str, default: str = "", validate=None) -> str:
        while True:
            self.records.append(PromptRecord(kind="text", message=message, default=default))
            kind, value = self._pop_script()
            if kind == "back":
                raise WizardBackError()
            assert kind == "text"
            answer = str(value)
            error = validate(answer) if validate else None
            if not error:
                return answer
            self.note(error, "Invalid input")

    def secret(self, message: str, default: str = "", validate=None) -> str:
        while True:
            self.records.append(PromptRecord(kind="secret", message=message, default=default))
            kind, value = self._pop_script()
            if kind == "back":
                raise WizardBackError()
            assert kind == "secret"
            answer = str(value)
            error = validate(answer) if validate else None
            if not error:
                return answer
            self.note(error, "Invalid input")

    def confirm(self, message: str, default: bool = True) -> bool:
        self.records.append(PromptRecord(kind="confirm", message=message, default=default))
        kind, value = self._pop_script()
        if kind == "back":
            raise WizardBackError()
        assert kind == "confirm"
        return bool(value)

    def outro(self, message: str) -> None:
        self.records.append(PromptRecord(kind="outro", message=message))

    def dump_text(self) -> str:
        lines: list[str] = []
        for record in self.records:
            lines.append(record.kind)
            if record.title:
                lines.append(record.title)
            lines.append(record.message)
            if record.options:
                lines.extend(record.options)
        return "\n".join(lines)


def fake_environment() -> EnvironmentReport:
    binaries = {
        "python": BinaryStatus(name="python", available=True, path="/usr/bin/python3", version="3.12.0"),
        "node": BinaryStatus(name="node", available=True, path="/usr/bin/node", version="v22.0.0"),
        "npm": BinaryStatus(name="npm", available=True, path="/usr/bin/npm", version="10.0.0"),
        "claude": BinaryStatus(name="claude", available=True, path="/usr/bin/claude", version="2.0.0"),
        "cursor": BinaryStatus(name="cursor-agent", available=True, path="/usr/bin/cursor-agent", version="1.0.0"),
        "codex": BinaryStatus(name="codex", available=True, path="/usr/bin/codex", version="0.116.0"),
        "opencode": BinaryStatus(name="opencode", available=True, path="/usr/bin/opencode", version="1.3.2"),
    }
    return EnvironmentReport(
        binaries=binaries,
        codex_auth="Logged in using ChatGPT",
        opencode_provider_count=1,
        opencode_provider_status="1 credentials",
    )


def test_setup_wizard_copy_is_english_only(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "none"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "continue"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    result = wizard.run()

    assert result == "cancelled"
    text = prompter.dump_text()
    assert "Project Orchestrator setup" in text
    assert "Code Agent" in text
    assert "Orchestrator path" in text
    assert "Workspace Orchestrator selection" in text
    assert "Workspace selection" in text
    assert "Final Confirmation" in text
    assert "Slack credentials" not in text
    assert "Telegram credentials" not in text
    assert "backend API changes, the frontend may need to change too" in text
    assert "Remove Workspace Orchestrator" not in text
    assert "Remove Workspace" not in text
    assert "Workspace Orchestrator ID:" not in text
    assert "Workspace ID:" not in text
    assert "Step (1/11)" in text
    assert "Step (11/11)" in text
    assert re.search(r"[가-힣]", text) is None


def test_setup_wizard_code_agent_seeds_default_and_executor_runtimes(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "cursor"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "none"),
            ("select", "cursor"),
            ("select", "cursor"),
            ("select", "continue"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    result = wizard.run()

    assert result == "cancelled"
    assert wizard.code_agent == "cursor"
    assert wizard.default_runtime == "cursor"
    assert wizard.executor_runtime == "cursor"
    default_runtime_prompt = next(
        record
        for record in prompter.records
        if record.kind == "select" and record.message.endswith("Select the default runtime")
    )
    executor_runtime_prompt = next(
        record
        for record in prompter.records
        if record.kind == "select" and record.message.endswith("Select the executor runtime")
    )
    assert default_runtime_prompt.default == "cursor"
    assert executor_runtime_prompt.default == "cursor"


def test_setup_wizard_accepts_relative_and_absolute_paths(tmp_path):
    archive_root = tmp_path / "shared-archive"
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "./custom-po"),
            ("text", str(archive_root)),
            ("select", "none"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "continue"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    wizard.run()

    assert wizard.po_root == (tmp_path / "custom-po").resolve()
    assert wizard.archive_path == archive_root.resolve()
    assert wizard.archive_path_is_manual is True


def test_setup_wizard_reprompts_invalid_orchestrator_path(tmp_path):
    (tmp_path / "skills").mkdir()
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "skills"),
            ("text", "./valid-po"),
            ("text", ""),
            ("select", "none"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "continue"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    wizard.run()

    assert wizard.po_root == (tmp_path / "valid-po").resolve()
    invalid_notes = [
        record.message
        for record in prompter.records
        if record.kind == "note" and record.title == "Invalid input"
    ]
    assert any("not a valid orchestrator target" in note for note in invalid_notes)


def test_setup_wizard_back_navigation_returns_to_previous_step(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "back"),
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "none"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "continue"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    result = wizard.run()

    assert result == "cancelled"
    step_one_notes = [
        record for record in prompter.records if record.kind == "note" and record.title == "Step (1/11) Current folder analysis"
    ]
    assert len(step_one_notes) == 2
    assert sum(1 for record in prompter.records if record.kind == "clear") >= 10


def test_setup_wizard_first_step_back_confirms_exit(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "back"),
            ("confirm", True),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    result = wizard.run()

    assert result == "cancelled"
    assert any(record.title == "Step (1/11) Exit setup" for record in prompter.records if record.kind == "note")


def test_setup_wizard_workspace_steps_use_parent_filtered_selection(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "none"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "add"),
            ("text", "site-api"),
            ("text", "services/api"),
            ("select", "local"),
            ("confirm", True),
            ("select", "add"),
            ("text", "site-web"),
            ("text", "services/web"),
            ("select", "local"),
            ("confirm", True),
            ("select", "continue"),
            ("select", "site-api"),
            ("select", "add"),
            ("text", "backend"),
            ("text", "backend"),
            ("select", "codex"),
            ("select", "local"),
            ("confirm", True),
            ("select", "done"),
            ("select", "site-web"),
            ("select", "add"),
            ("text", "frontend"),
            ("text", "frontend"),
            ("select", "claude"),
            ("select", "local"),
            ("confirm", True),
            ("select", "toggle"),
            ("multiselect", ["0"]),
            ("select", "confirm"),
            ("select", "done"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    wizard.run()

    assert len(wizard.workspace_orchestrator_candidates) == 2
    assert len(wizard.workspace_candidates) == 2
    assert wizard.active_workspace_orchestrator_id == "site-web"
    workspace_multiselect_prompt = next(
        record
        for record in prompter.records
        if record.kind == "multiselect" and record.message.endswith("Select the workspace entries that should stay enabled")
    )
    assert workspace_multiselect_prompt.options == [
        "[hl]frontend[/hl] (Path: frontend | claude, local, local, selected)"
    ]
    parent_select_prompt = next(
        record
        for record in prompter.records
        if record.kind == "select"
        and record.message.endswith("Choose a Workspace Orchestrator to manage, or continue to final confirmation")
    )
    assert parent_select_prompt.options is not None
    assert "[hl]site-api[/hl] (Environment: local)" in parent_select_prompt.options
    assert "[hl]site-web[/hl] (Environment: local)" in parent_select_prompt.options
    assert all("Workspace Orchestrator ID:" not in option for option in parent_select_prompt.options)
    assert all("Directory:" not in option for option in parent_select_prompt.options)
    step_nine_action_prompt = next(
        record
        for record in prompter.records
        if record.kind == "select" and record.message.endswith("Choose a Workspace Orchestrator action")
    )
    assert step_nine_action_prompt.options is not None
    assert all("Remove Workspace Orchestrator" not in option for option in step_nine_action_prompt.options)
    workspace_action_prompt = next(
        record
        for record in prompter.records
        if record.kind == "select" and record.message.endswith("Choose a workspace action")
    )
    assert workspace_action_prompt.options is not None
    assert all("Remove Workspace" not in option for option in workspace_action_prompt.options)
    summary_note = next(
        record
        for record in prompter.records
        if record.kind == "note"
        and record.title == "Current entries"
        and "[hl]site-api[/hl]" in record.message
        and "[hl]site-web[/hl]" in record.message
    )
    assert "[hl]site-web[/hl]" in summary_note.message
    workspace_note = next(
        record
        for record in prompter.records
        if record.kind == "note" and record.title == "Current entries" and "[hl]frontend[/hl]" in record.message
    )
    assert "[hl]frontend[/hl]" in workspace_note.message


def test_setup_wizard_discovered_workspaces_inherit_executor_runtime(tmp_path):
    po_root = tmp_path / "po-root"
    (po_root / "site" / "backend").mkdir(parents=True)
    (po_root / "site" / "backend" / "package.json").write_text("{}\n")

    wizard = SetupWizard(cwd=tmp_path, prompter=FakePrompter([]), environment=fake_environment())
    wizard.po_root = po_root
    wizard.executor_runtime = "codex"
    wizard.workspace_orchestrator_candidates = [
        WorkspaceOrchestratorCandidate(
            orchestrator_id="site",
            relative_path="site",
            score=10,
            markers=["manual"],
            selected=True,
            location="local",
        )
    ]

    candidates = wizard._resolve_workspace_candidates()

    assert len(candidates) == 1
    assert candidates[0].workspace_id == "site-backend"
    assert candidates[0].runtime == "codex"


def test_setup_wizard_supports_remote_workspace_orchestrators_and_workspaces(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "none"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "add"),
            ("text", "staging"),
            ("text", "staging"),
            ("select", "ssh"),
            ("text", "10.0.0.5"),
            ("text", "deploy"),
            ("text", ""),
            ("text", "/srv/site"),
            ("confirm", True),
            ("select", "continue"),
            ("select", "staging"),
            ("select", "add"),
            ("text", "backend"),
            ("text", "backend"),
            ("select", "codex"),
            ("text", "10.0.0.5"),
            ("text", "9200"),
            ("text", "secret"),
            ("text", "/srv/site/backend"),
            ("confirm", True),
            ("select", "done"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    wizard.run()

    assert len(wizard.workspace_orchestrator_candidates) == 1
    orchestrator = wizard.workspace_orchestrator_candidates[0]
    assert orchestrator.orchestrator_id == "staging"
    assert orchestrator.location == "ssh"
    assert orchestrator.remote["host"] == "10.0.0.5"
    assert orchestrator.remote["user"] == "deploy"
    assert orchestrator.remote["root_path"] == "/srv/site"

    assert len(wizard.workspace_candidates) == 1
    workspace = wizard.workspace_candidates[0]
    assert workspace.workspace_id == "backend"
    assert workspace.relative_path == "staging/backend"
    assert workspace.mode == "remote"
    assert workspace.remote["host"] == "10.0.0.5"
    assert workspace.remote["port"] == 9200
    assert workspace.remote["token"] == "secret"
    assert workspace.remote["access"]["method"] == "ssh"
    assert workspace.remote["access"]["cwd"] == "/srv/site/backend"


def test_setup_wizard_writes_files_under_manual_root(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "codex"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "slack"),
            ("secret", "A012345"),
            ("secret", "123456.789012"),
            ("secret", "client-secret"),
            ("secret", "signing-secret"),
            ("secret", "xapp-1-xxx"),
            ("secret", "xoxb-xxx"),
            ("select", "codex"),
            ("select", "codex"),
            ("select", "add"),
            ("text", "site"),
            ("text", "site"),
            ("select", "local"),
            ("confirm", True),
            ("select", "continue"),
            ("select", "site"),
            ("select", "add"),
            ("text", "backend"),
            ("text", "backend"),
            ("select", "codex"),
            ("select", "local"),
            ("confirm", True),
            ("select", "done"),
            ("select", "continue"),
            ("confirm", True),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    result = wizard.run()

    po_root = (tmp_path / "po-root").resolve()
    assert result == "success"
    assert wizard.summary is not None
    assert wizard.summary.po_root == po_root
    assert (po_root / "orchestrator.yaml").exists()
    assert (po_root / "start-orchestrator.sh").exists()
    assert (po_root / "AGENTS.md").exists()
    assert (po_root / "CLAUDE.md").exists()
    assert (po_root / "ARCHIVE" / "slack" / "credentials").exists()


def test_setup_wizard_collects_masked_channel_credentials(tmp_path):
    prompter = FakePrompter(
        [
            ("select", "continue"),
            ("select", "continue"),
            ("select", "claude"),
            ("text", "./po-root"),
            ("text", ""),
            ("select", "both"),
            ("secret", "A012345"),
            ("secret", "123456.789012"),
            ("secret", "client-secret"),
            ("secret", "signing-secret"),
            ("secret", "xapp-1-xxx"),
            ("secret", "xoxb-xxx"),
            ("secret", "123456:ABC-DEF1234"),
            ("secret", "user1,user2"),
            ("select", "claude"),
            ("select", "claude"),
            ("select", "continue"),
            ("select", "continue"),
            ("confirm", False),
            ("select", "cancel"),
        ]
    )
    wizard = SetupWizard(cwd=tmp_path, prompter=prompter, environment=fake_environment())

    result = wizard.run()

    assert result == "cancelled"
    assert wizard.slack_credentials["client_secret"] == "client-secret"
    assert wizard.telegram_credentials["bot_token"] == "123456:ABC-DEF1234"
    secret_prompts = [record.message for record in prompter.records if record.kind == "secret"]
    assert any(message.endswith("Slack client_secret") for message in secret_prompts)
    assert any(message.endswith("Telegram bot_token") for message in secret_prompts)
