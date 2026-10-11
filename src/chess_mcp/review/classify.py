"""Chess.com-style move ratings. Pure: numbers in, rating out.

Win values are the mover's expected score in percent. The order of checks
matters: the first matching rule wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Rating(StrEnum):
    BOOK = "book"
    BRILLIANT = "brilliant"
    GREAT = "great"
    BEST = "best"
    EXCELLENT = "excellent"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    MISS = "miss"
    BLUNDER = "blunder"


RATING_ORDER = list(Rating)

THRESHOLDS: dict[str, float] = {
    "excellent": 2.0,  # max loss
    "good": 5.0,
    "inaccuracy": 10.0,
    "mistake": 20.0,  # above this: blunder
    "brilliant_max_loss": 2.0,
    "brilliant_min_alternative": 30.0,  # the other option must not be losing
    "brilliant_min_after": 50.0,  # the mover must not be worse after the sacrifice
    "already_won": 97.0,  # no brilliant/great moves in completely won positions
    "great_min_gap": 15.0,  # best minus second-best
    "great_max_second": 50.0,  # the second-best move must leave the mover worse off
    "miss_min_chance": 65.0,  # what counts as a winning chance
    "miss_min_loss": 10.0,
}


@dataclass(frozen=True)
class MoveFacts:
    played_best: bool
    win_best: float
    win_played: float
    win_second: float | None
    legal_count: int
    is_book: bool
    is_sacrifice: bool
    prev_rating: Rating | None

    @property
    def loss(self) -> float:
        return 0.0 if self.played_best else max(0.0, self.win_best - self.win_played)


def classify(f: MoveFacts, t: dict[str, float] = THRESHOLDS) -> Rating:
    if f.is_book:
        return Rating.BOOK
    loss = f.loss
    not_already_won = f.win_best < t["already_won"]
    alternative = f.win_second if f.played_best else f.win_best

    if (
        f.is_sacrifice
        and loss <= t["brilliant_max_loss"]
        and f.legal_count > 1
        and alternative is not None
        and alternative >= t["brilliant_min_alternative"]
        and f.win_played >= t["brilliant_min_after"]
        and not_already_won
    ):
        return Rating.BRILLIANT

    if (
        f.played_best
        and f.legal_count > 1
        and f.win_second is not None
        and f.win_best - f.win_second >= t["great_min_gap"]
        and f.win_second < t["great_max_second"]
        and not_already_won
    ):
        return Rating.GREAT

    if f.played_best:
        return Rating.BEST

    if (
        f.prev_rating in (Rating.MISTAKE, Rating.BLUNDER)
        and f.win_best >= t["miss_min_chance"]
        and loss > t["miss_min_loss"]
    ):
        return Rating.MISS

    if loss <= t["excellent"]:
        return Rating.EXCELLENT
    if loss <= t["good"]:
        return Rating.GOOD
    if loss <= t["inaccuracy"]:
        return Rating.INACCURACY
    if loss <= t["mistake"]:
        return Rating.MISTAKE
    return Rating.BLUNDER
