"""Tests for runtime and remote config resolution."""

from pathlib import Path

import orchestrator


def test_workspace_runtime_override_beats_role_and_default(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "CONFIG",
        {
            "runtime": {
                "default": "claude",
                "roles": {"executor": "cursor"},
            },
            "workspaces": [
                {
                    "id": "backend",
                    "path": "backend",
                    "wo": {"runtime": "opencode", "mode": "local"},
                }
            ],
        },
    )

    assert orchestrator.resolve_runtime_name("executor", workspace_id="backend") == "opencode"
    assert orchestrator.resolve_runtime_name("executor", workspace_id="frontend") == "cursor"
    assert orchestrator.resolve_runtime_name("router") == "claude"


def test_resolve_remote_workspace_config_from_new_schema(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "CONFIG",
        {
            "workspaces": [
                {
                    "id": "staging",
                    "path": "services/staging",
                    "wo": {
                        "runtime": "codex",
                        "mode": "remote",
                        "remote": {"host": "10.0.0.5", "port": 9100, "token": "abc"},
                    },
                }
            ]
        },
    )

    config = orchestrator.resolve_remote_workspace_config("staging")

    assert config == {
        "host": "10.0.0.5",
        "port": 9100,
        "token": "abc",
        "runtime": "codex",
    }


def test_resolve_workspace_path_prefers_registry(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "CONFIG",
        {
            "workspaces": [
                {
                    "id": "backend",
                    "path": "services/backend",
                    "wo": {"runtime": "claude", "mode": "local"},
                }
            ]
        },
    )

    path = orchestrator.resolve_workspace_path(".", "backend", base_dir=Path("/tmp/project"))
    assert path == Path("/tmp/project/services/backend").resolve()
