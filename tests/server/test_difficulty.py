"""The Elo difficulty setting: state, WebSocket, API and the MCP tool."""

import httpx
import pytest

from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.mcp_client.api_client import ApiClient
from chess_mcp.mcp_client.server import ChessTools
from chess_mcp.server.app import build_app
from tests.fakes import FakeEngine
from tests.server.conftest import TOKEN, receive_until, ws_url

AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def limited_calls() -> list[int]:
    return []


@pytest.fixture
def engines(limited_calls) -> EngineRegistry:
    def limited(elo: int) -> FakeEngine:
        limited_calls.append(elo)
        return FakeEngine(cp=-30)

    return EngineRegistry.with_engines({"stockfish": FakeEngine()}, limited=limited)


@pytest.fixture
async def api(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=AUTH) as c:
        yield c


def test_state_carries_the_setting_and_the_games_elo(client):
    with client.websocket_connect(ws_url()) as ws:
        state = ws.receive_json()
        assert state["difficulty"] == {"elo": None, "min": 1320, "max": 3190}
        assert state["elo"] is None
        ws.send_json({"type": "set_difficulty", "elo": 1500})
        state = receive_until(ws, "state")
        assert state["difficulty"]["elo"] == 1500
        assert state["elo"] == 1500  # applies to the game in progress too
        ws.send_json({"type": "set_difficulty", "elo": 999})
        assert receive_until(ws, "error")["code"] == "bad_elo"
        ws.send_json({"type": "set_difficulty", "elo": "soon"})
        assert receive_until(ws, "error")["code"] == "bad_elo"


async def test_setting_survives_a_restart(config, engines):
    app = build_app(config, engines=engines)
    app.state.chess.set_difficulty(2200)
    again = build_app(config, engines=engines)
    assert again.state.chess.difficulty == 2200


def test_new_game_takes_an_elo_and_past_games_show_it(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "new_game", "human_color": "white", "elo": 1800})
        state = receive_until(ws, "state")
        assert state["elo"] == 1800 and state["difficulty"]["elo"] == 1800
        ws.send_json({"type": "new_game", "human_color": "black", "elo": None})
        state = receive_until(ws, "state")
        assert state["elo"] is None and state["difficulty"]["elo"] is None
        ws.send_json({"type": "set_difficulty", "elo": 1320})
        receive_until(ws, "state")
        ws.send_json({"type": "resign"})
        receive_until(ws, "state")
        ws.send_json({"type": "list_games"})
        games = receive_until(ws, "games")["games"]
    assert games == [] or games[0]["elo"] == 1320


async def test_suggest_needs_a_target_and_claudes_turn(api, limited_calls):
    r = await api.post("/api/suggest")
    assert r.status_code == 400 and r.json()["error"] == "no_target"
    assert (await api.post("/api/new_game", json={"claude_color": "white"})).status_code == 200
    r = await api.post("/api/suggest")
    assert r.json()["error"] == "no_target"
    app_state = api._transport.app.state.chess
    app_state.set_difficulty(1500)
    r = await api.post("/api/suggest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["elo"] == 1500 and body["move"] == "a3" and body["score"] == "-0.30"
    assert limited_calls == [1500]
    await api.post("/api/move", json={"move": "e4"})
    r = await api.post("/api/suggest")
    assert r.status_code == 409 and r.json()["error"] == "not_your_turn"


async def test_claude_is_told_the_target_and_the_tool_speaks(app):
    app.state.chess.set_difficulty(2600)
    client = ApiClient("http://test", TOKEN, transport=httpx.ASGITransport(app=app))
    tools = ChessTools(client, TOKEN)
    try:
        await tools.new_game("white")
        text = await tools.get_game()
        assert "Target strength: about 2600 Elo" in text
        assert "suggest_move" in text
        assert (await tools.suggest_move()).startswith("At about 2600 Elo the engine plays a3")
    finally:
        await client.aclose()
