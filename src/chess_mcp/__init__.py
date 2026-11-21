"""chess-mcp: play chess against Claude."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="chess-mcp", description="Play chess against Claude.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{server,mcp}")
    server = sub.add_parser("server", help="run the game server (web UI + API)")
    server.add_argument("--no-auth", action="store_true", help="disable the token (loopback hosts only)")
    sub.add_parser("mcp", help="run the stdio MCP server for Claude Code")
    args = parser.parse_args(argv)

    if args.command == "server":
        from chess_mcp.config import ServerConfig
        from chess_mcp.server.run import run_server

        run_server(ServerConfig.from_env(no_auth=args.no_auth))
    else:
        from chess_mcp.config import McpConfig
        from chess_mcp.mcp_client.server import run_mcp

        run_mcp(McpConfig.from_env())
