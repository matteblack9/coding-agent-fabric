"""Tests for orchestrator.server — ConfirmGate, format_results, handle_request."""

from unittest.mock import patch, AsyncMock

import pytest

from orchestrator.server import (
    ConfirmGate,
    format_results,
    handle_request,
    plan_request,
)
from orchestrator.router import RouteResult


class TestConfirmGate:
    def test_create_request_adds_to_pending(self):
        gate = ConfirmGate()
        req = gate.create_request("r1", "test message", "cli", {})

        assert req.request_id == "r1"
        assert req.message == "test message"
        assert "r1" in gate.pending_requests

    def test_get_pending_found(self):
        gate = ConfirmGate()
        gate.create_request("r1", "test", "cli", {})
        assert gate.get_pending("r1") is not None

    def test_get_pending_not_found(self):
        gate = ConfirmGate()
        assert gate.get_pending("r999") is None

    def test_remove_existing(self):
        gate = ConfirmGate()
        gate.create_request("r1", "test", "cli", {})
        req = gate.remove("r1")
        assert req is not None
        assert req.request_id == "r1"
        assert "r1" not in gate.pending_requests

    def test_remove_nonexistent(self):
        gate = ConfirmGate()
        assert gate.remove("r999") is None

    @pytest.mark.asyncio
    async def test_confirm_executes_and_removes(self):
        gate = ConfirmGate()
        gate.create_request("r1", "add health check", "cli", {})

        with patch(
            "orchestrator.server.handle_request", new_callable=AsyncMock
        ) as mock_handle:
            mock_handle.return_value = {"status": "ok"}
            result = await gate.confirm("r1")

            assert result == {"status": "ok"}
            mock_handle.assert_called_once_with(
                user_message="add health check",
                raw_message="add health check",
                channel="cli",
                callback_info={},
                send_results=False,
                request_id="r1",
            )

        assert "r1" not in gate.pending_requests

    @pytest.mark.asyncio
    async def test_confirm_unknown_raises_key_error(self):
        gate = ConfirmGate()
        with pytest.raises(KeyError, match="No pending request"):
            await gate.confirm("nonexistent")


class TestFormatResults:
    def test_stateless_channel_includes_request(self):
        result = format_results(
            original_request="add health API",
            project_results={
                "new-place": {
                    "phases": [["server"]],
                    "results": {
                        "server": {
                            "summary": "Added GET /health",
                            "test_result": "pass",
                        },
                    },
                },
            },
            channel="works",
        )

        assert "add health API" in result
        assert "[pass]" in result
        assert "Added GET /health" in result

    def test_cli_channel_no_request_prefix(self):
        result = format_results(
            original_request="something",
            project_results={
                "p": {
                    "phases": [["ws1"]],
                    "results": {
                        "ws1": {"summary": "done", "test_result": "pass"},
                    },
                },
            },
            channel="cli",
        )

        assert "Request:" not in result

    def test_multi_phase_format(self):
        result = format_results(
            original_request="update API v2",
            project_results={
                "new-place": {
                    "phases": [["server", "pipeline"], ["demo-frontend"]],
                    "results": {
                        "server": {"summary": "API v2", "test_result": "pass"},
                        "pipeline": {"summary": "schema v2", "test_result": "pass"},
                        "demo-frontend": {"summary": "route v2", "test_result": "pass"},
                    },
                },
            },
            channel="works",
        )

        assert "Phase 1: server, pipeline" in result
        assert "Phase 2: demo-frontend" in result

    def test_failed_project(self):
        result = format_results(
            original_request="test",
            project_results={
                "broken": {"error": "timeout"},
            },
            channel="works",
        )

        assert "[broken] FAILED: timeout" in result


