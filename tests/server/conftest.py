from pathlib import Path

import pytest
from starlette.testclient import TestClient

from chess_mcp.config import ServerConfig
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.server.app import build_app
from tests.fakes import FakeEngine

TOKEN = "test-token"
PASSWORD = "open-sesame"
FAKE_CLAUDE = str(Path(__file__).resolve().parent.parent / "fake_claude.py")


@pytest.fixture
def fake_claude_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "fake-claude"
    d.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(d))
    return d


@pytest.fixture
def config(tmp_path, fake_claude_dir) -> ServerConfig:
    return ServerConfig(data_dir=tmp_path, token=TOKEN, password=PASSWORD, public_url="http://chess.test", claude_path=FAKE_CLAUDE)


@pytest.fixture
def engines() -> EngineRegistry:
    return EngineRegistry.with_engines({"stockfish": FakeEngine()})


@pytest.fixture
def app(config, engines):
    return build_app(config, engines=engines)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def ws_url(token: str = TOKEN) -> str:
    return f"/ws?token={token}"


def receive_until(ws, kind: str, limit: int = 20) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind!r} message")
