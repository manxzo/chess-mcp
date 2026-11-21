import pytest

from chess_mcp.engines.base import Score
from chess_mcp.review.accuracy import game_accuracy, move_accuracy
from chess_mcp.review.winprob import for_side, win_pct_white


@pytest.mark.parametrize(
    ("cp", "expected"),
    [(0, 50.0), (100, 59.1026), (-100, 40.8974), (300, 75.1126), (1000, 97.5447), (5000, 97.5447)],
)
def test_win_pct_matches_lichess(cp, expected):
    assert win_pct_white(Score(cp=cp)) == pytest.approx(expected, abs=1e-3)


def test_mate_scores():
    assert win_pct_white(Score(mate=2)) == 100.0
    assert win_pct_white(Score(mate=-1)) == 0.0


def test_for_side():
    assert for_side(70.0, True) == 70.0
    assert for_side(70.0, False) == pytest.approx(30.0)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [(50, 50, 100.0), (50, 60, 100.0), (60, 50, 64.5798), (80, 40, 15.909), (100, 0, 0.0)],
)
def test_move_accuracy(before, after, expected):
    assert move_accuracy(before, after) == pytest.approx(expected, abs=1e-3)


def test_game_accuracy_perfect_game_is_100():
    wins = [50.0] * 11
    accs = [100.0] * 10
    assert game_accuracy(wins, accs) == (100.0, 100.0)


def test_game_accuracy_punishes_one_blunder_for_that_side_only():
    wins = [50, 50, 50, 50, 50, 10, 10, 10, 10]  # white blunders on ply index 4
    accs = [100, 100, 100, 100, move_accuracy(50, 10), 100, 100, 100]
    white, black = game_accuracy([float(w) for w in wins], accs)
    assert white < 80
    assert black == 100.0


def test_game_accuracy_no_moves():
    assert game_accuracy([50.0], []) == (None, None)


def test_game_accuracy_single_move():
    white, black = game_accuracy([50.0, 50.0], [100.0])
    assert white == 100.0
    assert black is None
