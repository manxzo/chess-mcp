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
