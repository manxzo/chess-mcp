"""Engine pass over a finished game, then pure rating and accuracy logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import chess

from chess_mcp.engines.base import Engine, Limit, Score
from chess_mcp.review.accuracy import game_accuracy, move_accuracy
from chess_mcp.review.book import book_plies, opening_name
from chess_mcp.review.classify import RATING_ORDER, MoveFacts, Rating, classify
from chess_mcp.review.model import MoveReview, PlayerSummary, Review
from chess_mcp.review.sacrifice import is_sacrifice
from chess_mcp.review.winprob import for_side, win_pct_white

Progress = Callable[[int, int], None]


@dataclass
class PositionEval:
    win_white: float
    score: Score | None  # None for finished positions
    best_uci: str | None
    pv_uci: list[str]
    second_win_white: float | None
    legal_count: int


def _terminal(board: chess.Board) -> PositionEval:
    if board.is_checkmate():
        win = 0.0 if board.turn == chess.WHITE else 100.0
    else:
        win = 50.0
    return PositionEval(win, None, None, [], None, 0)


async def analyse_positions(moves_uci: list[str], engine: Engine, depth: int, progress: Progress | None = None) -> list[PositionEval]:
    board = chess.Board()
    total = len(moves_uci) + 1
    out: list[PositionEval] = []
    for i in range(total):
        if i > 0:
            board.push_uci(moves_uci[i - 1])
        if board.outcome() is not None:
            out.append(_terminal(board))
        else:
            legal = board.legal_moves.count()
            analysis = await engine.analyse(board, Limit(depth=depth), multipv=min(2, legal))
            top = analysis.lines[0]
            second = analysis.lines[1] if len(analysis.lines) > 1 else None
            out.append(
                PositionEval(
                    win_white=win_pct_white(top.score),
                    score=top.score,
                    best_uci=top.move,
                    pv_uci=list(top.pv),
                    second_win_white=win_pct_white(second.score) if second else None,
                    legal_count=legal,
                )
            )
        if progress:
            progress(i + 1, total)
    return out


def _eval_text(ev: PositionEval, board_after: chess.Board) -> str:
    if ev.score is not None:
        return ev.score.text()
    outcome = board_after.outcome()
    return outcome.result() if outcome else "½-½"


def build_review(record: dict, evals: list[PositionEval], depth: int) -> Review:
    moves = list(record["moves"])
    if len(evals) != len(moves) + 1:
        raise ValueError("need one evaluation per position")
    in_book = book_plies(moves)
    board = chess.Board()
    reviews: list[MoveReview] = []
    accuracies: list[float] = []
    prev_rating: Rating | None = None
    for i, uci in enumerate(moves):
        white = board.turn == chess.WHITE
        before, after = evals[i], evals[i + 1]
        move = chess.Move.from_uci(uci)
        san = board.san(move)
        best_move = chess.Move.from_uci(before.best_uci) if before.best_uci else None
        best_line = board.variation_san([chess.Move.from_uci(u) for u in before.pv_uci[:6]]) if before.pv_uci else ""
        facts = MoveFacts(
            played_best=before.best_uci == uci,
            win_best=for_side(before.win_white, white),
            win_played=for_side(after.win_white, white),
            win_second=for_side(before.second_win_white, white) if before.second_win_white is not None else None,
            legal_count=before.legal_count,
            is_book=i < in_book,
            is_sacrifice=is_sacrifice(board, move),
            prev_rating=prev_rating,
        )
        rating = classify(facts)
        accuracy = 100.0 if (facts.is_book or facts.played_best) else move_accuracy(facts.win_best, facts.win_played)
        best_san = board.san(best_move) if best_move else None
        board.push(move)
        reviews.append(
            MoveReview(
                ply=i + 1,
                color="white" if white else "black",
                san=san,
                uci=uci,
                fen=board.fen(),
                rating=rating.value,
                loss=round(facts.loss, 2),
                accuracy=round(accuracy, 1),
                eval_after=_eval_text(after, board),
                win_white_after=round(after.win_white, 2),
                best_uci=before.best_uci,
                best_san=best_san,
                best_line=best_line,
            )
        )
        accuracies.append(accuracy)
        prev_rating = rating

    win_series = [ev.win_white for ev in evals]
    white_acc, black_acc = game_accuracy(win_series, accuracies)
    human_white = record["human_color"] == "white"

    def summary(color: str, accuracy: float | None) -> PlayerSummary:
        is_human = (color == "white") == human_white
        counts = {r.value: 0 for r in RATING_ORDER}
        for m in reviews:
            if m.color == color:
                counts[m.rating] += 1
        return PlayerSummary(
            name="Human" if is_human else "Claude",
            color=color,
            accuracy=round(accuracy, 1) if accuracy is not None else None,
            counts=counts,
        )

    return Review(
        game_id=record["game_id"],
        opening=opening_name(moves),
        result=record.get("result", "*"),
        reason=record.get("reason"),
        white=summary("white", white_acc),
        black=summary("black", black_acc),
        moves=reviews,
        eval_series=[round(w, 2) for w in win_series],
        depth=depth,
    )


async def review_game(record: dict, engine: Engine, depth: int, progress: Progress | None = None) -> Review:
    evals = await analyse_positions(list(record["moves"]), engine, depth, progress)
    return build_review(record, evals, depth)
