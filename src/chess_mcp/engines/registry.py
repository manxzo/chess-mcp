"""Where engines come from: Stockfish discovery plus an optional engines.toml."""

from __future__ import annotations

import os
import shutil


def find_stockfish() -> str | None:
    env = os.environ.get("STOCKFISH_PATH")
    if env and os.access(env, os.X_OK):
        return env
    found = shutil.which("stockfish")
    if found:
        return found
    if os.access("/usr/games/stockfish", os.X_OK):
        return "/usr/games/stockfish"
    return None
