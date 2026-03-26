"""Persistent JSON-RPC bridge for Node-based runtimes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_ENTRYPOINT = BRIDGE_ROOT / "bridge" / "daemon.mjs"


class BridgeError(RuntimeError):
    """Raised when the runtime bridge fails."""


class BridgeDaemon:
    """Long-lived stdio JSON-RPC client for the Node bridge."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._counter = 0

    async def ensure_started(self) -> None:
        async with self._lock:
            if self._proc and self._proc.returncode is None:
                return
            node = _find_working_node()
            if not node:
                raise BridgeError("Node.js is required for Codex/OpenCode runtimes.")
            if not BRIDGE_ENTRYPOINT.exists():
                raise BridgeError(f"Bridge entrypoint not found: {BRIDGE_ENTRYPOINT}")

            self._proc = await asyncio.create_subprocess_exec(
                node,
                str(BRIDGE_ENTRYPOINT),
                cwd=str(BRIDGE_ROOT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(self._read_stdout())
            self._stderr_task = asyncio.create_task(self._read_stderr())

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2)
            except TimeoutError:
                self._proc.kill()
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        self._proc = None

    async def request(self, method: str, params: dict) -> dict:
        await self.ensure_started()
        if not self._proc or not self._proc.stdin:
            raise BridgeError("Bridge process is not available.")

        self._counter += 1
        request_id = f"req-{self._counter}"
        payload = {"id": request_id, "method": method, "params": params}
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        try:
            self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()
            response = await future
        finally:
            self._pending.pop(request_id, None)

        if not response.get("ok"):
            error = response.get("error", {})
            raise BridgeError(error.get("message", "Bridge request failed"))
        return response.get("result", {})

    async def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning("Bridge emitted invalid JSON: %s", line)
                continue
            request_id = message.get("id")
            future = self._pending.get(request_id)
            if future and not future.done():
                future.set_result(message)

        for future in self._pending.values():
            if not future.done():
                future.set_exception(BridgeError("Bridge process exited unexpectedly"))

    async def _read_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            logger.debug("[bridge] %s", line.decode("utf-8").rstrip())


_daemon: BridgeDaemon | None = None


async def get_bridge_daemon() -> BridgeDaemon:
    global _daemon
    if _daemon is None:
        _daemon = BridgeDaemon()
    await _daemon.ensure_started()
    return _daemon


async def close_bridge_daemon() -> None:
    global _daemon
    if _daemon is not None:
        await _daemon.close()
        _daemon = None


def _find_working_node() -> str | None:
    """Return the first node binary that can execute a version probe."""
    path_value = os.environ.get("PATH", "")
    candidates: list[str] = []
    for directory in path_value.split(os.pathsep):
        candidate = Path(directory) / "node"
        if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
            candidates.append(str(candidate))
    fallback = shutil.which("node")
    if fallback and fallback not in candidates:
        candidates.append(fallback)

    for candidate in candidates:
        try:
            proc = awaitable_run_version_probe(candidate)
        except Exception:
            continue
        if proc:
            return candidate
    return None


def awaitable_run_version_probe(candidate: str) -> bool:
    """Run `node --version` synchronously to validate the candidate binary."""
    import subprocess

    proc = subprocess.run(
        [candidate, "--version"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return proc.returncode == 0
