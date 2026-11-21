"""Saved opponents, take back, and the Elo-limited hint: state, WebSocket, API and the MCP tools."""

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


def test_create_edit_delete_and_play_an_opponent(client):
    with client.websocket_connect(ws_url()) as ws:
        state = ws.receive_json()
        assert [o["name"] for o in state["opponents"]["list"]][0] == "Pip"
        assert state["opponents"]["selected"] == "pip"

        ws.send_json({"type": "save_opponent", "id": None, "name": " Grump ", "description": "A grumpy 1600 player."})
        made = receive_until(ws, "state")["opponents"]["list"][-1]
        assert made["name"] == "Grump"
        ws.send_json({"type": "save_opponent", "id": made["id"], "name": "Grump", "description": "Now cheerful."})
        assert receive_until(ws, "state")["opponents"]["list"][-1]["description"] == "Now cheerful."
        ws.send_json({"type": "save_opponent", "id": None, "name": "", "description": "x"})
        assert receive_until(ws, "error")["code"] == "bad_opponent"

        ws.send_json({"type": "new_game", "human_color": "white", "opponent_id": made["id"]})
        state = receive_until(ws, "state")
        assert state["opponent"] == {"name": "Grump", "description": "Now cheerful."}
        assert state["opponents"]["selected"] == made["id"]

        # Deleting the opponent leaves the game in progress alone and falls back to another default.
        ws.send_json({"type": "delete_opponent", "id": made["id"]})
        state = receive_until(ws, "state")
        assert state["opponent"]["name"] == "Grump" and state["opponents"]["selected"] == "pip"
        ws.send_json({"type": "new_game", "human_color": "white", "opponent_id": made["id"]})
        assert receive_until(ws, "error")["code"] == "unknown_opponent"

        ws.send_json({"type": "move", "move": "e4"})
        receive_until(ws, "state")
        ws.send_json({"type": "resign"})
        receive_until(ws, "state")
        ws.send_json({"type": "list_games"})
        assert receive_until(ws, "games")["games"][0]["opponent"] == "Grump"


async def test_opponents_survive_a_restart(config, engines):
    app = build_app(config, engines=engines)
    new_id = app.state.chess.save_opponent(None, "Zed", "Plays the London every game.")
    app.state.chess.start_game(True, by="human", opponent_id=new_id)
    again = build_app(config, engines=engines).state.chess
    assert again.opponent_id == new_id and again.opponents[-1]["name"] == "Zed"
    assert again.session.opponent["name"] == "Zed"


async def test_take_back_rewinds_to_the_humans_turn(app, api):
    session = app.state.chess.session  # the human is white
    with pytest.raises(Exception, match="no move to take back"):
        session.take_back()
    session.play("e4", by="human")
    session.take_back()  # Claude has not answered: one ply
    assert session.movetext() == "" and session.side_to_move() == "human"

    session.play("d4", by="human")
    # Claude chose a reply for 1.e4 before the take back; it must not land on 1.d4.
    r = await api.post("/api/move", json={"move": "e5"})
    assert r.status_code == 409 and r.json()["error"] == "position_changed"
    r = await api.post("/api/move", json={"move": "d5"})
    assert r.status_code == 200, r.text
    session.play("c4", by="human")
    await api.post("/api/move", json={"move": "e6"})
    session.take_back()  # Claude has answered: two plies
    assert session.movetext() == "1. d4 d5" and session.side_to_move() == "human"
    assert "takeback" in session.claude_events()
    assert (await api.get("/api/game")).json()["took_back"] is True
    assert "takeback" not in session.claude_events()


def test_take_back_over_the_websocket(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "take_back"})
        assert receive_until(ws, "error")["code"] == "nothing_to_take_back"
        ws.send_json({"type": "move", "move": "e4"})
        assert len(receive_until(ws, "state")["moves"]) == 1
        ws.send_json({"type": "take_back"})
        assert receive_until(ws, "state")["moves"] == []


async def test_suggest_takes_an_elo_and_needs_claudes_turn(api, limited_calls):
    assert (await api.post("/api/new_game", json={"claude_color": "white"})).status_code == 200
    r = await api.post("/api/suggest", json={})
    assert r.status_code == 400 and r.json()["error"] == "bad_elo"
    r = await api.post("/api/suggest", json={"elo": 1500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["elo"] == 1500 and body["move"] == "a3" and body["score"] == "-0.30"
    assert limited_calls == [1500]
    await api.post("/api/move", json={"move": "e4"})
    r = await api.post("/api/suggest", json={"elo": 1500})
    assert r.status_code == 409 and r.json()["error"] == "not_your_turn"


async def test_claude_is_told_its_character_and_the_tool_speaks(app):
    client = ApiClient("http://test", TOKEN, transport=httpx.ASGITransport(app=app))
    tools = ChessTools(client, TOKEN)
    try:
        await tools.new_game("white")
        text = await tools.get_game()
        assert "Your character: Pip. A five-year-old" in text
        assert (await tools.suggest_move(2600)).startswith("At about 2600 Elo the engine plays a3")
    finally:
        await client.aclose()
