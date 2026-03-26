"""Textual setup wizard for Project Orchestrator configuration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Input, Select, Static

from orchestrator.setup_support import (
    EnvironmentReport,
    WorkspaceCandidate,
    bootstrap_project_dependencies,
    classify_current_folder,
    detect_environment,
    environment_summary,
    final_instruction_text,
    suggested_workspace_candidates,
    write_setup_files,
)

RUNTIME_OPTIONS = [("claude", "claude"), ("cursor", "cursor"), ("codex", "codex"), ("opencode", "opencode")]
MODE_OPTIONS = [("local", "local"), ("remote", "remote")]


class WorkspaceRow(Static):
    """Single editable workspace/WO row."""

    def __init__(self, candidate: WorkspaceCandidate) -> None:
        super().__init__(classes="workspace-row")
        self.candidate = candidate

    def compose(self) -> ComposeResult:
        markers = ", ".join(self.candidate.markers) if self.candidate.markers else "no markers"
        with Vertical():
            with Horizontal(classes="workspace-fields"):
                yield Checkbox("include", value=self.candidate.selected, classes="ws-include")
                yield Input(value=self.candidate.workspace_id, placeholder="workspace id", classes="ws-id")
                yield Input(value=self.candidate.relative_path, placeholder="relative path", classes="ws-path")
                yield Select(options=RUNTIME_OPTIONS, value=self.candidate.runtime, classes="ws-runtime")
                yield Select(options=MODE_OPTIONS, value=self.candidate.mode, classes="ws-mode")
            yield Static(
                f"score={self.candidate.score} | markers={markers}",
                classes="workspace-meta",
            )

    def as_candidate(self) -> WorkspaceCandidate:
        include = self.query_one(".ws-include", Checkbox).value
        workspace_id = self.query_one(".ws-id", Input).value.strip() or self.candidate.workspace_id
        relative_path = self.query_one(".ws-path", Input).value.strip() or self.candidate.relative_path
        runtime = str(self.query_one(".ws-runtime", Select).value or self.candidate.runtime)
        mode = str(self.query_one(".ws-mode", Select).value or self.candidate.mode)
        return WorkspaceCandidate(
            workspace_id=workspace_id,
            relative_path=relative_path,
            score=self.candidate.score,
            markers=list(self.candidate.markers),
            selected=include,
            runtime=runtime,
            mode=mode,
        )


class SetupOrchestratorApp(App[None]):
    """Full-screen setup UI for claude-code-tunnels."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        padding: 1 2;
    }

    .section {
        margin: 1 0;
        padding: 1;
        border: round $panel;
    }

    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .workspace-row {
        margin: 1 0;
        padding: 1;
        border: solid $boost;
    }

    .workspace-fields {
        height: auto;
        width: 1fr;
    }

    .workspace-fields > * {
        margin-right: 1;
        width: 1fr;
    }

    .workspace-meta {
        color: $text-muted;
    }

    #actions {
        margin-top: 1;
        height: auto;
    }

    #actions Button {
        margin-right: 1;
    }

    #status {
        margin-top: 1;
        padding: 1;
        border: round $accent;
        min-height: 12;
    }
    """

    def __init__(self, cwd: Path | None = None) -> None:
        super().__init__()
        self.cwd = (cwd or Path.cwd()).resolve()
        self.analysis = classify_current_folder(self.cwd)
        self.environment: EnvironmentReport = detect_environment(self.cwd)
        self.po_root = self.analysis.suggested_po_root
        self.archive_path = self.po_root / "ARCHIVE"
        self.default_runtime = "claude"
        self.executor_runtime = "claude"
        self.last_status_text = ""
        self.workspace_candidates = suggested_workspace_candidates(self.cwd)
        if not self.workspace_candidates:
            self.workspace_candidates = [
                WorkspaceCandidate(
                    workspace_id="root",
                    relative_path=".",
                    score=0,
                    markers=["manual"],
                    selected=False,
                )
            ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="body"):
            with Vertical(classes="section"):
                yield Static("Step 1. Current folder analysis", classes="section-title")
                yield Static(self._analysis_text(), id="analysis")

            with Vertical(classes="section"):
                yield Static("Step 2. Environment checks", classes="section-title")
                yield Static(environment_summary(self.environment), id="environment")

            with Vertical(classes="section"):
                yield Static("Step 3. PO root, archive, channels, runtimes", classes="section-title")
                yield Input(value=str(self.po_root), placeholder="PO root", id="po-root")
                yield Input(value=str(self.archive_path), placeholder="ARCHIVE path", id="archive-path")
                yield Select(options=RUNTIME_OPTIONS, value=self.default_runtime, id="default-runtime")
                yield Select(options=RUNTIME_OPTIONS, value=self.executor_runtime, id="executor-runtime")
                yield Checkbox("Enable Slack", value=False, id="slack-enabled")
                yield Checkbox("Enable Telegram", value=False, id="telegram-enabled")

            with Vertical(classes="section"):
                yield Static("Step 4. Workspace and WO suggestions", classes="section-title")
                yield Static(
                    "Each selected workspace becomes one Workspace Orchestrator. "
                    "Edit ids, paths, runtime, and local/remote mode before writing the config."
                )
                for candidate in self.workspace_candidates:
                    yield WorkspaceRow(candidate)

            with Horizontal(id="actions"):
                yield Button("Bootstrap deps", id="bootstrap")
                yield Button("Write setup", id="write-setup", variant="primary")
                yield Button("Quit", id="quit")

            with Vertical(classes="section"):
                yield Static("Step 5. Final instructions", classes="section-title")
                yield Static(
                    "Write the setup to generate orchestrator.yaml and start-orchestrator.sh.",
                    id="status",
                )

        yield Footer()

    def _analysis_text(self) -> str:
        alternatives = ", ".join(str(path) for path in self.analysis.alternative_roots) or "(none)"
        reasons = "\n".join(f"- {reason}" for reason in self.analysis.reasons)
        messages = {
            "existing_po": "현재 폴더가 PO 폴더로 보입니다.",
            "new_po_candidate": "현재 폴더를 새 PO 폴더로 쓰는 것이 적절해 보입니다.",
            "workspace_candidate": "현재 폴더는 workspace로 보입니다. parent를 PO 폴더로 쓰는 제안을 준비했습니다.",
            "unknown": "현재 폴더를 자동 분류하기 어려워서 cwd / parent 기준 제안을 준비했습니다.",
        }
        return (
            f"{messages.get(self.analysis.kind, self.analysis.kind)}\n\n"
            f"cwd: {self.cwd}\n"
            f"suggested PO root: {self.analysis.suggested_po_root}\n"
            f"alternative roots: {alternatives}\n"
            f"{reasons}"
        )

    def _collect_candidates(self) -> list[WorkspaceCandidate]:
        return [row.as_candidate() for row in self.query(WorkspaceRow)]

    def _python_bin(self) -> str:
        return self.environment.binaries["python"].path

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        status = self.query_one("#status", Static)

        if event.button.id == "quit":
            self.exit()
            return

        if event.button.id == "bootstrap":
            self.last_status_text = "Bootstrapping local .venv and Node dependencies..."
            status.update(self.last_status_text)
            try:
                outputs = await asyncio.to_thread(
                    bootstrap_project_dependencies,
                    Path(self.query_one("#po-root", Input).value).expanduser(),
                    self._python_bin(),
                )
            except Exception as exc:
                self.last_status_text = f"Bootstrap failed.\n\n{exc}"
                status.update(self.last_status_text)
                return
            self.last_status_text = "Bootstrap complete.\n\n" + "\n".join(outputs)
            status.update(self.last_status_text)
            return

        if event.button.id == "write-setup":
            po_root = Path(self.query_one("#po-root", Input).value).expanduser()
            archive_path = Path(self.query_one("#archive-path", Input).value).expanduser()
            default_runtime = str(self.query_one("#default-runtime", Select).value or "claude")
            executor_runtime = str(self.query_one("#executor-runtime", Select).value or "claude")
            slack_enabled = self.query_one("#slack-enabled", Checkbox).value
            telegram_enabled = self.query_one("#telegram-enabled", Checkbox).value
            candidates = self._collect_candidates()

            try:
                summary = await asyncio.to_thread(
                    write_setup_files,
                    po_root.resolve(),
                    archive_path.resolve(),
                    slack_enabled,
                    telegram_enabled,
                    default_runtime,
                    executor_runtime,
                    candidates,
                    self._python_bin(),
                )
            except Exception as exc:
                self.last_status_text = f"Setup write failed.\n\n{exc}"
                status.update(self.last_status_text)
                return

            self.last_status_text = final_instruction_text(summary)
            status.update(self.last_status_text)


def main() -> None:
    """Run the setup TUI."""
    app = SetupOrchestratorApp()
    app.run()


if __name__ == "__main__":
    main()
