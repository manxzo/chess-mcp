import chess
import pytest

from chess_mcp.engines.base import EngineError, Limit, Score
from chess_mcp.engines.registry import EngineRegistry, EngineSpec
from chess_mcp.engines.uci import UciEngine


def test_score_text():
    assert Score(cp=35).text() == "+0.35"
    assert Score(cp=-120).text() == "-1.20"
    assert Score(cp=35).text(chess.BLACK) == "-0.35"
    assert Score(mate=3).text() == "#3"
    assert Score(mate=3).text(chess.BLACK) == "#-3"


def test_registry_unknown_and_missing(tmp_path):
    reg = EngineRegistry([EngineSpec("ghost", str(tmp_path / "nope"), {})])
    assert reg.has("ghost") is False
    assert reg.info() == [{"name": "ghost", "path": str(tmp_path / "nope"), "available": False}]
    with pytest.raises(EngineError, match="not found"):
        reg.get("ghost")
    with pytest.raises(EngineError, match="Unknown engine"):
        reg.get("lc0")


def test_registry_reads_toml(tmp_path, stockfish_path):
    cfg = tmp_path / "engines.toml"
    cfg.write_text(f'[engines.weak]\npath = "{stockfish_path}"\noptions = {{ "Skill Level" = 1 }}\n')
    reg = EngineRegistry.discover(cfg)
    assert set(reg.names()) >= {"stockfish", "weak"}
    assert reg.has("weak")


async def test_stockfish_analyses_and_finds_mate(stockfish_path):
    engine = UciEngine("stockfish", stockfish_path, {"Threads": 1, "Hash": 16})
    try:
        start = await engine.analyse(chess.Board(), Limit(depth=8), multipv=2)
        assert len(start.lines) == 2
        assert chess.Move.from_uci(start.lines[0].move) in chess.Board().legal_moves
        mate_in_one = chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
        result = await engine.analyse(mate_in_one, Limit(depth=6))
        assert result.lines[0].move == "d1d8"
        assert result.lines[0].score.mate == 1
    finally:
        await engine.close()


async def test_stockfish_recovers_after_being_killed(stockfish_path):
    engine = UciEngine("stockfish", stockfish_path)
    try:
        await engine.analyse(chess.Board(), Limit(depth=4))
        engine._transport.kill()
        again = await engine.analyse(chess.Board(), Limit(depth=4))
        assert again.lines
    finally:
        await engine.close()


async def test_dedicated_engine_is_a_separate_process(stockfish_path):
    reg = EngineRegistry([EngineSpec("stockfish", stockfish_path, {"Threads": 1})])
    shared = reg.get("stockfish")
    dedicated = reg.dedicated("stockfish")
    assert dedicated is not shared
    assert reg.dedicated("stockfish") is dedicated
    await dedicated.analyse(chess.Board(), Limit(depth=4))
    await reg.close_all()
