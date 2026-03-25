"""Lightweight HTTP API for external channel gateways (external bots, etc).

Runs alongside Socket Mode gateways. External services POST to /request
and results are delivered back via channel-specific push (channel push API, etc).
"""

from __future__ import annotations

import logging
from aiohttp import web

from orchestrator.server import ConfirmGate, handle_request, send_to_channel

logger = logging.getLogger(__name__)


def create_app(confirm_gate: ConfirmGate) -> web.Application:
    app = web.Application()
    app["confirm_gate"] = confirm_gate

    app.router.add_post("/request", _handle_incoming)
    app.router.add_post("/confirm/{request_id}", _handle_confirm)
    app.router.add_get("/pending", _handle_pending)
    app.router.add_get("/health", _handle_health)

    return app


async def _handle_incoming(request: web.Request) -> web.Response:
    """Receive a new request from external gateway.

    Body: {
        "message": "user message text",
        "channel": "...",
        "callback_info": { ... }
    }
    """
    gate: ConfirmGate = request.app["confirm_gate"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    message = body.get("message", "").strip()
    channel = body.get("channel", "")
    callback_info = body.get("callback_info", {})

    if not message:
        return web.json_response({"error": "message required"}, status=400)

    import uuid
    request_id = uuid.uuid4().hex[:8]

    gate.create_request(
        request_id=request_id,
        message=message,
        channel=channel,
        callback_info=callback_info,
    )

    confirm_msg = (
        f"이렇게 이해했는데 맞나요?\n"
        f"> {message}\n\n"
        f"진행하려면 이 request_id로 /confirm 호출: {request_id}"
    )

    return web.json_response({
        "request_id": request_id,
        "status": "pending_confirm",
        "confirm_message": confirm_msg,
    })


async def _handle_confirm(request: web.Request) -> web.Response:
    """Confirm a pending request → triggers handle_request."""
    gate: ConfirmGate = request.app["confirm_gate"]
    request_id = request.match_info["request_id"]

    req = gate.get_pending(request_id)
    if req is None:
        return web.json_response(
            {"error": f"No pending request: {request_id}"}, status=404
        )

    try:
        result = await gate.confirm(request_id)
        return web.json_response({"status": "completed", "result": result})
    except Exception as e:
        logger.exception("handle_request failed for %s", request_id)
        return web.json_response(
            {"error": str(e), "status": "failed"}, status=500
        )


async def _handle_pending(request: web.Request) -> web.Response:
    """List all pending requests."""
    gate: ConfirmGate = request.app["confirm_gate"]
    pending = {
        rid: {"message": r.message, "channel": r.channel}
        for rid, r in gate.pending_requests.items()
    }
    return web.json_response(pending)


async def _handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})