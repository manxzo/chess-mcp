"""The stdio MCP server Claude Code runs. Every tool calls the game server."""

from __future__ import annotations

import asyncio
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from chess_mcp.config import McpConfig
from chess_mcp.mcp_client.api_client import ApiClient, ApiError
from chess_mcp.mcp_client.format import format_analysis, format_games, format_review, format_view

INSTRUCTIONS = """\
You are playing chess against the user. They play in a web UI; you play through these tools.

How to play:
1. Call get_game. If the user hasn't opened the web UI yet, give them the link it shows.
2. Call wait_for_turn. It returns when it is your move, the user sends a message, offers a
   draw, or the game ends. If it says still_waiting, call it again straight away.
3. On your move, think about the position yourself. You may call analyze to consult an
   engine whenever you like, but the choice of move is yours. Then call make_move, usually
   with a short, friendly message.
4. Answer the user's messages with send_message, or in make_move's message. Keep it brief.
5. Keep looping until the game ends; don't stop waiting while a game is active unless the
   user asks. After the game, call get_review and talk the user through the key moments.
"""

TOOL_NAMES = [
    "get_game",
    "wait_for_turn",
    "make_move",
    "send_message",
    "analyze",
    "list_engines",
    "get_review",
    "list_games",
    "new_game",
    "offer_draw",
    "respond_to_draw",
    "resign",
]


class ChessTools:
    def __init__(self, client: ApiClient, token: str | None):
        self.client = client
        self.token = token

    def _link(self, view: dict) -> str | None:
        url = view.get("ui_url")
        if not url:
            return None
        return f"{url}/?token={self.token}" if self.token else f"{url}/"

    def _view(self, view: dict) -> str:
        return format_view(view, self._link(view))

    async def _call(self, coro):
        try:
            return await coro
        except ApiError as exc:
            raise ToolError(exc.message) from exc

    async def get_game(self) -> str:
        """Show the current game: board, moves, whose turn it is, new messages from the user, and the web UI link."""
        return self._view(await self._call(self.client.game()))

    async def wait_for_turn(self, timeout_s: int = 45) -> str:
        """Wait until it is your move, the user sends a message or offers a draw, or the game ends.

        Returns 'still_waiting' if nothing happened within timeout_s seconds (max 55); then call it again.
        """
        deadline = time.monotonic() + max(1, min(timeout_s, 55))
        last_error: ApiError | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_error is not None:
                    raise ToolError(last_error.message)
                return "still_waiting: nothing has happened yet. Call wait_for_turn again."
            try:
                result = await self.client.wait(remaining)
                last_error = None
            except ApiError as exc:
                if exc.code != "unreachable":
                    raise ToolError(exc.message) from exc
                last_error = exc
                await asyncio.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
                continue
            if result["event"] == "still_waiting":
                continue
            return f"events: {', '.join(result['events'])}\n\n" + self._view(result["game"])

    async def make_move(self, move: str, message: str | None = None) -> str:
        """Play your move in SAN (e.g. Nf3, O-O, exd5, e8=Q) or UCI (g1f3). Optionally include a short chat message for the user."""
        result = await self._call(self.client.move(move, message))
        return f"You played {result['played']}.\n\n" + self._view(result["game"])

    async def send_message(self, text: str) -> str:
        """Send a chat message to the user; it appears in the web UI."""
        await self._call(self.client.chat(text))
        return "Sent."

    async def analyze(self, engine: str = "stockfish", depth: int | None = None, time_s: float | None = None, multipv: int = 1) -> str:
        """Ask a chess engine about the current position. Returns its top lines with scores from the side to move's point of view.

        depth: search depth (1-30, default 18). time_s: seconds to think instead of a depth. multipv: number of lines (1-5).
        """
        return format_analysis(await self._call(self.client.analyze(engine, depth, time_s, multipv)))

    async def list_engines(self) -> str:
        """List the chess engines the server has and whether each one is available."""
        result = await self._call(self.client.engines())
        return "\n".join(f"{e['name']}: {'available' if e['available'] else 'missing'} ({e['path']})" for e in result["engines"])

    async def get_review(self, game: str = "current", detail: str = "key_moments") -> str:
        """Review a finished game: accuracy, a rating for each move (brilliant ... blunder) and the engine's best lines.

        game: 'current' for the game just finished, or a game id from list_games.
        detail: 'summary', 'key_moments' (brilliant, great, miss, mistake and blunder moves) or 'full'.
        The first review of a game takes a little while; this waits for it.
        """
        while True:
            result = await self._call(self.client.review(game, detail, wait=240))
            if result["status"] == "done":
                return format_review(result["review"], detail)

    async def list_games(self, limit: int = 10) -> str:
        """List recently finished games with their ids, results and openings."""
        return format_games((await self._call(self.client.games(limit)))["games"])

    async def new_game(self, claude_color: str = "black") -> str:
        """Start a new game. claude_color is the colour YOU play: white, black or random. Fails if a game is in progress."""
        return self._view(await self._call(self.client.new_game(claude_color)))

    async def offer_draw(self) -> str:
        """Offer the user a draw."""
        return self._view(await self._call(self.client.offer_draw()))

    async def respond_to_draw(self, accept: bool) -> str:
        """Accept or decline the user's draw offer."""
        return self._view(await self._call(self.client.respond_draw(accept)))

    async def resign(self) -> str:
        """Resign the current game."""
        return self._view(await self._call(self.client.resign()))


def build_mcp_server(tools: ChessTools) -> MCPServer:
    server = MCPServer("chess", instructions=INSTRUCTIONS)
    for name in TOOL_NAMES:
        server.add_tool(getattr(tools, name))
    return server


def run_mcp(config: McpConfig) -> None:
    client = ApiClient(config.server_url, config.token)
    build_mcp_server(ChessTools(client, config.token)).run()
