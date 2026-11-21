import pytest

from chess_mcp.engines.registry import find_stockfish


@pytest.fixture
def stockfish_path() -> str:
    path = find_stockfish()
    if path is None:
        pytest.skip("Stockfish binary not installed")
    return path
