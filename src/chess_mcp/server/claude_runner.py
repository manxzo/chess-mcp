"""Hosts Claude on the server: Claude Code sign-in, and a headless `claude -p` that plays through the MCP tools.

The process speaks stream-json on stdin/stdout. It is "busy" from the moment we send it a user
message until it emits a `result`; while idle, the runner wakes it whenever the game has events
for Claude, so Claude never has to poll between games.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from chess_mcp.config import ServerConfig
from chess_mcp.core.game import GameError, GameSession
from chess_mcp.core.store import Store

log = logging.getLogger("chess_mcp.claude")

MODELS = [
    ("claude-fable-5-1", "Fable 5.1"),
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5-5", "Sonnet 5.5"),
    ("claude-haiku-5-5", "Haiku 5.5"),
]
DEFAULT_MODEL = "claude-opus-5-5"
LOGIN_TIMEOUT = 600
STOP_GRACE = 5
COMMAND_TIMEOUT = 60
LINE_LIMIT = 8 * 1024 * 1024
_URL = re.compile(r"https://\S+")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

SYSTEM_PROMPT = """\
You are the chess opponent in a web UI. Play only through the chess tools; you have no other job here.
Keep playing while a game is active. When a game ends, call get_review and talk the user through the
key moments, then stop and end your turn: you will receive a message when the user starts a new game
or writes to you. In reviews, 'Human' is the user and 'Claude' is you."""

OPENING_MESSAGE = "Let's play chess. Call get_game to see the board and whether the user is waiting for you."


def find_claude(configured: str | None) -> str | None:
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.is_file() else None


class ClaudeRunner:
    def __init__(
        self,
        config: ServerConfig,
        store: Store,
        token: str | None,
        session: GameSession,
        on_change: Callable[[], None],
    ):
        self.config = config
        self.store = store
        self.token = token
        self.session = session
        self.on_change = on_change
        self.path = find_claude(config.claude_path)
        if config.claude_path and self.path is None:
            log.warning("CHESS_CLAUDE_PATH=%s is not a file; hosted Claude is unavailable", config.claude_path)
        self.config_dir = config.data_dir / "claude"
        self.work_dir = self.config_dir / "work"
        self.model = store.load_settings().get("claude_model", DEFAULT_MODEL)
        if self.model not in dict(MODELS):
            self.model = DEFAULT_MODEL
        self.status = "stopped"
        self.error: str | None = None
        self.auth: dict = {"logged_in": False, "email": None, "method": None}
        self.login_url: str | None = None
        self._login: asyncio.subprocess.Process | None = None
        self._login_task: asyncio.Task | None = None
        self._code_sent = False
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._stderr: collections.deque[str] = collections.deque(maxlen=30)
        self._busy = False
        self._nudged: tuple[str, ...] | None = None
        self._stop_requested = False

    # ---- lifecycle ----
    async def startup(self) -> None:
        if self.path is None:
            return
        self.work_dir.mkdir(parents=True, exist_ok=True)
        await self.refresh_auth()

    async def shutdown(self) -> None:
        await self.cancel_login()
        await self.stop()

    @property
    def available(self) -> bool:
        return self.path is not None

    @property
    def busy(self) -> bool:
        return self._busy

    def view(self) -> dict:
        return {
            "available": self.available,
            "status": self.status,
            "model": self.model,
            "models": [{"id": model_id, "name": name} for model_id, name in MODELS],
            "error": self.error,
            "auth": {"logged_in": self.auth["logged_in"], "email": self.auth["email"]},
            "login": {"url": self.login_url, "busy": self._login is not None, "verifying": self._code_sent},
        }

    def _changed(self) -> None:
        with contextlib.suppress(RuntimeError):  # no running loop
            self.on_change()

    def _env(self) -> dict[str, str]:
        return {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config_dir)}

    def _require_available(self) -> None:
        if self.path is None:
            raise GameError("claude_unavailable", "Claude Code isn't installed on the server.")

    async def _spawn(self, *args: str, **kwargs) -> asyncio.subprocess.Process:
        assert self.path is not None
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return await asyncio.create_subprocess_exec(self.path, *args, env=self._env(), cwd=self.work_dir, **kwargs)

    async def _run(self, *args: str) -> tuple[str, str, int]:
        proc = await self._spawn(*args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), COMMAND_TIMEOUT)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"claude {' '.join(args)} timed out", -1
        return out.decode(errors="replace"), err.decode(errors="replace"), proc.returncode or 0

    # ---- auth ----
    async def refresh_auth(self) -> None:
        if self.path is None:
            return
        out, err, code = await self._run("auth", "status", "--json")
        try:
            data = json.loads(out)
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            data = {}
            if code != 0:
                log.warning("claude auth status failed (%s): %s", code, _tail(err) or _tail(out))
        self.auth = {"logged_in": bool(data.get("loggedIn")), "email": data.get("email"), "method": data.get("authMethod")}
        self._changed()

    async def login(self) -> None:
        self._require_available()
        if self._login is not None:
            raise GameError("claude_busy", "A sign-in is already in progress.")
        self.error = None
        self.login_url = None
        self._code_sent = False
        proc = await self._spawn("auth", "login", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        self._login = proc
        self._login_task = asyncio.create_task(self._watch_login(proc))
        self._changed()

    async def _watch_login(self, proc: asyncio.subprocess.Process) -> None:
        output: list[str] = []
        assert proc.stdout is not None
        try:
            async with asyncio.timeout(LOGIN_TIMEOUT):
                while self.login_url is None:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = _ANSI.sub("", line.decode(errors="replace"))
                    output.append(text)
                    if match := _URL.search(text):
                        self.login_url = match.group(0).rstrip(".,)")
                        self._changed()
                while chunk := await proc.stdout.read(4096):
                    output.append(_ANSI.sub("", chunk.decode(errors="replace")))
                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            output.append("Sign-in timed out.")
        except asyncio.CancelledError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise
        finally:
            self._login = None
            self.login_url = None
            self._code_sent = False
            self._changed()
        if proc.returncode == 0:
            await self.refresh_auth()
        else:
            self.error = f"Sign-in failed: {_tail(''.join(output)) or f'exit code {proc.returncode}'}"
            log.warning(self.error)
            self._changed()

    async def submit_code(self, code: str) -> None:
        proc = self._login
        if proc is None or self.login_url is None:
            raise GameError("no_login", "Start the sign-in first.")
        if self._code_sent:
            raise GameError("claude_busy", "The code is being checked.")
        code = code.strip()
        if not code:
            raise GameError("bad_request", "Paste the code from the sign-in page.")
        assert proc.stdin is not None
        proc.stdin.write((code + "\n").encode())
        await proc.stdin.drain()
        self._code_sent = True
        self._changed()

    async def cancel_login(self) -> None:
        task = self._login_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def logout(self) -> None:
        self._require_available()
        await self.stop()
        _, err, code = await self._run("auth", "logout")
        if code != 0:
            log.warning("claude auth logout failed (%s): %s", code, _tail(err))
        await self.refresh_auth()

    # ---- the playing process ----
    async def set_model(self, model: str) -> None:
        if model not in dict(MODELS):
            raise GameError("bad_model", "Unknown model.")
        if model == self.model:
            return
        self.model = model
        self.store.save_settings({**self.store.load_settings(), "claude_model": model})
        self._changed()
        if self._proc is not None:
            await self.stop()
            await self.start()

    def _play_args(self) -> list[str]:
        env = {"CHESS_SERVER_URL": self.config.api_url}
        if self.token:
            env["CHESS_TOKEN"] = self.token
        mcp = {"mcpServers": {"chess": {"command": sys.executable, "args": ["-m", "chess_mcp", "mcp"], "env": env}}}
        return [
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
            "--permission-mode", "dontAsk",
            "--allowedTools", "mcp__chess",
            "--strict-mcp-config",
            "--mcp-config", json.dumps(mcp),
            "--disable-slash-commands",
            "--restricted",
            "--append-system-prompt", SYSTEM_PROMPT,
        ]  # fmt: skip

    async def start(self) -> None:
        self._require_available()
        if not self.auth["logged_in"]:
            raise GameError("claude_not_signed_in", "Sign in to Claude first.")
        if self._proc is not None:
            raise GameError("claude_busy", "Claude is already running.")
        self.error = None
        self.status = "starting"
        self._stop_requested = False
        self._busy = False
        self._nudged = None
        self._stderr.clear()
        self._changed()
        try:
            proc = await self._spawn(
                *self._play_args(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=LINE_LIMIT,
                start_new_session=True,
            )
        except OSError as exc:
            self.status = "error"
            self.error = f"Could not start Claude: {exc}"
            self._changed()
            return
        self._proc = proc
        self._reader = asyncio.create_task(self._read_output(proc))
        asyncio.create_task(self._read_stderr(proc))
        self._send(proc, OPENING_MESSAGE)

    def _send(self, proc: asyncio.subprocess.Process, text: str) -> None:
        assert proc.stdin is not None
        if proc.stdin.is_closing():
            return
        payload = {"type": "user", "message": {"role": "user", "content": text}}
        proc.stdin.write((json.dumps(payload) + "\n").encode())
        self._busy = True
        log.info("to Claude: %s", text)

    async def _read_output(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except ValueError:  # a line over LINE_LIMIT
                    log.warning("Claude sent an oversized line; ignoring it")
                    continue
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self._handle(msg)
        finally:
            await proc.wait()
            self._on_exit(proc)

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while line := await proc.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            if text:
                self._stderr.append(text)
                log.info("claude stderr: %s", text)

    def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "system" and msg.get("subtype") == "init":
            if self.status == "starting":
                self.status = "running"
            log.info("Claude is running (model %s)", msg.get("model"))
            self._changed()
        elif kind == "result":
            self._busy = False
            if msg.get("is_error"):
                self.error = str(msg.get("result") or msg.get("subtype") or "Claude reported an error")[:400]
                log.warning("Claude turn failed: %s", self.error)
            self._changed()
            self._maybe_nudge()
        elif kind == "assistant":
            for block in (msg.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    log.debug("Claude: %s", block["text"])

    def _on_exit(self, proc: asyncio.subprocess.Process) -> None:
        if self._proc is not proc:
            return
        self._proc = None
        self._busy = False
        if self._stop_requested:
            self.status = "stopped"
            log.info("Claude stopped")
        else:
            self.status = "error"
            tail = _tail("\n".join(self._stderr))
            self.error = f"Claude exited (code {proc.returncode})" + (f": {tail}" if tail else "")
            log.warning(self.error)
        self._changed()

    def on_session_change(self) -> None:
        self._maybe_nudge()

    def _maybe_nudge(self) -> None:
        proc = self._proc
        if proc is None or self.status != "running":
            return
        events = tuple(self.session.claude_events())
        if not events:
            self._nudged = None  # Claude dealt with everything; the next event is news again
            return
        if self._busy or events == self._nudged:
            return
        self._nudged = events
        self._send(proc, f"Update from the game: {', '.join(events)}. Call get_game and carry on.")

    async def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._stop_requested = True
        self.status = "stopping"
        self._changed()
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), STOP_GRACE)
        except TimeoutError:
            _signal_group(proc, signal.SIGKILL)
            await proc.wait()
        if self._reader is not None:
            with contextlib.suppress(Exception):
                await self._reader


def _signal_group(proc: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(sig)


def _tail(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""
