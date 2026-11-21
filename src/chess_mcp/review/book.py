"""Opening theory from the Lichess chess-openings dataset (CC0)."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import chess

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "openings"
MAX_NAME_PLIES = 40


@dataclass(frozen=True)
class Book:
    positions: frozenset[str]
    names: dict[str, tuple[str, str]]


def position_key(board: chess.Board) -> str:
    return board.epd()


@functools.cache
def load_book() -> Book:
    positions: set[str] = set()
    names: dict[str, tuple[str, str]] = {}
    for path in sorted(DATA_DIR.glob("*.tsv")):
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            eco, name, pgn = line.split("\t")
            board = chess.Board()
            for token in pgn.split():
                if "." in token:
                    continue
                board.push_san(token)
                positions.add(position_key(board))
            names[position_key(board)] = (eco, name)
    return Book(frozenset(positions), names)


def book_plies(moves_uci: list[str]) -> int:
    book = load_book()
    board = chess.Board()
    count = 0
    for uci in moves_uci:
        board.push_uci(uci)
        if position_key(board) not in book.positions:
            break
        count += 1
    return count


def opening_name(moves_uci: list[str]) -> str | None:
    book = load_book()
    board = chess.Board()
    found: tuple[str, str] | None = None
    for uci in moves_uci[:MAX_NAME_PLIES]:
        board.push_uci(uci)
        found = book.names.get(position_key(board), found)
    return f"{found[0]} {found[1]}" if found else None
