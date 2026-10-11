import pytest
from starlette.websockets import WebSocketDisconnect

from tests.server.conftest import receive_until, ws_url


def test_bad_token_is_closed_with_4401(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(ws_url("wrong")) as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_connect_sends_state(client):
    with client.websocket_connect(ws_url()) as ws:
        state = ws.receive_json()
    assert state["type"] == "state"
    assert "e4" in state["dests"]["e2"]
    assert state["claude_connected"] is False


def test_move_is_broadcast_to_every_tab(client):
    with client.websocket_connect(ws_url()) as a, client.websocket_connect(ws_url()) as b:
        a.receive_json()
        b.receive_json()
        a.send_json({"type": "move", "move": "e2e4"})
        sa = receive_until(a, "state")
        sb = receive_until(b, "state")
    assert sa["moves"] == sb["moves"] == [{"san": "e4", "uci": "e2e4"}]


def test_second_tab_moving_out_of_turn_gets_an_error(client):
    with client.websocket_connect(ws_url()) as a, client.websocket_connect(ws_url()) as b:
        a.receive_json()
        b.receive_json()
        a.send_json({"type": "move", "move": "e2e4"})
        receive_until(a, "state")
        receive_until(b, "state")
        b.send_json({"type": "move", "move": "d2d4"})
        err = receive_until(b, "error")
    assert err["code"] == "not_your_turn"


def test_illegal_move_and_bad_json(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "move", "move": "e2e5"})
        assert receive_until(ws, "error")["code"] == "illegal_move"
        ws.send_text("not json")
        assert receive_until(ws, "error")["code"] == "bad_json"
        ws.send_json({"type": "dance"})
        assert receive_until(ws, "error")["code"] == "bad_message"


def test_chat_shows_up_in_state(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "chat", "text": "hello Claude"})
        state = receive_until(ws, "state")
    assert state["chat"][-1]["text"] == "hello Claude"


def test_live_eval_arrives_after_a_move(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "move", "move": "e2e4"})
        for _ in range(10):
            state = receive_until(ws, "state")
            if state["eval"]:
                break
    assert state["eval"]["text"] == "+0.20"


def test_finished_game_is_listed_and_reviewed(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "move", "move": "e2e4"})
        receive_until(ws, "state")
        ws.send_json({"type": "resign"})
        state = receive_until(ws, "state")
        assert state["status"] == "resigned"
        ws.send_json({"type": "list_games"})
        games = receive_until(ws, "games")["games"]
        assert games[0]["game_id"] == state["game_id"]
        ws.send_json({"type": "open_review", "game_id": state["game_id"]})
        progress = receive_until(ws, "review_progress")
        review = receive_until(ws, "review")["review"]
    assert progress["total"] == 2
    assert review["moves"][0]["san"] == "e4"


def test_review_of_unknown_game(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "open_review", "game_id": "20200101-000000-0000"})
        assert receive_until(ws, "error")["code"] == "unknown_game"


def test_index_and_static_are_public(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/index.html").status_code == 200
