import pytest

from chess_mcp import main


def test_cli_requires_a_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "server" in capsys.readouterr().err


def test_cli_rejects_unknown_subcommand():
    with pytest.raises(SystemExit):
        main(["dance"])


from chess_mcp.config import ServerConfig
from chess_mcp.server import run as run_module


def test_no_auth_refuses_non_loopback(tmp_path):
    with pytest.raises(SystemExit, match="loopback"):
        run_module.run_server(ServerConfig(host="0.0.0.0", data_dir=tmp_path, no_auth=True))


def test_server_subcommand_reads_env(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHESS_PORT", "9999")
    monkeypatch.setattr(run_module, "run_server", lambda cfg: seen.setdefault("cfg", cfg))
    main(["server", "--no-auth"])
    assert seen["cfg"].port == 9999
    assert seen["cfg"].no_auth is True


def test_mcp_subcommand(monkeypatch):
    import chess_mcp.mcp_client.server as mcp_module

    seen = {}
    monkeypatch.setenv("CHESS_SERVER_URL", "http://ts.nuc.chess.lan/")
    monkeypatch.setenv("CHESS_TOKEN", "abc")
    monkeypatch.setattr(mcp_module, "run_mcp", lambda cfg: seen.setdefault("cfg", cfg))
    main(["mcp"])
    assert seen["cfg"].server_url == "http://ts.nuc.chess.lan"
    assert seen["cfg"].token == "abc"
