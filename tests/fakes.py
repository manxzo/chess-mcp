import chess

from chess_mcp.engines.base import Analysis, Limit, Line, Score


class FakeEngine:
    """Deterministic engine for tests: best move = first legal move in UCI order."""

    name = "fake"

    def __init__(self, cp: int = 20):
        self.cp = cp
        self.calls = 0

    async def analyse(self, board: chess.Board, limit: Limit, multipv: int = 1) -> Analysis:
        self.calls += 1
        moves = sorted(board.legal_moves, key=lambda m: m.uci())[:multipv]
        lines = [Line(move=m.uci(), pv=[m.uci()], score=Score(cp=self.cp - 50 * i)) for i, m in enumerate(moves)]
        return Analysis(depth=limit.depth or 1, lines=lines)

    async def close(self) -> None:
        pass
