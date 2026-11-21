"""Starts any AI agent from the web UI: runs the CHESS_AGENT_CMD shell command whenever the game needs the opponent.

The command is expected to be a headless agent run that has the `chess` MCP server registered and plays
until it has nothing left to do, e.g. `codex exec "Play chess with the chess tools until the game ends."`.
It gets CHESS_SERVER_URL and CHESS_TOKEN in its environment. When it exits and the game still has events
for the opponent, it is run again. Offers the same surface as ClaudeRunner, minus sign-in and models.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from collections.abc import Callable

from chess_mcp.config import ServerConfig
from chess_mcp.core.game import GameError, GameSession

log = logging.getLogger("chess_mcp.agent")
QUICK_EXIT_SECONDS = 5  # a run shorter than this that leaves work undone counts as a failure
MAX_FAILURES = 3
STOP_GRACE = 5


class AgentCommandRunner:
    available = True

    def __init__(self, config: ServerConfig, token: str | None, session: GameSession, on_change: Callable[[], None]):
        self.command = config.agent_cmd
        self.env = {**os.environ, "CHESS_SERVER_URL": config.api_url, **({"CHESS_TOKEN": token} if token else {})}
        self.session = session
        self.on_change = on_change
        self.status = "stopped"
        self.error: str | None = None
        self._wanted = False
        self._proc: asyncio.subprocess.Process | None = None
        self._failures = 0
        self._active = False

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        await self.stop()

    def view(self) -> dict:
        return {
            "available": True,
            "custom": True,  # the UI hides sign-in and the model picker
            "status": self.status,
            "model": None,
            "models": [],
            "error": self.error,
            "auth": {"logged_in": True, "email": None},
            "login": {"url": None, "busy": False, "verifying": False},
        }

    async def start(self) -> None:
        self._wanted = True
        self._failures = 0
        self.error = None
        self.status = "running"
        self._changed()
        self._kick()

    async def stop(self) -> None:
        self._wanted = False
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), STOP_GRACE)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
        if self.status != "error":
            self.status = "stopped"
        self._changed()

    def on_session_change(self) -> None:
        self._kick()

    def _kick(self) -> None:
        if self._wanted and not self._active and self.session.claude_events():
            with contextlib.suppress(RuntimeError):  # no running loop
                asyncio.get_running_loop().create_task(self._run())
                self._active = True  # set here, not in the task, so two quick changes start one run

    async def _run(self) -> None:
        started = time.monotonic()
        try:
            proc = self._proc = await asyncio.create_subprocess_shell(
                self.command,
                env=self.env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            log.info("agent command started (pid %s)", proc.pid)
            _, stderr = await proc.communicate()
        except OSError as exc:
            return self._fail(f"Could not start the agent command: {exc}")
        finally:
            self._active = False
            self._proc = None
        if not self._wanted:  # stopped meanwhile
            return
        if not self.session.claude_events():
            self._failures = 0
            return
        if proc.returncode != 0 or time.monotonic() - started < QUICK_EXIT_SECONDS:
            self._failures += 1
            if self._failures >= MAX_FAILURES:
                lines = [line.strip() for line in stderr.decode(errors="replace").splitlines() if line.strip()]
                return self._fail(f"The agent command keeps exiting (code {proc.returncode})" + (f": {lines[-1][:300]}" if lines else "."))
        self._kick()

    def _fail(self, message: str) -> None:
        self._wanted = False
        self.status = "error"
        self.error = message
        log.warning(message)
        self._changed()

    def _changed(self) -> None:
        with contextlib.suppress(RuntimeError):  # no running loop
            self.on_change()

    # Sign-in and models belong to the agent itself, not to this server.
    async def _unsupported(self, *args) -> None:
        raise GameError("not_supported", "This server starts its opponent with CHESS_AGENT_CMD; sign in and choose a model in that agent.")

    login = logout = cancel_login = submit_code = set_model = _unsupported
