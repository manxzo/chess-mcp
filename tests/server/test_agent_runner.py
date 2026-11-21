"""CHESS_AGENT_CMD: the server runs any agent's command when the game needs the opponent."""

import asyncio
import dataclasses

import httpx

from chess_mcp.server import agent_runner
from chess_mcp.server.app import build_app
from tests.server.conftest import TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def _until(check, seconds: float = 10) -> None:
    for _ in range(int(seconds / 0.05)):
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out")


async def test_the_command_runs_as_the_opponent_and_stops_when_idle(config, engines, tmp_path):
    app = build_app(dataclasses.replace(config, agent_cmd="true"), engines=engines)
    state = app.state.chess
    runner = state.claude
    assert isinstance(runner, agent_runner.AgentCommandRunner) and runner.view()["custom"] is True
    assert runner.env["CHESS_SERVER_URL"] == config.api_url and runner.env["CHESS_TOKEN"] == TOKEN

    runner.command = f"echo run >> {tmp_path}/runs"
    await runner.start()
    await _until(lambda: (tmp_path / "runs").exists())
    # The fake agent never deals with the new game, so after three quick exits the runner gives up.
    await _until(lambda: runner.status == "error")
    assert "keeps exiting" in runner.error
    assert (tmp_path / "runs").read_text().count("run") == agent_runner.MAX_FAILURES

    # Once the opponent has nothing to do, starting does not run the command at all.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=AUTH) as api:
        await api.get("/api/game")
    assert state.session.claude_events() == []
    await runner.start()
    await asyncio.sleep(0.3)
    assert runner.status == "running" and (tmp_path / "runs").read_text().count("run") == agent_runner.MAX_FAILURES
    await runner.stop()
    assert runner.status == "stopped"


async def test_stop_kills_a_running_command(config, engines):
    app = build_app(dataclasses.replace(config, agent_cmd="sleep 60"), engines=engines)
    runner = app.state.chess.claude
    await runner.start()
    await _until(lambda: runner._proc is not None)
    proc = runner._proc
    await runner.stop()
    await _until(lambda: proc.returncode is not None and runner._proc is None)
    assert runner.status == "stopped"
