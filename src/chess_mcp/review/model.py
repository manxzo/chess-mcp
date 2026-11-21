"""The review of one game, as stored on disk and sent to the UI and Claude."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

KEY_RATINGS = {"brilliant", "great", "miss", "mistake", "blunder"}


@dataclass
class MoveReview:
    ply: int
    color: str
    san: str
    uci: str
    fen: str
    rating: str
    loss: float
    accuracy: float
    eval_after: str
    win_white_after: float
    best_uci: str | None
    best_san: str | None
    best_line: str


@dataclass
class PlayerSummary:
    name: str
    color: str
    accuracy: float | None
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class Review:
    game_id: str
    opening: str | None
    result: str
    reason: str | None
    white: PlayerSummary
    black: PlayerSummary
    moves: list[MoveReview]
    eval_series: list[float]
    depth: int
    version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Review:
        return cls(
            game_id=d["game_id"],
            opening=d["opening"],
            result=d["result"],
            reason=d["reason"],
            white=PlayerSummary(**d["white"]),
            black=PlayerSummary(**d["black"]),
            moves=[MoveReview(**m) for m in d["moves"]],
            eval_series=list(d["eval_series"]),
            depth=d["depth"],
            version=d.get("version", 1),
        )
