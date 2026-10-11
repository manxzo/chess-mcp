"""Short background evaluation for the UI's eval bar. Never shown to Claude.

One worker at a time: while it is busy, new positions only replace the
target, so a quick exchange of moves never queues stale evaluations.
"""

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
        self._target: chess.Board | None = None
        self._result: dict | None = None
        self._worker: asyncio.Task | None = None

    def schedule(self, board: chess.Board) -> None:
        fen = board.fen()
        if fen == self._fen:
            return
        self._fen = fen
        self._result = None
        if board.outcome(claim_draw=True) is not None or not self.engines.has("stockfish"):
            self._target = None
            return
        self._target = board.copy()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while self._target is not None:
            board, self._target = self._target, None
            try:
                analysis = await self.engines.get("stockfish").analyse(board, Limit(depth=self.depth))
            except EngineError:
                continue
            if not analysis.lines or board.fen() != self._fen:
                continue
            score = analysis.lines[0].score
            self._result = {"fen": board.fen(), "text": score.text(), "win_white": round(win_pct_white(score), 1)}
            self.on_update()

    def current(self, fen: str) -> dict | None:
        if self._result and self._result["fen"] == fen:
            return self._result
        return None
