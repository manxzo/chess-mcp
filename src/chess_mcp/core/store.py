"""Files on disk: the current game, finished games, reviews and the token."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

_GAME_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.games_dir = self.data_dir / "games"
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self._current = self.data_dir / "current.json"

    # ---- current game ----
    def load_current(self) -> dict | None:
        if not self._current.exists():
            return None
        try:
            data = json.loads(self._current.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return data
        except (OSError, ValueError):
            self.discard_current()
            return None

    def save_current(self, record: dict) -> None:
        self._write_json(self._current, record)

    def discard_current(self) -> None:
        if self._current.exists():
            self._current.replace(self.data_dir / "current.json.bad")

    # ---- finished games ----
    def archive(self, record: dict, pgn: str) -> None:
        game_id = record["game_id"]
        self._write_json(self.games_dir / f"{game_id}.json", record)
        (self.games_dir / f"{game_id}.pgn").write_text(pgn, encoding="utf-8")

    def list_games(self, limit: int = 20) -> list[dict]:
        files = sorted(
            (p for p in self.games_dir.glob("*.json") if _GAME_ID.match(p.stem)),
            key=lambda p: p.stem,
            reverse=True,
        )[:limit]
        out = []
        for path in files:
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append(
                {
                    "game_id": rec["game_id"],
                    "started_at": rec.get("started_at"),
                    "ended_at": rec.get("ended_at"),
                    "human_color": rec.get("human_color"),
                    "result": rec.get("result"),
                    "winner": rec.get("winner"),
                    "reason": rec.get("reason"),
                    "opening": rec.get("opening"),
                    "moves": len(rec.get("moves", [])),
                    "reviewed": (self.games_dir / f"{rec['game_id']}.review.json").exists(),
                }
            )
        return out

    def load_game(self, game_id: str) -> dict | None:
        if not _GAME_ID.match(game_id):
            return None
        path = self.games_dir / f"{game_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- reviews ----
    def load_review(self, game_id: str) -> dict | None:
        if not _GAME_ID.match(game_id):
            return None
        path = self.games_dir / f"{game_id}.review.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save_review(self, game_id: str, data: dict) -> None:
        self._write_json(self.games_dir / f"{game_id}.review.json", data)

    # ---- token ----
    def token(self) -> str:
        path = self.data_dir / "token"
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = secrets.token_urlsafe(24)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        os.chmod(path, 0o600)
        return value

    # ---- helpers ----
    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
