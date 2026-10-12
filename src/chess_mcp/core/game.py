"""One game of chess between the human and Claude.

Owns the board, the chat log, the game status, and what Claude has already
seen. Knows nothing about HTTP, MCP or engines. Every mutation bumps
`version`, wakes `wait_for_change`, and calls each listener.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Literal

import chess
import chess.pgn

Side = Literal["human", "claude"]
MAX_CHAT_CHARS = 2000
_UCI_LIKE = re.compile(r"^([a-h][1-8])-?([a-h][1-8])([qrbn])?$")


class GameError(Exception):
    """A rule or request error that is shown to the player as-is."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ChatMessage:
    id: int
    sender: str  # "human" | "claude"
    text: str
    ts: float
    ply: int


def color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def parse_color(text: str) -> chess.Color:
    if text == "white":
        return chess.WHITE
    if text == "black":
        return chess.BLACK
    if text == "random":
        return random.choice([chess.WHITE, chess.BLACK])
    raise GameError("bad_color", f"Colour must be white, black or random, not {text!r}.")


def new_game_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{random.randrange(16**4):04x}"


def _other(side: Side) -> Side:
    return "claude" if side == "human" else "human"


class GameSession:
    def __init__(self, human_color: chess.Color = chess.WHITE, game_id: str | None = None):
        self.listeners: list[Callable[[], None]] = []
        self.version = 0
        self._changed = asyncio.Event()
        self.claude_seen_game_id: str | None = None
        self._reset(human_color, game_id)

    def _reset(self, human_color: chess.Color, game_id: str | None) -> None:
        self.game_id = game_id or new_game_id()
        self.started_at = time.time()
        self.elo: int | None = None
        self.ended_at: float | None = None
        self.human_color = human_color
        self.board = chess.Board()
        self.chat: list[ChatMessage] = []
        self.status = "active"
        self.result = "*"
        self.reason: str | None = None
        self.winner: str | None = None
        self.draw_offer: Side | None = None
        self.claude_chat_seen = 0
        self.claude_seen_game_over = False
        self.archived = False

    # ---- sides -------------------------------------------------------
    @property
    def claude_color(self) -> chess.Color:
        return not self.human_color

    def color_of(self, side: Side) -> chess.Color:
        return self.human_color if side == "human" else self.claude_color

    def side_to_move(self) -> Side:
        return "human" if self.board.turn == self.human_color else "claude"

    # ---- mutations ---------------------------------------------------
    def new_game(self, human_color: chess.Color, by: Side, elo: int | None = None) -> None:
        if self.status == "active" and len(self.board.move_stack) >= 2:
            raise GameError("game_in_progress", "Finish or resign the current game first.")
        self._reset(human_color, None)
        self.elo = elo
        if by == "claude":
            self.claude_seen_game_id = self.game_id
        self._notify()

    def set_elo(self, elo: int | None) -> None:
        if elo != self.elo:
            self.elo = elo
            self._notify()

    def play(self, move: str, by: Side) -> str:
        self._require_active()
        if self.side_to_move() != by:
            raise GameError("not_your_turn", f"It is {self.side_to_move()}'s turn, not {by}'s.")
        parsed = self._parse_move(move)
        san = self.board.san(parsed)
        self.board.push(parsed)
        if self.draw_offer == _other(by):
            self.draw_offer = None
        self._check_board_end()
        self._notify()
        return san

    def add_chat(self, sender: Side, text: str) -> ChatMessage:
        text = text.strip()
        if not text:
            raise GameError("empty_message", "Message is empty.")
        msg = ChatMessage(
            id=len(self.chat) + 1,
            sender=sender,
            text=text[:MAX_CHAT_CHARS],
            ts=time.time(),
            ply=len(self.board.move_stack),
        )
        self.chat.append(msg)
        self._notify()
        return msg

    def resign(self, by: Side) -> None:
        self._require_active()
        self._end("resigned", self.color_of(_other(by)), f"{color_name(self.color_of(by))} resigned")
        self._notify()

    def offer_draw(self, by: Side) -> None:
        self._require_active()
        if self.draw_offer == _other(by):
            self._end("draw_agreed", None, "draw agreed")
        else:
            self.draw_offer = by
        self._notify()

    def answer_draw(self, by: Side, accept: bool) -> None:
        self._require_active()
        if self.draw_offer != _other(by):
            raise GameError("no_draw_offer", "There is no draw offer to answer.")
        if accept:
            self._end("draw_agreed", None, "draw agreed")
        else:
            self.draw_offer = None
        self._notify()

    # ---- Claude's view -------------------------------------------------
    def claude_events(self) -> list[str]:
        events = []
        if self.claude_seen_game_id != self.game_id:
            events.append("new_game")
        if self.status != "active" and not self.claude_seen_game_over:
            events.append("game_over")
        if self.draw_offer == "human":
            events.append("draw_offer")
        if any(m.sender == "human" and m.id > self.claude_chat_seen for m in self.chat):
            events.append("message")
        if self.status == "active" and self.side_to_move() == "claude":
            events.append("your_move")
        return events

    def claude_view(self, mark_seen: bool) -> dict:
        your_turn = self.status == "active" and self.side_to_move() == "claude"
        new_messages = [m.text for m in self.chat if m.sender == "human" and m.id > self.claude_chat_seen]
        view = {
            "game_id": self.game_id,
            "you_play": color_name(self.claude_color),
            "status": self.status,
            "result": self.result,
            "reason": self.reason,
            "turn": color_name(self.board.turn),
            "your_turn": your_turn,
            "in_check": self.board.is_check(),
            "fen": self.board.fen(),
            "board": self.board_text(self.claude_color),
            "moves": self.movetext(),
            "last_move": self._last_san(),
            "legal_moves": [self.board.san(m) for m in self.board.legal_moves] if your_turn else [],
            "draw_offer": self.draw_offer,
            "new_messages": new_messages,
            "target_elo": self.elo,
        }
        if mark_seen:
            changed = (
                self.claude_seen_game_id != self.game_id
                or bool(new_messages)
                or (self.status != "active" and not self.claude_seen_game_over)
            )
            self.claude_seen_game_id = self.game_id
            self.claude_chat_seen = max((m.id for m in self.chat), default=0)
            if self.status != "active":
                self.claude_seen_game_over = True
            if changed:
                self._notify()
        return view

    # ---- browser view --------------------------------------------------
    def browser_state(self) -> dict:
        dests: dict[str, list[str]] = {}
        if self.status == "active" and self.side_to_move() == "human":
            for mv in self.board.legal_moves:
                targets = dests.setdefault(chess.square_name(mv.from_square), [])
                to = chess.square_name(mv.to_square)
                if to not in targets:
                    targets.append(to)
        last = self.board.peek() if self.board.move_stack else None
        return {
            "game_id": self.game_id,
            "fen": self.board.fen(),
            "turn": color_name(self.board.turn),
            "human_color": color_name(self.human_color),
            "moves": self._replay(),
            "last_move": [chess.square_name(last.from_square), chess.square_name(last.to_square)] if last else None,
            "check": self.board.is_check(),
            "dests": dests,
            "status": self.status,
            "result": self.result,
            "reason": self.reason,
            "winner": self.winner,
            "draw_offer": self.draw_offer,
            "chat": [asdict(m) for m in self.chat],
            "elo": self.elo,
        }

    # ---- waiting ---------------------------------------------------------
    async def wait_for_change(self, timeout: float) -> bool:
        event = self._changed
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except TimeoutError:
            return False

    # ---- text helpers ------------------------------------------------------
    def board_text(self, perspective: chess.Color) -> str:
        ranks = range(7, -1, -1) if perspective == chess.WHITE else range(8)
        files = list(range(8)) if perspective == chess.WHITE else list(range(7, -1, -1))
        rows = []
        for rank in ranks:
            cells = []
            for file in files:
                piece = self.board.piece_at(chess.square(file, rank))
                cells.append(piece.symbol() if piece else ".")
            rows.append(f"{rank + 1} " + " ".join(cells))
        rows.append("  " + " ".join(chess.FILE_NAMES[f] for f in files))
        return "\n".join(rows)

    def movetext(self) -> str:
        if not self.board.move_stack:
            return ""
        return chess.Board().variation_san(self.board.move_stack)

    def pgn(self) -> str:
        game = chess.pgn.Game()
        headers = game.headers
        headers["Event"] = "Chess vs Claude"
        headers["Site"] = "chess-mcp"
        headers["Date"] = datetime.fromtimestamp(self.started_at).strftime("%Y.%m.%d")
        headers["White"] = "Human" if self.human_color == chess.WHITE else "Claude"
        headers["Black"] = "Claude" if self.human_color == chess.WHITE else "Human"
        headers["Result"] = self.result
        if self.reason:
            headers["Termination"] = self.reason
        nodes: list[chess.pgn.GameNode] = [game]
        node: chess.pgn.GameNode = game
        for mv in self.board.move_stack:
            node = node.add_variation(mv)
            nodes.append(node)
        for msg in self.chat:
            target = nodes[min(msg.ply, len(nodes) - 1)]
            speaker = "Human" if msg.sender == "human" else "Claude"
            target.comment = (target.comment + " " if target.comment else "") + f"{speaker}: {msg.text}"
        return str(game)

    # ---- persistence -------------------------------------------------------
    def to_record(self) -> dict:
        return {
            "game_id": self.game_id,
            "started_at": self.started_at,
            "elo": self.elo,
            "ended_at": self.ended_at,
            "human_color": color_name(self.human_color),
            "moves": [m.uci() for m in self.board.move_stack],
            "chat": [asdict(m) for m in self.chat],
            "status": self.status,
            "result": self.result,
            "reason": self.reason,
            "winner": self.winner,
            "draw_offer": self.draw_offer,
            "claude_chat_seen": self.claude_chat_seen,
            "claude_seen_game_id": self.claude_seen_game_id,
            "claude_seen_game_over": self.claude_seen_game_over,
            "archived": self.archived,
        }

    @classmethod
    def from_record(cls, record: dict) -> GameSession:
        human = chess.WHITE if record["human_color"] == "white" else chess.BLACK
        session = cls(human_color=human, game_id=record["game_id"])
        for uci in record["moves"]:
            move = chess.Move.from_uci(uci)
            if move not in session.board.legal_moves:
                raise ValueError(f"illegal move {uci} in saved game")
            session.board.push(move)
        session.started_at = record["started_at"]
        session.elo = record.get("elo")
        session.ended_at = record["ended_at"]
        session.chat = [ChatMessage(**m) for m in record["chat"]]
        session.status = record["status"]
        session.result = record["result"]
        session.reason = record["reason"]
        session.winner = record["winner"]
        session.draw_offer = record["draw_offer"]
        session.claude_chat_seen = record["claude_chat_seen"]
        session.claude_seen_game_id = record["claude_seen_game_id"]
        session.claude_seen_game_over = record["claude_seen_game_over"]
        session.archived = record["archived"]
        return session

    # ---- internals -----------------------------------------------------------
    def _require_active(self) -> None:
        if self.status != "active":
            raise GameError("game_over", f"The game is over ({self.result}, {self.reason}).")

    def _parse_move(self, text: str) -> chess.Move:
        cleaned = text.strip().rstrip("+#!?")
        match = _UCI_LIKE.match(cleaned.lower())
        if match:
            move = chess.Move.from_uci("".join(g for g in match.groups() if g))
            if move in self.board.legal_moves:
                return move
        try:
            return self.board.parse_san(cleaned)
        except ValueError:
            pass
        sample = ", ".join(sorted(self.board.san(m) for m in self.board.legal_moves)[:12])
        raise GameError("illegal_move", f"{text.strip()!r} is not a legal move here. Legal moves include: {sample}.")

    def _check_board_end(self) -> None:
        outcome = self.board.outcome(claim_draw=True)
        if outcome is None:
            return
        status = outcome.termination.name.lower()
        self._end(status, outcome.winner, status.replace("_", " "))

    def _end(self, status: str, winner: chess.Color | None, reason: str) -> None:
        self.status = status
        self.winner = None if winner is None else color_name(winner)
        self.result = "1/2-1/2" if winner is None else ("1-0" if winner == chess.WHITE else "0-1")
        self.reason = reason
        self.ended_at = time.time()
        self.draw_offer = None

    def _last_san(self) -> str | None:
        if not self.board.move_stack:
            return None
        before = self.board.copy()
        last = before.pop()
        return before.san(last)

    def _replay(self) -> list[dict]:
        board = chess.Board()
        out = []
        for mv in self.board.move_stack:
            out.append({"san": board.san(mv), "uci": mv.uci()})
            board.push(mv)
        return out

    def _notify(self) -> None:
        self.version += 1
        old, self._changed = self._changed, asyncio.Event()
        old.set()
        for listener in list(self.listeners):
            listener()
