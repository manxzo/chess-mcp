from chess_mcp.engines.base import Score
from chess_mcp.engines.uci import UciEngine
from chess_mcp.review.analyzer import PositionEval, analyse_positions, build_review, review_game
from chess_mcp.review.book import book_plies
from chess_mcp.review.model import Review
from tests.fakes import FakeEngine

# 1. e4 a6 2. Qg4 a5 3. Qxg7?? Bxg7 — White hangs the queen on move 3.
BLUNDER_GAME = ["e2e4", "a7a6", "d1g4", "a6a5", "g4g7", "f8g7"]


def record(moves, human="white", result="0-1"):
    return {"game_id": "20261011-120000-abcd", "moves": moves, "human_color": human, "result": result, "reason": "white resigned"}


def flat(win: float, best: str | None = None, second: float | None = None, legal: int = 20) -> PositionEval:
    return PositionEval(win_white=win, score=Score(cp=0), best_uci=best, pv_uci=[best] if best else [], second_win_white=second, legal_count=legal)


def test_build_review_rates_a_hand_built_game():
    moves = ["e2e4", "e7e5", "g1f3"]
    evals = [
        flat(55, best="e2e4", second=54),  # before 1. e4
        flat(55, best="g8f6", second=54),  # before 1... e5 (best was Nf6)
        flat(30, best="b1c3", second=29),  # before 2. Nf3: White dropped to 30
        flat(30),
    ]
    review = build_review(record(moves), evals, depth=18)
    assert [m.rating for m in review.moves] == ["book", "book", "book"]  # all in theory
    assert review.opening is not None
    assert len(review.eval_series) == 4


def test_build_review_outside_book():
    moves = BLUNDER_GAME
    assert book_plies(moves) == 2
    evals = [
        flat(55, best="e2e4", second=54),
        flat(55, best="e7e5", second=54),
        flat(60, best="d2d4", second=59),  # 2. Qg4: best was d4, small loss
        flat(57, best="a6a5", second=56),
        flat(62, best="b1c3", second=61),  # 3. Qxg7?? drops to 5
        flat(5, best="f8g7", second=4),
        flat(5),
    ]
    review = build_review(record(moves), evals, depth=18)
    ratings = [m.rating for m in review.moves]
    assert ratings[:2] == ["book", "book"]
    assert ratings[2] == "good"  # 60 → 57, loss 3
    assert ratings[3] == "best"
    assert ratings[4] == "blunder"
    assert ratings[5] == "best"
    assert review.white.name == "You" and review.black.name == "Claude"
    assert review.white.counts["blunder"] == 1
    assert review.white.accuracy < review.black.accuracy
    m = review.moves[4]
    assert (m.ply, m.san, m.best_san) == (5, "Qxg7", "Nc3")
    assert m.best_line.startswith("3. Nc3")
    assert m.fen == "rnbqkbnr/1pppppQp/8/p7/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 0 3"


def test_review_round_trips_through_dict():
    review = build_review(record(["e2e4"]), [flat(55, best="e2e4", second=54), flat(55)], depth=18)
    again = Review.from_dict(review.to_dict())
    assert again == review


async def test_analyse_positions_with_fake_engine_reports_progress():
    seen = []
    evals = await analyse_positions(["e2e4", "e7e5"], FakeEngine(), depth=5, progress=lambda d, t: seen.append((d, t)))
    assert len(evals) == 3
    assert seen[-1] == (3, 3)
    assert evals[0].best_uci is not None
    assert evals[0].second_win_white is not None


async def test_terminal_positions_need_no_engine():
    fools_mate = ["f2f3", "e7e5", "g2g4", "d8h4"]
    evals = await analyse_positions(fools_mate, FakeEngine(), depth=5)
    assert evals[-1].win_white == 0.0
    assert evals[-1].best_uci is None


async def test_real_stockfish_finds_the_blunder(stockfish_path):
    engine = UciEngine("stockfish", stockfish_path, {"Threads": 1, "Hash": 16})
    try:
        review = await review_game(record(BLUNDER_GAME), engine, depth=12)
    finally:
        await engine.close()
    assert review.moves[4].san == "Qxg7"
    assert review.moves[4].rating == "blunder"
    assert review.moves[5].rating in ("best", "great")
