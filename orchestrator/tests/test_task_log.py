"""Tests for orchestrator.task_log — log writing, status, retention."""

from datetime import datetime
from pathlib import Path

import pytest

from orchestrator.task_log import (
    write_task_log,
    _is_date_folder,
    _determine_status,
)


def _make_results(**overrides):
    base = {
        "changed_files": [],
        "summary": "done",
        "test_result": "pass",
        "downstream_context": "",
    }
    return {**base, **overrides}


class TestWriteTaskLog:
    @pytest.mark.asyncio
    async def test_log_file_created_at_correct_path(self, tmp_path):
        result = await write_task_log(
            task_id="a3f1",
            task_label="add-health-api",
            project="new-place",
            channel="works",
            original_request="add health check",
            phases=[["server"]],
            results={"server": _make_results()},
            started_at=datetime(2026, 3, 18, 14, 30),
            base_dir=tmp_path,
        )

        assert result.exists()
        assert result.name == "a3f1_add-health-api.md"
        assert "new-place" in str(result)
        assert ".tasks" in str(result)

    @pytest.mark.asyncio
    async def test_frontmatter_contains_required_fields(self, tmp_path):
        result = await write_task_log(
            task_id="b7c2",
            task_label="fix-css",
            project="new-place",
            channel="cli",
            original_request="fix dark mode CSS",
            phases=[["demo-frontend"]],
            results={"demo-frontend": _make_results()},
            started_at=datetime(2026, 3, 18, 10, 0),
            base_dir=tmp_path,
        )

        content = result.read_text()
        assert "task_id: b7c2" in content
        assert "project: new-place" in content
        assert "channel: cli" in content
        assert "status: success" in content

    @pytest.mark.asyncio
    async def test_status_success(self, tmp_path):
        result = await write_task_log(
            task_id="x1",
            task_label="all-pass",
            project="p",
            channel="cli",
            original_request="test",
            phases=[["ws1", "ws2"]],
            results={"ws1": _make_results(), "ws2": _make_results()},
            started_at=datetime(2026, 1, 1),
            base_dir=tmp_path,
        )

        assert "status: success" in result.read_text()

    @pytest.mark.asyncio
    async def test_status_partial_failure(self, tmp_path):
        result = await write_task_log(
            task_id="x2",
            task_label="some-fail",
            project="p",
            channel="cli",
            original_request="test",
            phases=[["ws1", "ws2"]],
            results={
                "ws1": _make_results(),
                "ws2": _make_results(test_result="fail", error="crashed"),
            },
            started_at=datetime(2026, 1, 1),
            base_dir=tmp_path,
        )

        assert "status: partial_failure" in result.read_text()

    @pytest.mark.asyncio
    async def test_status_failure(self, tmp_path):
        result = await write_task_log(
            task_id="x3",
            task_label="all-fail",
            project="p",
            channel="cli",
            original_request="test",
            phases=[["ws1"]],
            results={"ws1": _make_results(test_result="fail", error="crashed")},
            started_at=datetime(2026, 1, 1),
            base_dir=tmp_path,
        )

        assert "status: failure" in result.read_text()

    @pytest.mark.asyncio
    async def test_log_contains_request_and_results(self, tmp_path):
        result = await write_task_log(
            task_id="c1",
            task_label="multi-ws",
            project="new-place",
            channel="works",
            original_request="update everything",
            phases=[["server"], ["frontend"]],
            results={
                "server": _make_results(
                    changed_files=["api.py"],
                    summary="added endpoint",
                ),
                "frontend": _make_results(
                    changed_files=["app.vue"],
                    summary="updated UI",
                ),
            },
            started_at=datetime(2026, 3, 18),
            base_dir=tmp_path,
        )

        content = result.read_text()
        assert '"update everything"' in content
        assert "### server [pass]" in content
        assert "### frontend [pass]" in content
        assert "- changed: api.py" in content
        assert "Phase 1: server (독립)" in content
        assert "Phase 2: frontend (이전 phase 결과 반영)" in content


class TestRetention:
    @pytest.mark.asyncio
    async def test_old_folders_deleted_when_exceeding_limit(self, tmp_path):
        tasks_dir = tmp_path / ".tasks"

        for i in range(31):
            date_str = f"2025-01-{i + 1:02d}"
            folder = tasks_dir / date_str / "test-project"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "dummy.md").write_text("test")

        await write_task_log(
            task_id="r1",
            task_label="retention-test",
            project="test-project",
            channel="cli",
            original_request="test",
            phases=[["ws1"]],
            results={"ws1": _make_results()},
            started_at=datetime(2026, 3, 18),
            base_dir=tmp_path,
        )

        date_folders = [
            d
            for d in tasks_dir.iterdir()
            if d.is_dir() and _is_date_folder(d.name)
        ]
        assert len(date_folders) <= 30


class TestHelpers:
    def test_is_date_folder_valid(self):
        assert _is_date_folder("2026-03-18") is True

    def test_is_date_folder_invalid(self):
        assert _is_date_folder("not-a-date") is False
        assert _is_date_folder("test-project") is False

    def test_determine_status_success(self):
        result = _determine_status(
            {
                "ws1": {"test_result": "pass"},
                "ws2": {"test_result": "pass"},
            }
        )
        assert result == "success"

    def test_determine_status_partial_failure(self):
        result = _determine_status(
            {
                "ws1": {"test_result": "pass"},
                "ws2": {"test_result": "fail", "error": "x"},
            }
        )
        assert result == "partial_failure"

    def test_determine_status_failure(self):
        result = _determine_status(
            {"ws1": {"test_result": "fail", "error": "x"}}
        )
        assert result == "failure"
