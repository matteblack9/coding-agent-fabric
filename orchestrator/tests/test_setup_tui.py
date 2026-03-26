"""Smoke tests for the setup TUI."""

from pathlib import Path

import pytest

from orchestrator.setup_support import BinaryStatus, EnvironmentReport
from orchestrator.setup_tui import SetupOrchestratorApp
from textual.widgets import Button


def _fake_environment() -> EnvironmentReport:
    binaries = {
        "python": BinaryStatus(name="python", available=True, path="/usr/bin/python3", version="3.12.0"),
        "node": BinaryStatus(name="node", available=True, path="/usr/bin/node", version="v22.0.0"),
        "npm": BinaryStatus(name="npm", available=True, path="/usr/bin/npm", version="10.0.0"),
        "claude": BinaryStatus(name="claude", available=True, path="/usr/bin/claude", version="2.0.0"),
        "codex": BinaryStatus(name="codex", available=True, path="/usr/bin/codex", version="0.116.0"),
        "opencode": BinaryStatus(name="opencode", available=True, path="/usr/bin/opencode", version="1.3.2"),
    }
    return EnvironmentReport(
        binaries=binaries,
        codex_auth="Logged in using ChatGPT",
        opencode_provider_count=0,
        opencode_provider_status="0 credentials",
    )


@pytest.mark.asyncio
async def test_setup_tui_writes_files_and_shows_run_instructions(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "package.json").write_text("{}\n")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "pyproject.toml").write_text("[project]\nname='frontend'\n")

    monkeypatch.setattr("orchestrator.setup_tui.detect_environment", lambda cwd: _fake_environment())

    app = SetupOrchestratorApp(cwd=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        button = app.query_one("#write-setup", Button)
        await app.on_button_pressed(Button.Pressed(button))
        await pilot.pause()
        assert "./start-orchestrator.sh --fg" in app.last_status_text

    assert (tmp_path / "orchestrator.yaml").exists()
    assert (tmp_path / "start-orchestrator.sh").exists()
