import pytest

from chess_mcp.review.classify import MoveFacts, Rating, classify


def facts(**overrides) -> MoveFacts:
    base = dict(
        played_best=False,
        win_best=55.0,
        win_played=55.0,
        win_second=50.0,
        legal_count=30,
        is_book=False,
        is_sacrifice=False,
        prev_rating=None,
    )
    base.update(overrides)
    return MoveFacts(**base)


def test_book_wins_over_everything():
    assert classify(facts(is_book=True, win_played=0.0)) is Rating.BOOK


def test_brilliant_sacrifice():
    f = facts(played_best=True, is_sacrifice=True, win_best=70.0, win_played=70.0, win_second=55.0)
    assert classify(f) is Rating.BRILLIANT


@pytest.mark.parametrize(
    "override",
    [
        {"win_second": 20.0},  # forced: the alternative loses
        {"win_best": 99.0, "win_played": 99.0},  # already completely winning
        {"win_played": 45.0, "win_best": 45.0},  # worse for the mover afterwards
        {"played_best": False, "win_played": 60.0},  # loses 10% — not engine-approved
        {"legal_count": 1},
    ],
)
def test_sacrifices_that_are_not_brilliant(override):
    f = facts(**{**dict(played_best=True, is_sacrifice=True, win_best=70.0, win_played=70.0, win_second=55.0), **override})
    assert classify(f) is not Rating.BRILLIANT


def test_great_only_move():
    f = facts(played_best=True, win_best=52.0, win_played=52.0, win_second=30.0)
    assert classify(f) is Rating.GREAT


def test_not_great_when_alternative_still_wins():
    f = facts(played_best=True, win_best=95.0, win_played=95.0, win_second=75.0)
    assert classify(f) is Rating.BEST


def test_best():
    assert classify(facts(played_best=True)) is Rating.BEST


def test_best_ignores_eval_noise():
    f = facts(played_best=True, win_best=60.0, win_played=52.0, win_second=58.0)
    assert classify(f) is Rating.BEST


@pytest.mark.parametrize(
    ("loss", "rating"),
    [
        (0.0, Rating.EXCELLENT),
        (2.0, Rating.EXCELLENT),
        (4.9, Rating.GOOD),
        (9.0, Rating.INACCURACY),
        (15.0, Rating.MISTAKE),
        (20.5, Rating.BLUNDER),
    ],
)
def test_loss_bands(loss, rating):
    f = facts(win_best=60.0, win_played=60.0 - loss)
    assert classify(f) is rating


def test_miss_after_opponent_blunder():
    f = facts(prev_rating=Rating.BLUNDER, win_best=85.0, win_played=60.0)
    assert classify(f) is Rating.MISS


def test_no_miss_without_a_winning_chance():
    f = facts(prev_rating=Rating.BLUNDER, win_best=55.0, win_played=40.0)
    assert classify(f) is Rating.MISTAKE


def test_no_miss_when_opponent_did_not_err():
    f = facts(prev_rating=Rating.GOOD, win_best=85.0, win_played=60.0)
    assert classify(f) is Rating.BLUNDER
