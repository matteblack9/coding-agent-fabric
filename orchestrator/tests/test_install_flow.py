"""Tests for install-flow setup auto-launch helpers."""

from pathlib import Path
import subprocess

from orchestrator import install_flow


def test_should_skip_setup_respects_env_override():
    assert install_flow.should_skip_setup({"SKIP_SETUP_TUI": "1"}) is True
    assert install_flow.should_skip_setup({"SKIP_SETUP_TUI": "true"}) is True
    assert install_flow.should_skip_setup({}) is False


def test_launch_setup_tui_runs_from_repo_root(monkeypatch, tmp_path):
    recorded: dict[str, object] = {}

    def fake_run(args, cwd, check):
        recorded["args"] = args
        recorded["cwd"] = cwd
        recorded["check"] = check
        return subprocess.CompletedProcess(args=args, returncode=7)

    monkeypatch.setattr(install_flow.subprocess, "run", fake_run)

    code = install_flow.launch_setup_tui("/venv/bin/python", tmp_path)

    assert code == 7
    assert recorded["args"] == ["/venv/bin/python", "-m", "orchestrator.setup_tui"]
    assert recorded["cwd"] == str(tmp_path.resolve())
    assert recorded["check"] is False


def test_main_launches_setup_when_not_skipped(monkeypatch, tmp_path):
    called: dict[str, object] = {}
    cleared: dict[str, bool] = {"value": False}

    def fake_launch(python_bin: str, root_dir: str | Path) -> int:
        called["python_bin"] = python_bin
        called["root_dir"] = Path(root_dir)
        return 3

    def fake_clear() -> None:
        cleared["value"] = True

    monkeypatch.delenv("SKIP_SETUP_TUI", raising=False)
    monkeypatch.setattr(install_flow, "clear_terminal", fake_clear)
    monkeypatch.setattr(install_flow, "launch_setup_tui", fake_launch)

    code = install_flow.main([str(tmp_path)])

    assert code == 3
    assert cleared["value"] is True
    assert called["python_bin"] == install_flow.sys.executable
    assert called["root_dir"] == tmp_path.resolve()


def test_main_skips_when_env_override_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SKIP_SETUP_TUI", "1")
    monkeypatch.setattr(install_flow, "clear_terminal", lambda: (_ for _ in ()).throw(AssertionError("should not clear")))
    monkeypatch.setattr(install_flow, "launch_setup_tui", lambda *_: 99)

    code = install_flow.main([str(tmp_path)])

    assert code == 0
