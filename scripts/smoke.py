"""End-to-end check: running game server + real MCP server over stdio + a browser-like client.

Usage: uv run python scripts/smoke.py [server_url] [token]
Defaults: http://127.0.0.1:8765 and the local token file.
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from chess_mcp.config import McpConfig


async def call(client: Client, name: str, args: dict | None = None) -> str:
    result = await client.call_tool(name, args or {})
    text = result.content[0].text
    if result.is_error:
        raise SystemExit(f"{name} failed: {text}")
    return text


async def browser_move(url: str, token: str, move: str) -> dict:
    ws_url = url.replace("http", "ws", 1) + f"/ws?token={token}"
    async with websockets.connect(ws_url) as ws:
        json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "move", "move": move}))
        return json.loads(await ws.recv())


async def main() -> None:
    cfg = McpConfig.from_env()
    url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else cfg.server_url
    token = sys.argv[2] if len(sys.argv) > 2 else cfg.token
    params = StdioServerParameters(
        command="uv",
        args=["run", "--quiet", "chess-mcp", "mcp"],
        env={"CHESS_SERVER_URL": url, "CHESS_TOKEN": token or ""},
    )
    async with Client(params) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        print("tools:", ", ".join(sorted(tools)))
        print(await call(client, "get_game"))
        state = await browser_move(url, token, "e2e4")
        print("browser played e4:", state.get("type"), state.get("code", ""))
        print(await call(client, "wait_for_turn", {"timeout_s": 10}))
        print(await call(client, "analyze", {"depth": 12, "multipv": 2}))
        print(await call(client, "make_move", {"move": "c5", "message": "Smoke test says hi."}))
        print(await call(client, "resign"))
        print(await call(client, "get_review", {"detail": "full"}))
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
