"""Everything the server shares between the WebSocket, the API and background tasks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time

from starlette.websockets import WebSocket

from chess_mcp.config import ServerConfig
from chess_mcp.core.game import GameError, GameSession
from chess_mcp.core.store import Store
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.review.book import opening_name
from chess_mcp.server.agent_runner import AgentCommandRunner
from chess_mcp.server.auth import token_matches
from chess_mcp.server.claude_runner import ClaudeRunner
from chess_mcp.server.live_eval import LiveEval
from chess_mcp.server.reviews import ReviewService

log = logging.getLogger("chess_mcp")
PRESENCE_SECONDS = 60
ELO_MIN, ELO_MAX = 1320, 3190  # what Stockfish's UCI_Elo accepts


DEFAULT_OPPONENTS = [
    {"id": "pip", "name": "Pip", "description": "A five-year-old who has just learned how the pieces move. Plays fast, leaves pieces hanging, misses every threat and loves giving check. Never looks at the engine."},
    {"id": "rosa", "name": "Rosa", "description": "A friendly club player, around 1400. Develops sensibly and likes simple plans, but misses tactics more than two moves deep. Encouraging in chat."},
    {"id": "viktor", "name": "Viktor", "description": "A coffee-house attacker, around 1800. Loves gambits and kingside sacrifices, teases a little, and would rather lose brilliantly than win a dull endgame."},
    {"id": "professor", "name": "The Professor", "description": "A patient positional master at full strength. Uses the engine freely, prefers quiet squeezes and endgames, and says little unless asked."},
]
NAME_MAX, DESCRIPTION_MAX = 40, 1000


def parse_elo(value) -> int:
    try:
        elo = int(value)
    except (TypeError, ValueError):
        raise GameError("bad_elo", f"elo must be a whole number between {ELO_MIN} and {ELO_MAX}.") from None
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
        if config.agent_cmd:
            self.claude = AgentCommandRunner(config, self.token, self.session, self.schedule_broadcast)
        else:
            self.claude = ClaudeRunner(config, store, self.token, self.session, self.schedule_broadcast)
        settings = store.load_settings()
        saved = settings.get("opponents")
        self.opponents: list[dict] = saved if isinstance(saved, list) else [dict(o) for o in DEFAULT_OPPONENTS]
        self.opponent_id: str | None = settings.get("opponent_id") or (self.opponents[0]["id"] if self.opponents else None)
        if self.session.opponent is None and not self.session.board.move_stack:
            self.session.opponent = self._snapshot(self.opponent_id)  # the board a first visit lands on
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

    # ---- opponents ----
    def _save_opponents(self) -> None:
        self.store.save_settings({**self.store.load_settings(), "opponents": self.opponents, "opponent_id": self.opponent_id})
        self.schedule_broadcast()

    def save_opponent(self, opponent_id: str | None, name, description) -> str:
        """Create an opponent (no id) or change one. Returns its id."""
        if not isinstance(name, str) or not isinstance(description, str) or not name.strip() or not description.strip():
            raise GameError("bad_opponent", "An opponent needs a name and a description.")
        fields = {"name": name.strip()[:NAME_MAX], "description": description.strip()[:DESCRIPTION_MAX]}
        if opponent_id is None:
            opponent_id = secrets.token_hex(4)
            self.opponents.append({"id": opponent_id, **fields})
        else:
            self._opponent(opponent_id).update(fields)
        self._save_opponents()
        return opponent_id

    def delete_opponent(self, opponent_id: str) -> None:
        self.opponents.remove(self._opponent(opponent_id))
        if self.opponent_id == opponent_id:
            self.opponent_id = self.opponents[0]["id"] if self.opponents else None
        self._save_opponents()

    def start_game(self, human_color, by: str, opponent_id: str | None = None) -> None:
        """A new game against the chosen opponent, which becomes the default for the next one."""
        if opponent_id is not None:
            self._opponent(opponent_id)
        self.session.new_game(human_color, by=by, opponent=self._snapshot(opponent_id or self.opponent_id))
        if opponent_id is not None and opponent_id != self.opponent_id:
            self.opponent_id = opponent_id
            self._save_opponents()

    def _snapshot(self, opponent_id) -> dict | None:
        found = next((o for o in self.opponents if o["id"] == opponent_id), None)
        return {"name": found["name"], "description": found["description"]} if found else None

    def _opponent(self, opponent_id) -> dict:
        for opponent in self.opponents:
            if opponent["id"] == opponent_id:
                return opponent
        raise GameError("unknown_opponent", "That opponent no longer exists.")

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
        state["opponents"] = {"list": self.opponents, "selected": self.opponent_id}
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
