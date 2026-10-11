import asyncio

import httpx
import pytest

from chess_mcp.config import ServerConfig
from chess_mcp.server.app import build_app
from tests.server.conftest import TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
async def api(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=AUTH) as c:
        yield c


async def test_requires_token(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/game")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


async def test_no_auth_mode(tmp_path, engines):
    app = build_app(ServerConfig(data_dir=tmp_path, no_auth=True), engines=engines)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/game")).status_code == 200


async def test_get_game(api):
    view = (await api.get("/api/game")).json()
    assert view["you_play"] == "black"
    assert view["ui_url"] == "http://chess.test"


async def test_wait_reports_new_game_then_times_out(api):
    first = (await api.get("/api/wait", params={"timeout": 1})).json()
    assert first["event"] == "new_game"
    second = (await api.get("/api/wait", params={"timeout": 0.1})).json()
    assert second == {"event": "still_waiting", "events": []}


async def test_wait_wakes_on_a_human_move(api, app):
    await api.get("/api/game")  # mark everything seen

    async def human_moves():
        await asyncio.sleep(0.05)
        app.state.chess.session.play("e4", by="human")

    task = asyncio.create_task(human_moves())
    r = (await api.get("/api/wait", params={"timeout": 5})).json()
    await task
    assert r["event"] == "your_move"
    assert r["game"]["last_move"] == "e4"


async def test_claude_moves_with_a_message(api, app):
    app.state.chess.session.play("e4", by="human")
    r = await api.post("/api/move", json={"move": "c5", "message": "The Sicilian."})
    assert r.status_code == 200
    assert r.json()["played"] == "c5"
    assert app.state.chess.session.chat[-1].text == "The Sicilian."


async def test_move_errors(api, app):
    r = await api.post("/api/move", json={"move": "e5"})
    assert r.status_code == 409
    assert r.json()["error"] == "not_your_turn"
    app.state.chess.session.play("e4", by="human")
    r = await api.post("/api/move", json={"move": "e4"})
    assert r.status_code == 400
    assert r.json()["error"] == "illegal_move"
    r = await api.post("/api/move", content=b"{oops")
    assert r.json()["error"] == "bad_json"


async def test_move_after_human_resigned(api, app):
    app.state.chess.session.play("e4", by="human")
    app.state.chess.session.resign("human")
    r = await api.post("/api/move", json={"move": "e5"})
    assert r.status_code == 409
    assert r.json()["error"] == "game_over"
    w = (await api.get("/api/wait", params={"timeout": 1})).json()
    assert "game_over" in w["events"]
    assert (await api.post("/api/chat", json={"text": "Good game!"})).status_code == 200


async def test_new_game_as_white_makes_it_claudes_move(api, app):
    app.state.chess.session.resign("human")
    view = (await api.post("/api/new_game", json={"claude_color": "white"})).json()
    assert view["your_turn"] is True
    w = (await api.get("/api/wait", params={"timeout": 1})).json()
    assert w["events"] == ["your_move"]


async def test_draw_flow(api, app):
    app.state.chess.session.offer_draw("human")
    r = await api.post("/api/draw/respond", json={"accept": True})
    assert r.json()["status"] == "draw_agreed"


async def test_engines_and_analyze(api, app):
    engines = (await api.get("/api/engines")).json()["engines"]
    assert engines[0]["name"] == "stockfish"
    r = (await api.post("/api/analyze", json={"multipv": 2, "depth": 5})).json()
    assert len(r["lines"]) == 2
    assert r["side_to_move"] == "white"
    assert r["lines"][0]["score"] == "+0.20"


async def test_analyze_unknown_engine(api):
    r = await api.post("/api/analyze", json={"engine": "lc0"})
    assert r.status_code == 503
    assert "Unknown engine" in r.json()["message"]


async def test_review_current_while_active_is_refused(api):
    r = await api.get("/api/review/current")
    assert r.status_code == 409


async def test_review_current_after_the_game(api, app):
    s = app.state.chess.session
    s.play("e4", by="human")
    s.play("e5", by="claude")
    s.resign("human")
    full = (await api.get("/api/review/current", params={"detail": "full", "wait": 10})).json()
    assert full["status"] == "done"
    assert [m["san"] for m in full["review"]["moves"]] == ["e4", "e5"]
    summary = (await api.get("/api/review/current", params={"detail": "summary"})).json()
    assert summary["review"]["moves"] == []
    games = (await api.get("/api/games")).json()["games"]
    assert games[0]["reviewed"] is True


async def test_review_unknown_game(api):
    r = await api.get("/api/review/20200101-000000-0000")
    assert r.status_code == 404
