"""Tests for orchestrator.task_log."""

from datetime import datetime

import pytest

from orchestrator.task_log import _determine_status, _is_date_folder, write_task_log


def _make_results(**overrides):
    base = {
        "changed_files": [],
        "summary": "done",
        "test_result": "pass",
        "downstream_context": "",
        "runtime": "claude",
    }
    return {**base, **overrides}


class TestWriteTaskLog:
    @pytest.mark.asyncio
    async def test_log_file_created_with_task_id_prefix(self, tmp_path):
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
    async def test_log_contains_request_plan_runtime_and_results(self, tmp_path):
        result = await write_task_log(
            task_id="b7c2",
            task_label="multi-ws",
            project="new-place",
            channel="cli",
            original_request="update everything",
            phases=[["server"], ["frontend"]],
            results={
                "server": _make_results(changed_files=["api.py"], summary="added endpoint", runtime="codex"),
                "frontend": _make_results(changed_files=["app.vue"], summary="updated UI"),
            },
            started_at=datetime(2026, 3, 18, 10, 0),
            base_dir=tmp_path,
        )

        content = result.read_text()
        assert "task_id: b7c2" in content
        assert "status: success" in content
        assert "update everything" in content
        assert "Phase 1: server (independent)" in content
        assert "Phase 2: frontend (incorporates previous phase results)" in content
        assert "### server [pass]" in content
        assert "- changed: api.py" in content
        assert "- runtime: codex" in content


class TestRetention:
    @pytest.mark.asyncio
    async def test_old_folders_deleted_when_exceeding_limit(self, tmp_path):
        tasks_dir = tmp_path / ".tasks"
        for index in range(31):
            date_str = f"2025-01-{index + 1:02d}"
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

        date_folders = [folder for folder in tasks_dir.iterdir() if folder.is_dir() and _is_date_folder(folder.name)]
        assert len(date_folders) <= 30


class TestHelpers:
    def test_is_date_folder(self):
        assert _is_date_folder("2026-03-18") is True
        assert _is_date_folder("not-a-date") is False

    def test_determine_status_success(self):
        assert _determine_status({"ws1": {"test_result": "pass"}}) == "success"

    def test_determine_status_partial_failure(self):
        result = _determine_status(
            {
                "ws1": {"test_result": "pass"},
                "ws2": {"test_result": "fail", "error": "x"},
            }
        )
        assert result == "partial_failure"

    def test_determine_status_failure(self):
        assert _determine_status({"ws1": {"test_result": "fail", "error": "x"}}) == "failure"
