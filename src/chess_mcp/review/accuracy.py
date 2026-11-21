"""Accuracy per move and per player, following Lichess's published method."""

from __future__ import annotations

import math
from statistics import pstdev


def move_accuracy(before: float, after: float) -> float:
    """Both arguments are win % from the mover's point of view."""
    if after >= before:
        return 100.0
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * (before - after)) - 3.166924740191411
    return max(0.0, min(100.0, raw + 1))


def _windows(values: list[float], size: int) -> list[list[float]]:
    sliding = [values] if len(values) <= size else [values[i : i + size] for i in range(len(values) - size + 1)]
    padding = [values[:size]] * max(0, min(size, len(values)) - 2)
    return padding + sliding


def _harmonic(values: list[float]) -> float:
    if any(v <= 0 for v in values):
        return 0.0
    return len(values) / sum(1 / v for v in values)


def game_accuracy(win_whites: list[float], accuracies: list[float]) -> tuple[float | None, float | None]:
    """Volatility-weighted mean averaged with the harmonic mean, per colour.

    `win_whites[i]` is White's win % in position i (0 = start); move i leads
    from position i to i + 1. White moves on even i.
    """
    moves = len(accuracies)
    if moves == 0:
        return (None, None)
    size = max(2, min(8, moves // 10))
    weights = [max(0.5, min(12.0, pstdev(w))) for w in _windows(win_whites, size)]
    result: list[float | None] = []
    for colour in (0, 1):
        pairs = [(accuracies[i], weights[i]) for i in range(moves) if i % 2 == colour]
        if not pairs:
            result.append(None)
            continue
        weighted = sum(a * w for a, w in pairs) / sum(w for _, w in pairs)
        harmonic = _harmonic([a for a, _ in pairs])
        result.append((weighted + harmonic) / 2)
    return (result[0], result[1])
