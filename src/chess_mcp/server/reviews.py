"""Runs each game's review once, shares it between callers, caches it on disk."""

from __future__ import annotations

import asyncio
from typing import Callable

from chess_mcp.core.game import GameError
from chess_mcp.core.store import Store
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.review.analyzer import review_game
from chess_mcp.review.model import Review


class ReviewService:
    def __init__(self, store: Store, engines: EngineRegistry, depth: int):
        self.store = store
        self.engines = engines
        self.depth = depth
        self.listeners: list[Callable[[str, int, int], None]] = []
        self._tasks: dict[str, asyncio.Task[Review]] = {}
        self._progress: dict[str, tuple[int, int]] = {}

    def start(self, game_id: str) -> asyncio.Future[Review]:
        if game_id in self._tasks:
            return self._tasks[game_id]
        cached = self.store.load_review(game_id)
        loop = asyncio.get_running_loop()
        if cached is not None:
            done: asyncio.Future[Review] = loop.create_future()
            done.set_result(Review.from_dict(cached))
            return done
        record = self.store.load_game(game_id)
        if record is None:
            raise GameError("unknown_game", f"No saved game with id {game_id!r}.")
        if not self.engines.has("stockfish"):
            raise GameError("no_engine", "Stockfish is not installed on the server, so games can't be reviewed.")
        task = loop.create_task(self._run(game_id, record))
        self._tasks[game_id] = task
        return task

    def progress(self, game_id: str) -> tuple[int, int] | None:
        return self._progress.get(game_id)

    async def _run(self, game_id: str, record: dict) -> Review:
        def report(done: int, total: int) -> None:
            self._progress[game_id] = (done, total)
            for listener in list(self.listeners):
                listener(game_id, done, total)

        try:
            review = await review_game(record, self.engines.get("stockfish"), self.depth, report)
            self.store.save_review(game_id, review.to_dict())
            return review
        finally:
            self._tasks.pop(game_id, None)
            self._progress.pop(game_id, None)
