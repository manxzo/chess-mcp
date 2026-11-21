import asyncio
import json
from pathlib import Path

import chess
import pytest

from chess_mcp.config import ServerConfig
from chess_mcp.core.game import GameError, GameSession
from chess_mcp.core.store import Store
from chess_mcp.server.claude_runner import ClaudeRunner

FAKE = str(Path(__file__).resolve().parent.parent / "fake_claude.py")


async def until(pred, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


@pytest.fixture
def fake_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "fake"
    d.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(d))
    return d


@pytest.fixture
async def runner(tmp_path, fake_dir) -> ClaudeRunner:
    config = ServerConfig(data_dir=tmp_path / "data", token="tok", host="127.0.0.1", port=8765, claude_path=FAKE)
    (tmp_path / "data").mkdir()
    r = ClaudeRunner(config, Store(config.data_dir), "tok", GameSession(), lambda: None)
    yield r
    await r.shutdown()


def messages(fake_dir: Path) -> list[str]:
    log = fake_dir / "messages.log"
    return log.read_text().splitlines() if log.exists() else []


async def test_unavailable_without_binary(tmp_path, fake_dir):
    config = ServerConfig(data_dir=tmp_path, claude_path=str(tmp_path / "missing"))
    r = ClaudeRunner(config, Store(tmp_path), None, GameSession(), lambda: None)
    await r.startup()
    assert r.view()["available"] is False
    with pytest.raises(GameError) as exc:
        await r.start()
    assert exc.value.code == "claude_unavailable"


async def test_startup_reads_auth_status(runner, fake_dir):
    await runner.startup()
    assert runner.view()["auth"] == {"logged_in": False, "email": None}
    (fake_dir / "creds").write_text("ok")
    await runner.refresh_auth()
    assert runner.view()["auth"] == {"logged_in": True, "email": "me@example.test"}
    assert runner.view()["model"] == "claude-opus-5-5"
    assert [m["id"] for m in runner.view()["models"]][:2] == ["claude-fable-5-1", "claude-opus-5-5"]


async def test_login_flow(runner, fake_dir):
    await runner.startup()
    with pytest.raises(GameError) as exc:
        await runner.submit_code("good")
    assert exc.value.code == "no_login"
    await runner.login()
    await until(lambda: runner.login_url is not None)
    assert runner.view()["login"] == {"url": "https://auth.example.test/oauth?state=abc", "busy": True, "verifying": False}
    with pytest.raises(GameError):
        await runner.login()
    await runner.submit_code("good")
    assert runner.view()["login"]["verifying"] is True
    await until(lambda: runner.auth["logged_in"])
    assert runner.view()["login"] == {"url": None, "busy": False, "verifying": False}
    assert runner.error is None


async def test_bad_code_reports_error(runner, fake_dir):
    await runner.login()
    await until(lambda: runner.login_url is not None)
    await runner.submit_code("nope")
    await until(lambda: runner.view()["login"]["busy"] is False)
    assert runner.auth["logged_in"] is False
    assert "Invalid authorization code" in runner.error


async def test_cancel_login(runner, fake_dir):
    await runner.login()
    await until(lambda: runner.login_url is not None)
    await runner.cancel_login()
    assert runner.view()["login"]["busy"] is False
    assert runner.login_url is None


async def test_start_requires_sign_in(runner, fake_dir):
    await runner.startup()
    with pytest.raises(GameError) as exc:
        await runner.start()
    assert exc.value.code == "claude_not_signed_in"


async def test_start_runs_claude_with_the_chess_mcp(runner, fake_dir):
    (fake_dir / "creds").write_text("ok")
    await runner.startup()
    await runner.start()
    await until(lambda: runner.status == "running")
    args = json.loads((fake_dir / "args.json").read_text())
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    assert args[args.index("--allowedTools") + 1] == "mcp__chess"
    assert "--restricted" in args and "--strict-mcp-config" in args
    mcp = json.loads(args[args.index("--mcp-config") + 1])["mcpServers"]["chess"]
    assert mcp["args"] == ["-m", "chess_mcp", "mcp"]
    assert mcp["env"] == {"CHESS_SERVER_URL": "http://127.0.0.1:8765", "CHESS_TOKEN": "tok"}
    assert messages(fake_dir)[0].startswith("Let's play chess")
    await until(lambda: not runner.busy)
    with pytest.raises(GameError) as exc:
        await runner.start()
    assert exc.value.code == "claude_busy"
    await runner.stop()
    assert runner.status == "stopped"
    assert runner.view()["error"] is None


async def test_idle_claude_is_nudged_once_per_change(runner, fake_dir):
    (fake_dir / "creds").write_text("ok")
    await runner.startup()
    session = runner.session
    session.claude_view(mark_seen=True)  # Claude has looked at the current game
    await runner.start()
    await until(lambda: runner.status == "running" and not runner.busy)
    runner.on_session_change()
    assert len(messages(fake_dir)) == 1

    session.new_game(chess.WHITE, by="human")
    runner.on_session_change()
    await until(lambda: len(messages(fake_dir)) == 2)
    assert "new_game" in messages(fake_dir)[1]
    await until(lambda: not runner.busy)
    runner.on_session_change()  # same events, Claude did nothing: no second nudge
    await asyncio.sleep(0.1)
    assert len(messages(fake_dir)) == 2

    session.claude_view(mark_seen=True)  # Claude catches up
    runner.on_session_change()
    session.play("e2e4", by="human")  # now it is Claude's move again
    runner.on_session_change()
    await until(lambda: len(messages(fake_dir)) == 3)
    assert "your_move" in messages(fake_dir)[2]


async def test_set_model_persists_and_restarts(runner, fake_dir):
    (fake_dir / "creds").write_text("ok")
    await runner.startup()
    with pytest.raises(GameError) as exc:
        await runner.set_model("gpt-9")
    assert exc.value.code == "bad_model"
    await runner.start()
    await until(lambda: runner.status == "running")
    await runner.set_model("claude-sonnet-5-5")
    await until(lambda: runner.status == "running")
    args = json.loads((fake_dir / "args.json").read_text())
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
    assert runner.store.load_settings()["claude_model"] == "claude-sonnet-5-5"
    await runner.stop()


async def test_crash_and_failed_turns_show_as_errors(runner, fake_dir):
    (fake_dir / "creds").write_text("ok")
    await runner.startup()
    (fake_dir / "crash").write_text("")
    await runner.start()
    await until(lambda: runner.status == "error")
    assert "boom" in runner.error
    (fake_dir / "crash").unlink()
    (fake_dir / "fail_turn").write_text("")
    await runner.start()
    await until(lambda: runner.status == "running" and not runner.busy)
    assert runner.error == "rate limited"
    await runner.stop()


async def test_logout_stops_claude_and_signs_out(runner, fake_dir):
    (fake_dir / "creds").write_text("ok")
    await runner.startup()
    await runner.start()
    await until(lambda: runner.status == "running")
    await runner.logout()
    assert runner.status == "stopped"
    assert runner.auth["logged_in"] is False
    assert not (fake_dir / "creds").exists()
