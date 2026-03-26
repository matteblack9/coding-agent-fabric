"""Tests for sanitization and blocked directory handling."""

from pathlib import Path

from orchestrator import BLOCKED_DIRS
from orchestrator.sanitize import validate_project_name, validate_workspace_name


def test_blocked_dirs_include_cursor():
    assert ".cursor" in BLOCKED_DIRS


def test_blocked_dirs_include_opencode():
    assert ".opencode" in BLOCKED_DIRS


def test_validate_project_name_rejects_cursor_dir(tmp_path):
    (tmp_path / ".cursor").mkdir()
    assert not validate_project_name(".cursor", tmp_path)


def test_validate_project_name_rejects_opencode_dir(tmp_path):
    (tmp_path / ".opencode").mkdir()
    assert not validate_project_name(".opencode", tmp_path)


def test_validate_workspace_name_rejects_cursor_dir(tmp_path):
    (tmp_path / ".cursor").mkdir()
    assert not validate_workspace_name(".cursor", tmp_path)


def test_validate_workspace_name_rejects_opencode_dir(tmp_path):
    (tmp_path / ".opencode").mkdir()
    assert not validate_workspace_name(".opencode", tmp_path)
