"""Hosted Claude and the password gate, over the WebSocket."""

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.server.conftest import PASSWORD, receive_until, ws_url


def claude_state(ws, pred, limit: int = 30) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == "state" and pred(msg["claude"]):
            return msg["claude"]
    raise AssertionError("no matching claude state")


def test_password_opens_the_websocket_and_wrong_one_does_not(client):
    with client.websocket_connect(ws_url(PASSWORD)) as ws:
        assert ws.receive_json()["type"] == "state"
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(ws_url("open-sesam")) as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_state_describes_hosted_claude(client):
    with client.websocket_connect(ws_url()) as ws:
        c = ws.receive_json()["claude"]
    assert c["available"] is True
    assert c["status"] == "stopped"
    assert c["auth"] == {"logged_in": False, "email": None}
    assert c["model"] == "claude-opus-5-5"
    assert {"id": "claude-sonnet-5-5", "name": "Sonnet 5.5"} in c["models"]


def test_start_needs_sign_in_and_models_are_validated(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "claude_start"})
        assert receive_until(ws, "error")["code"] == "claude_not_signed_in"
        ws.send_json({"type": "claude_model", "model": "gpt-9"})
        assert receive_until(ws, "error")["code"] == "bad_model"
        ws.send_json({"type": "claude_model", "model": "claude-haiku-5-5"})
        assert claude_state(ws, lambda c: c["model"] == "claude-haiku-5-5")


def test_sign_in_then_start_and_stop(client, fake_claude_dir):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "claude_login"})
        c = claude_state(ws, lambda c: c["login"]["url"] is not None)
        assert c["login"]["url"].startswith("https://auth.example.test/")
        ws.send_json({"type": "claude_login_code", "code": "good"})
        claude_state(ws, lambda c: c["auth"]["logged_in"])
        ws.send_json({"type": "claude_start"})
        claude_state(ws, lambda c: c["status"] == "running")
        assert (fake_claude_dir / "messages.log").read_text().startswith("Let's play chess")
        ws.send_json({"type": "claude_stop"})
        claude_state(ws, lambda c: c["status"] == "stopped")
        ws.send_json({"type": "claude_logout"})
        claude_state(ws, lambda c: not c["auth"]["logged_in"])


def test_cancel_sign_in(client):
    with client.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"type": "claude_login_code", "code": "good"})
        assert receive_until(ws, "error")["code"] == "no_login"
        ws.send_json({"type": "claude_login"})
        claude_state(ws, lambda c: c["login"]["url"] is not None)
        ws.send_json({"type": "claude_login_cancel"})
        claude_state(ws, lambda c: c["login"]["busy"] is False)