class TestPlanRequest:
    @pytest.mark.asyncio
    async def test_clarification_from_router(self):
        with patch(
            "orchestrator.server.route_request", new_callable=AsyncMock
        ) as mock_route:
            mock_route.return_value = RouteResult(
                projects=[],
                refined_message="do something",
                clarification_needed="Which project are you referring to?",
            )
            result = await plan_request("do something")
            assert result["status"] == "clarification_needed"

    @pytest.mark.asyncio
    async def test_direct_request(self):
        with patch(
            "orchestrator.server.route_request", new_callable=AsyncMock
        ) as mock_route:
            mock_route.return_value = RouteResult(
                projects=[], refined_message="search jira",
            )
            result = await plan_request("search jira")
            assert result["status"] == "direct_request"

    @pytest.mark.asyncio
    async def test_planned_single_project(self):
        plan = {
            "project": "new-place",
            "task_id": "a1",
            "task_label": "add-health",
            "phases": [["server"]],
            "task_per_workspace": {"server": "add health"},
        }
        with patch(
            "orchestrator.server.route_request", new_callable=AsyncMock
        ) as mock_route, patch(
            "orchestrator.server.get_execution_plan", new_callable=AsyncMock
        ) as mock_po:
            mock_route.return_value = RouteResult(
                projects=["new-place"], refined_message="add health",
            )
            mock_po.return_value = plan
            result = await plan_request("add health")
            assert result["status"] == "planned"
            assert len(result["plans"]) == 1
            assert result["plans"][0]["project"] == "new-place"


class TestHandleRequest:
    @pytest.mark.asyncio
    async def test_clarification_flow(self):
        with patch(
            "orchestrator.server.route_request", new_callable=AsyncMock
        ) as mock_route, patch(
            "orchestrator.server.send_to_channel", new_callable=AsyncMock
        ) as mock_send:
            mock_route.return_value = RouteResult(
                projects=[],
                refined_message="do something",
                clarification_needed="Which project are you referring to?",
            )

            result = await handle_request("do something", "works", {})

            assert result["status"] == "clarification_needed"
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_project_flow(self):
        plan = {
            "project": "new-place",
            "task_id": "a3f1",
            "task_label": "add-health",
            "phases": [["server"]],
            "task_per_workspace": {"server": "add health API"},
        }

        with patch(
            "orchestrator.server.route_request", new_callable=AsyncMock
        ) as mock_route, patch(
            "orchestrator.server.get_execution_plan", new_callable=AsyncMock
        ) as mock_po, patch(
            "orchestrator.server.execute_phases", new_callable=AsyncMock
        ) as mock_exec, patch(
            "orchestrator.server.write_task_log", new_callable=AsyncMock
        ) as mock_log, patch(
            "orchestrator.server.send_to_channel", new_callable=AsyncMock
        ):
            mock_route.return_value = RouteResult(
                projects=["new-place"], refined_message="add health check",
            )
            mock_po.return_value = plan
            mock_exec.return_value = {
                "server": {
                    "changed_files": ["health.py"],
                    "summary": "added endpoint",
                    "test_result": "pass",
                    "downstream_context": "",
                },
            }
            mock_log.return_value = "/tmp/log.md"

            result = await handle_request("add health check", "cli", {})

            assert result["project"] == "new-place"
            assert result["task_id"] == "a3f1"
            mock_exec.assert_called_once()
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_multi_project_flow(self):
        plan_np = {
            "project": "new-place",
            "task_id": "a1",
            "task_label": "update-log",
            "phases": [["server"]],
            "task_per_workspace": {"server": "update logging"},
        }
        plan_ltr = {
            "project": "local-trend-reason",
            "task_id": "a2",
            "task_label": "update-log",
            "phases": [["reason-analysis"]],
            "task_per_workspace": {"reason-analysis": "update logging"},
        }

        with patch(
            "orchestrator.server.route_request", new_callable=AsyncMock
        ) as mock_route, patch(
            "orchestrator.server.get_execution_plan", new_callable=AsyncMock
        ) as mock_po, patch(
            "orchestrator.server.execute_phases", new_callable=AsyncMock
        ) as mock_exec, patch(
            "orchestrator.server.write_task_log", new_callable=AsyncMock
        ) as mock_log, patch(
            "orchestrator.server.send_to_channel", new_callable=AsyncMock
        ):
            mock_route.return_value = RouteResult(
                projects=["new-place", "local-trend-reason"],
                refined_message="update logging everywhere",
            )
            mock_po.side_effect = [plan_np, plan_ltr]
            mock_exec.return_value = {
                "server": {
                    "changed_files": [],
                    "summary": "done",
                    "test_result": "pass",
                    "downstream_context": "",
                },
            }
            mock_log.return_value = "/tmp/log.md"

            result = await handle_request("update logging everywhere", "works", {})

            assert "new-place" in result
            assert "local-trend-reason" in result
