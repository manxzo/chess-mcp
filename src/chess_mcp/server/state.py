"""Everything the server shares between the WebSocket, the API and background tasks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from starlette.websockets import WebSocket

from chess_mcp.config import ServerConfig
from chess_mcp.core.game import GameError, GameSession
from chess_mcp.core.store import Store
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.review.book import opening_name
from chess_mcp.server.auth import token_matches
from chess_mcp.server.claude_runner import ClaudeRunner
from chess_mcp.server.live_eval import LiveEval
from chess_mcp.server.reviews import ReviewService

log = logging.getLogger("chess_mcp")
PRESENCE_SECONDS = 60
ELO_MIN, ELO_MAX = 1320, 3190  # what Stockfish's UCI_Elo accepts


def parse_elo(value) -> int | None:
    """None means 'Claude': no target strength."""
    if value is None:
        return None
    try:
        elo = int(value)
    except (TypeError, ValueError):
        raise GameError("bad_elo", f"elo must be a whole number between {ELO_MIN} and {ELO_MAX}, or null.") from None
    if not ELO_MIN <= elo <= ELO_MAX:
        raise GameError("bad_elo", f"elo must be between {ELO_MIN} and {ELO_MAX}.")
    return elo


def load_session(store: Store) -> GameSession:
    record = store.load_current()
    if record is not None:
        try:
            return GameSession.from_record(record)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("saved game is unreadable (%s); starting a new one", exc)
            store.discard_current()
    return GameSession()


class AppState:
    def __init__(self, config: ServerConfig, store: Store, engines: EngineRegistry):
        self.config = config
        self.store = store
        self.engines = engines
        self.token = None if config.no_auth else (config.token or store.token())
        self.session = load_session(store)
        self.session.listeners.append(self._on_session_change)
        self.sockets: set[WebSocket] = set()
        self.live = LiveEval(engines, config.eval_depth, self.schedule_broadcast)
        self.reviews = ReviewService(store, engines, config.review_depth)
        self.claude = ClaudeRunner(config, store, self.token, self.session, self.schedule_broadcast)
        try:
            self.difficulty: int | None = parse_elo(store.load_settings().get("elo"))
        except GameError:
            self.difficulty = None
        self._claude_waits = 0
        self._claude_last_seen = 0.0
        self._last_presence = False
        self._broadcast_pending = False
        self._seq = 0

    # ---- session changes ----
    def _on_session_change(self) -> None:
        s = self.session
        if s.status != "active" and not s.archived:
            s.archived = True
            if s.board.move_stack:
                record = s.to_record()
                record["opening"] = opening_name(record["moves"])
                self.store.archive(record, s.pgn())
        self.store.save_current(s.to_record())
        self.live.schedule(s.board)
        self.schedule_broadcast()
        self.claude.on_session_change()

    # ---- difficulty ----
    def set_difficulty(self, elo: int | None) -> None:
        """The target Elo for new games; also applies to the game in progress."""
        self.difficulty = elo
        self.store.save_settings({**self.store.load_settings(), "elo": elo})
        self.session.set_elo(elo)
        self.schedule_broadcast()

    # ---- access ----
    def accepts(self, secret: str | None) -> bool:
        """The browser may present the access token or the password; the API uses the token."""
        if self.token is None:
            return True
        if token_matches(secret, self.token):
            return True
        return self.config.password is not None and token_matches(secret, self.config.password)

    # ---- broadcasting ----
    def schedule_broadcast(self) -> None:
        if self._broadcast_pending:
            return
        self._broadcast_pending = True
        asyncio.get_running_loop().create_task(self._broadcast())

    async def _broadcast(self) -> None:
        self._broadcast_pending = False
        payload = self.browser_state()
        for ws in list(self.sockets):
            try:
                await ws.send_json(payload)
            except Exception:
                self.sockets.discard(ws)

    def browser_state(self) -> dict:
        state = self.session.browser_state()
        state["type"] = "state"
        self._seq += 1
        state["seq"] = self._seq  # lets a tab drop a snapshot that arrives after a newer one
        state["claude_connected"] = self.claude_connected()
        state["claude"] = self.claude.view()
        state["difficulty"] = {"elo": self.difficulty, "min": ELO_MIN, "max": ELO_MAX}
        state["eval"] = self.live.current(self.session.board.fen())
        return state

    # ---- Claude ----
    def claude_view(self, mark_seen: bool = True) -> dict:
        view = self.session.claude_view(mark_seen)
        view["ui_url"] = self.config.ui_url
        return view

    def claude_connected(self) -> bool:
        return self._claude_waits > 0 or time.monotonic() - self._claude_last_seen < PRESENCE_SECONDS

    def mark_claude_seen(self) -> None:
        self._claude_last_seen = time.monotonic()
        self.check_presence()

    def claude_wait_started(self) -> None:
        self._claude_waits += 1
        self.mark_claude_seen()

    def claude_wait_finished(self) -> None:
        self._claude_waits = max(0, self._claude_waits - 1)
        self._claude_last_seen = time.monotonic()

    def check_presence(self) -> None:
        now = self.claude_connected()
        if now != self._last_presence:
            self._last_presence = now
            with contextlib.suppress(RuntimeError):  # no running loop (e.g. at import)
                self.schedule_broadcast()
