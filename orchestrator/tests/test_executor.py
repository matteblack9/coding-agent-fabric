"""Tests for orchestrator.executor — run_workspace and execute_phases."""

from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from claude_agent_sdk import AssistantMessage

from orchestrator.executor import run_workspace, execute_phases


def _make_fake_query(response_text: str):
    """Create a fake query async generator yielding a message with given text."""

    async def fake_query(*, prompt, options=None, transport=None):
        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock()
        block.text = response_text
        msg.content = [block]
        yield msg

    return fake_query


class TestRunWorkspace:
    @pytest.mark.asyncio
    async def test_cwd_is_workspace_absolute_path(self):
        response = (
            '{"changed_files": [], "summary": "done", '
            '"test_result": "pass", "downstream_context": ""}'
        )
        with patch("orchestrator.executor.query") as mock_query:
            mock_query.side_effect = _make_fake_query(response)

            await run_workspace(
                project="new-place",
                workspace="server",
                task="add health API",
                base_dir=Path("/test/base"),
            )

            call_kwargs = mock_query.call_args.kwargs
            assert str(call_kwargs["options"].cwd) == "/test/base/new-place/server"

    @pytest.mark.asyncio
    async def test_cwd_uses_default_base(self):
        response = (
            '{"changed_files": [], "summary": "done", '
            '"test_result": "pass", "downstream_context": ""}'
        )
        with patch("orchestrator.executor.query") as mock_query:
            mock_query.side_effect = _make_fake_query(response)

            await run_workspace(
                project="new-place",
                workspace="server",
                task="add health API",
            )

            call_kwargs = mock_query.call_args.kwargs
            assert (
                str(call_kwargs["options"].cwd)
                == "/home1/irteam/naver/project/new-place/server"
            )

    @pytest.mark.asyncio
    async def test_json_response_parsed(self):
        response = (
            '{"changed_files": ["api.py"], "summary": "added endpoint", '
            '"test_result": "pass", "downstream_context": "Added GET /health"}'
        )
        with patch("orchestrator.executor.query") as mock_query:
            mock_query.side_effect = _make_fake_query(response)

            result = await run_workspace(
                project="p",
                workspace="ws",
                task="task",
                base_dir=Path("/test"),
            )

            assert result["changed_files"] == ["api.py"]
            assert result["summary"] == "added endpoint"
            assert result["test_result"] == "pass"
            assert result["downstream_context"] == "Added GET /health"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        with patch("orchestrator.executor.query") as mock_query:
            mock_query.side_effect = _make_fake_query("not valid json at all")

            result = await run_workspace(
                project="p",
                workspace="ws",
                task="task",
                base_dir=Path("/test"),
            )

            assert result["test_result"] == "skip"
            assert "not valid json" in result["summary"]

    @pytest.mark.asyncio
    async def test_upstream_context_included_in_prompt(self):
        response = (
            '{"changed_files": [], "summary": "ok", '
            '"test_result": "pass", "downstream_context": ""}'
        )
        with patch("orchestrator.executor.query") as mock_query:
            mock_query.side_effect = _make_fake_query(response)

            await run_workspace(
                project="p",
                workspace="ws",
                task="update frontend",
                upstream_context={"server": "Added GET /health endpoint"},
                base_dir=Path("/test"),
            )

            prompt = mock_query.call_args.kwargs["prompt"]
            assert "Upstream context" in prompt
            assert "server: Added GET /health endpoint" in prompt

    @pytest.mark.asyncio
    async def test_setting_sources_and_permission_mode(self):
        response = (
            '{"changed_files": [], "summary": "ok", '
            '"test_result": "pass", "downstream_context": ""}'
        )
        with patch("orchestrator.executor.query") as mock_query:
            mock_query.side_effect = _make_fake_query(response)

            await run_workspace(
                project="p",
                workspace="ws",
                task="task",
                base_dir=Path("/test"),
            )

            options = mock_query.call_args.kwargs["options"]
            assert options.setting_sources == ["project"]
            assert options.permission_mode == "bypassPermissions"
            assert options.max_turns == 100
            assert options.model is None


