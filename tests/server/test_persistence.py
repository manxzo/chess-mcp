from starlette.testclient import TestClient

from chess_mcp.config import ServerConfig
from chess_mcp.server.app import build_app
from tests.server.conftest import ws_url


def test_game_survives_a_restart(config, engines):
    with TestClient(build_app(config, engines=engines)) as c:
        with c.websocket_connect(ws_url()) as ws:
            ws.receive_json()
            ws.send_json({"type": "move", "move": "e2e4"})
            ws.receive_json()
    with TestClient(build_app(config, engines=engines)) as c:
        with c.websocket_connect(ws_url()) as ws:
            state = ws.receive_json()
    assert state["moves"][0]["san"] == "e4"


def test_corrupt_save_starts_fresh(config, engines):
    (config.data_dir / "current.json").write_text('{"game_id": "x", "moves": ["e2e5"]}')
    app = build_app(config, engines=engines)
    assert app.state.chess.session.board.move_stack == []
    assert (config.data_dir / "current.json.bad").exists()


def test_generated_token_when_none_configured(tmp_path, engines):
    app = build_app(ServerConfig(data_dir=tmp_path), engines=engines)
    assert app.state.chess.token == (tmp_path / "token").read_text().strip()


def test_no_auth(tmp_path, engines):
    app = build_app(ServerConfig(data_dir=tmp_path, no_auth=True), engines=engines)
    assert app.state.chess.token is None


def test_config_from_env(tmp_path):
    env = {"CHESS_HOST": "0.0.0.0", "CHESS_PORT": "3000", "CHESS_DATA_DIR": str(tmp_path), "CHESS_PUBLIC_URL": "http://ts.nuc.chess.lan/"}
    cfg = ServerConfig.from_env(env=env)
    assert (cfg.host, cfg.port, cfg.data_dir) == ("0.0.0.0", 3000, tmp_path)
    assert cfg.ui_url == "http://ts.nuc.chess.lan"
