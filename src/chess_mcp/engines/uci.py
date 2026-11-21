"""Any UCI engine, driven through python-chess's async API."""

from __future__ import annotations

import asyncio
import contextlib

import chess
import chess.engine

from chess_mcp.engines.base import Analysis, EngineError, Limit, Line, Score

DEFAULT_DEPTH = 18


class UciEngine:
    def __init__(self, name: str, path: str, options: dict | None = None):
        self.name = name
        self.path = path
        self.options = options or {}
        self._engine: chess.engine.UciProtocol | None = None
        self._transport: asyncio.SubprocessTransport | None = None
        self._lock = asyncio.Lock()

    async def _start(self) -> None:
        self._transport, self._engine = await chess.engine.popen_uci(self.path)
        if self.options:
            await self._engine.configure(self.options)

    async def analyse(self, board: chess.Board, limit: Limit, multipv: int = 1) -> Analysis:
        depth = limit.depth if (limit.depth or limit.time_s) else DEFAULT_DEPTH
        engine_limit = chess.engine.Limit(depth=depth, time=limit.time_s)
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._engine is None:
                        await self._start()
                    infos = await self._engine.analyse(board, engine_limit, multipv=multipv)
                    break
                except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError) as exc:
                    self._engine = None
                    if attempt == 2:
                        raise EngineError(f"{self.name} failed: {exc}") from exc
        lines = [
            Line(move=info["pv"][0].uci(), pv=[m.uci() for m in info["pv"]], score=Score.from_pov(info["score"]))
            for info in infos
            if info.get("pv")
        ]
        return Analysis(depth=max((info.get("depth", 0) for info in infos), default=0), lines=lines)

    async def close(self) -> None:
        if self._engine is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._engine.quit(), 2)
            self._engine = None
