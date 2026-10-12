from chess_mcp.config import ServerConfig


def test_password_and_claude_path_come_from_env():
    cfg = ServerConfig.from_env(env={"CHESS_PASSWORD": "hunter2", "CHESS_CLAUDE_PATH": "/opt/claude"})
    assert cfg.password == "hunter2"
    assert cfg.claude_path == "/opt/claude"
    assert ServerConfig.from_env(env={"CHESS_PASSWORD": ""}).password is None


def test_api_url_uses_loopback_for_wildcard_binds():
    assert ServerConfig(host="0.0.0.0", port=3000).api_url == "http://127.0.0.1:3000"
    assert ServerConfig(host="192.168.44.105", port=3000).api_url == "http://192.168.44.105:3000"
    assert ServerConfig(host="::1", port=8765).api_url == "http://[::1]:8765"
