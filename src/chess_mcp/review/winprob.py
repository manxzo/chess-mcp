"""Engine score → expected score (win %), Lichess's formula."""

from __future__ import annotations

import math

from chess_mcp.engines.base import Score


def win_pct_white(score: Score) -> float:
    if score.mate is not None:
        return 100.0 if score.mate > 0 else 0.0
    cp = max(-1000, min(1000, score.cp or 0))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def for_side(win_white: float, white: bool) -> float:
    return win_white if white else 100.0 - win_white