class TestExecutePhases:
    @pytest.mark.asyncio
    async def test_single_phase_single_workspace(self):
        with patch(
            "orchestrator.executor.run_workspace", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = {
                "changed_files": ["file.py"],
                "summary": "done",
                "test_result": "pass",
                "downstream_context": "",
            }

            results = await execute_phases(
                project="test-project",
                phases=[["ws1"]],
                tasks={"ws1": "do task"},
            )

            assert "ws1" in results
            assert results["ws1"]["test_result"] == "pass"
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_phase_multi_workspace_parallel(self):
        call_order = []

        async def tracked_run(
            project, workspace, task, upstream_context=None, base_dir=None
        ):
            call_order.append(workspace)
            return {
                "changed_files": [],
                "summary": f"{workspace} done",
                "test_result": "pass",
                "downstream_context": "",
            }

        with patch("orchestrator.executor.run_workspace", side_effect=tracked_run):
            results = await execute_phases(
                project="test",
                phases=[["ws1", "ws2", "ws3"]],
                tasks={"ws1": "t1", "ws2": "t2", "ws3": "t3"},
            )

            assert len(results) == 3
            assert all(
                results[ws]["test_result"] == "pass" for ws in ["ws1", "ws2", "ws3"]
            )

    @pytest.mark.asyncio
    async def test_multi_phase_upstream_context_flow(self):
        call_contexts: dict[str, dict | None] = {}

        async def tracked_run(
            project, workspace, task, upstream_context=None, base_dir=None
        ):
            call_contexts[workspace] = upstream_context
            if workspace == "server":
                return {
                    "changed_files": ["api.py"],
                    "summary": "added API",
                    "test_result": "pass",
                    "downstream_context": "Added GET /health endpoint",
                }
            return {
                "changed_files": ["app.vue"],
                "summary": "updated frontend",
                "test_result": "pass",
                "downstream_context": "",
            }

        with patch("orchestrator.executor.run_workspace", side_effect=tracked_run):
            results = await execute_phases(
                project="test",
                phases=[["server"], ["frontend"]],
                tasks={"server": "add health API", "frontend": "update UI"},
            )

            assert call_contexts["server"] is None
            assert call_contexts["frontend"] == {
                "server": "Added GET /health endpoint"
            }
            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_downstream_context_not_passed(self):
        call_contexts: dict[str, dict | None] = {}

        async def tracked_run(
            project, workspace, task, upstream_context=None, base_dir=None
        ):
            call_contexts[workspace] = upstream_context
            return {
                "changed_files": [],
                "summary": "done",
                "test_result": "pass",
                "downstream_context": "",
            }

        with patch("orchestrator.executor.run_workspace", side_effect=tracked_run):
            await execute_phases(
                project="test",
                phases=[["ws1"], ["ws2"]],
                tasks={"ws1": "task1", "ws2": "task2"},
            )

            assert call_contexts["ws2"] is None

    @pytest.mark.asyncio
    async def test_workspace_failure_partial(self):
        async def tracked_run(
            project, workspace, task, upstream_context=None, base_dir=None
        ):
            if workspace == "ws1":
                raise RuntimeError("ws1 crashed")
            return {
                "changed_files": [],
                "summary": "ok",
                "test_result": "pass",
                "downstream_context": "",
            }

        with patch("orchestrator.executor.run_workspace", side_effect=tracked_run):
            results = await execute_phases(
                project="test",
                phases=[["ws1", "ws2"]],
                tasks={"ws1": "task1", "ws2": "task2"},
            )

            assert "error" in results["ws1"]
            assert results["ws1"]["test_result"] == "fail"
            assert results["ws2"]["test_result"] == "pass"

    @pytest.mark.asyncio
    async def test_failed_workspace_in_upstream_context(self):
        call_contexts: dict[str, dict | None] = {}

        async def tracked_run(
            project, workspace, task, upstream_context=None, base_dir=None
        ):
            call_contexts[workspace] = upstream_context
            if workspace == "server":
                raise RuntimeError("server build failed")
            return {
                "changed_files": [],
                "summary": "done",
                "test_result": "pass",
                "downstream_context": "",
            }

        with patch("orchestrator.executor.run_workspace", side_effect=tracked_run):
            await execute_phases(
                project="test",
                phases=[["server"], ["frontend"]],
                tasks={"server": "update API", "frontend": "update UI"},
            )

            assert call_contexts["frontend"] is not None
            assert "FAILED" in call_contexts["frontend"].get("server", "")
