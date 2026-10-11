"""Short background evaluation for the UI's eval bar. Never shown to Claude."""

from __future__ import annotations

import asyncio
from typing import Callable

import chess

from chess_mcp.engines.base import EngineError, Limit
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.review.winprob import win_pct_white


class LiveEval:
    def __init__(self, engines: EngineRegistry, depth: int, on_update: Callable[[], None]):
        self.engines = engines
        self.depth = depth
        self.on_update = on_update
        self._fen: str | None = None
        self._result: dict | None = None
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, board: chess.Board) -> None:
        fen = board.fen()
        if fen == self._fen:
            return
        self._fen = fen
        self._result = None
        if board.outcome(claim_draw=True) is not None or not self.engines.has("stockfish"):
            return
        task = asyncio.get_running_loop().create_task(self._run(board.copy()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, board: chess.Board) -> None:
        try:
            analysis = await self.engines.get("stockfish").analyse(board, Limit(depth=self.depth))
        except EngineError:
            return
        if not analysis.lines or board.fen() != self._fen:
            return
        score = analysis.lines[0].score
        self._result = {"fen": board.fen(), "text": score.text(), "win_white": round(win_pct_white(score), 1)}
        self.on_update()

    def current(self, fen: str) -> dict | None:
        if self._result and self._result["fen"] == fen:
            return self._result
        return None
