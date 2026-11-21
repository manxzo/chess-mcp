import asyncio

import chess

from chess_mcp.core.game import GameSession
from chess_mcp.core.store import Store
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.server.live_eval import LiveEval
from chess_mcp.server.reviews import ReviewService
from tests.fakes import FakeEngine


class SlowEngine(FakeEngine):
    async def analyse(self, board, limit, multipv=1):
        await asyncio.sleep(0.05)
        return await super().analyse(board, limit, multipv)


async def test_live_eval_skips_positions_that_are_already_stale():
    engine = SlowEngine()
    updates = []
    live = LiveEval(EngineRegistry.with_engines({"stockfish": engine}), 10, lambda: updates.append(1))
    board = chess.Board()
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]:
        board.push_uci(uci)
        live.schedule(board)
    for _ in range(50):
        if live.current(board.fen()):
            break
        await asyncio.sleep(0.02)
    assert live.current(board.fen()) is not None
    assert engine.calls <= 2


async def test_reviews_use_their_own_engine(tmp_path):
    shared, own = FakeEngine(), FakeEngine()
    engines = EngineRegistry.with_engines({"stockfish": shared}, dedicated={"stockfish": own})
    store = Store(tmp_path)
    s = GameSession(game_id="20261011-120000-abcd")
    s.play("e4", by="human")
    s.resign("human")
    store.archive(s.to_record(), s.pgn())
    review = await ReviewService(store, engines, depth=5).start(s.game_id)
    assert review.moves[0].san == "e4"
    assert own.calls > 0
    assert shared.calls == 0
