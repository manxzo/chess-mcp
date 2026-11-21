"""Engine-neutral analysis types. Scores are always from White's point of view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import chess
import chess.engine


class EngineError(Exception):
    pass


@dataclass(frozen=True)
class Score:
    cp: int | None = None
    mate: int | None = None

    def text(self, pov: chess.Color = chess.WHITE) -> str:
        sign = 1 if pov == chess.WHITE else -1
        if self.mate is not None:
            return f"#{self.mate * sign}"
        return f"{(self.cp or 0) * sign / 100:+.2f}"

    @classmethod
    def from_pov(cls, pov: chess.engine.PovScore) -> Score:
        white = pov.white()
        if white.is_mate():
            return cls(mate=white.mate())
        return cls(cp=white.score())


@dataclass(frozen=True)
class Line:
    move: str
    pv: list[str]
    score: Score


@dataclass(frozen=True)
class Analysis:
    depth: int
    lines: list[Line]


@dataclass(frozen=True)
class Limit:
    depth: int | None = None
    time_s: float | None = None


class Engine(Protocol):
    name: str

    async def analyse(self, board: chess.Board, limit: Limit, multipv: int = 1) -> Analysis: ...

    async def close(self) -> None: ...
