import asyncio

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from chess_mcp.config import ServerConfig
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.mcp_client.api_client import ApiClient
from chess_mcp.mcp_client.server import TOOL_NAMES, ChessTools, build_mcp_server
from chess_mcp.server.app import build_app
from tests.fakes import FakeEngine

TOKEN = "tok"


@pytest.fixture
def app(tmp_path):
    config = ServerConfig(data_dir=tmp_path, token=TOKEN, public_url="http://chess.test")
    return build_app(config, engines=EngineRegistry.with_engines({"stockfish": FakeEngine()}))


@pytest.fixture
async def tools(app):
    client = ApiClient("http://test", TOKEN, transport=httpx.ASGITransport(app=app))
    yield ChessTools(client, TOKEN)
    await client.aclose()


async def test_get_game_text(tools):
    text = await tools.get_game()
    assert "You play black" in text
    assert "http://chess.test/?token=tok" in text
    assert "Waiting for the human (white) to move" in text


async def test_wait_then_move_with_message(tools, app):
    await tools.get_game()

    async def human():
        await asyncio.sleep(0.05)
        app.state.chess.session.add_chat("human", "good luck!")
        app.state.chess.session.play("e4", by="human")

    task = asyncio.create_task(human())
    text = await tools.wait_for_turn(timeout_s=5)
    await task
    assert "your_move" in text
    assert "good luck!" in text
    assert "Legal moves:" in text
    result = await tools.make_move("c5", message="Let's fight.")
    assert "You played c5" in result
    assert app.state.chess.session.chat[-1].text == "Let's fight."


async def test_wait_times_out_politely(tools):
    await tools.get_game()
    text = await tools.wait_for_turn(timeout_s=1)
    assert text.startswith("still_waiting")


async def test_illegal_move_is_a_tool_error(tools, app):
    app.state.chess.session.play("e4", by="human")
    with pytest.raises(ToolError, match="not a legal move"):
        await tools.make_move("Ke3")


async def test_analyze_and_engines(tools):
    assert "stockfish" in await tools.list_engines()
    text = await tools.analyze(depth=5, multipv=2)
    assert text.count("\n") >= 2
    assert "+0.20" in text


async def test_review_flow(tools, app):
    with pytest.raises(ToolError, match="still being played"):
        await tools.get_review()
    s = app.state.chess.session
    s.play("e4", by="human")
    s.play("e5", by="claude")
    s.resign("human")
    text = await tools.get_review(detail="full")
    assert "accuracy" in text
    assert "1. e4" in text
    assert "Recent games" in await tools.list_games()


async def test_unreachable_server():
    client = ApiClient("http://127.0.0.1:9", TOKEN)
    tools = ChessTools(client, TOKEN)
    with pytest.raises(ToolError, match="CHESS_SERVER_URL"):
        await tools.get_game()
    with pytest.raises(ToolError, match="CHESS_SERVER_URL"):
        await tools.wait_for_turn(timeout_s=1)
    await client.aclose()


async def test_wrong_token(app):
    client = ApiClient("http://test", "nope", transport=httpx.ASGITransport(app=app))
    with pytest.raises(ToolError, match="CHESS_TOKEN"):
        await ChessTools(client, "nope").get_game()
    await client.aclose()


async def test_mcp_server_registers_every_tool(tools):
    server = build_mcp_server(tools)
    names = {t.name for t in await server.list_tools()}
    assert names == set(TOOL_NAMES)
    result = await server.call_tool("get_game", {})
    assert "You play black" in result.content[0].text


async def test_slow_server_is_reported_as_a_timeout_not_unreachable():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    client = ApiClient("http://test", TOKEN, transport=httpx.MockTransport(slow))
    with pytest.raises(ToolError) as exc:
        await ChessTools(client, TOKEN).analyze(depth=18)
    assert "took too long" in str(exc.value)
    assert "Can't reach" not in str(exc.value)
    await client.aclose()
