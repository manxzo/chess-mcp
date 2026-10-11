"""Static exchange evaluation, used to spot sacrifices for the Brilliant rating.

Pins are ignored; this is a heuristic, and Brilliant also requires the engine
to approve the move.
"""

from __future__ import annotations

import chess

VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


def see(board: chess.Board, square: chess.Square, by: chess.Color) -> int:
    """Material `by` wins by starting a capture sequence on `square` (≥ 0)."""
    b = board.copy(stack=False)
    target = b.piece_at(square)
    if target is None or target.color == by:
        return 0
    gains: list[int] = []
    side = by
    value_on_square = VALUES[target.piece_type]
    while True:
        attackers = list(b.attackers(side, square))
        if not attackers:
            break
        origin = min(attackers, key=lambda s: VALUES[b.piece_type_at(s)])
        piece = b.piece_at(origin)
        gains.append(value_on_square)
        value_on_square = VALUES[piece.piece_type]
        b.remove_piece_at(origin)
        b.set_piece_at(square, piece)
        side = not side
    score = 0
    for gain in reversed(gains):
        score = max(0, gain - score)
    return score


def material_given_up(board_before: chess.Board, move: chess.Move) -> int:
    """Pawns the opponent can win after `move`, minus what `move` itself won."""
    mover = board_before.turn
    if board_before.is_en_passant(move):
        captured = 1
    else:
        piece = board_before.piece_at(move.to_square)
        captured = VALUES[piece.piece_type] if piece else 0
    promotion_gain = VALUES[move.promotion] - 1 if move.promotion else 0
    after = board_before.copy(stack=False)
    after.push(move)
    exposed = [
        see(after, square, not mover)
        for square, piece in after.piece_map().items()
        if piece.color == mover and piece.piece_type != chess.KING
    ]
    return max(exposed, default=0) - captured - promotion_gain


def is_sacrifice(board_before: chess.Board, move: chess.Move, threshold: int = 2) -> bool:
    return material_given_up(board_before, move) >= threshold
