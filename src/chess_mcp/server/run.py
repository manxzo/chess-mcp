"""Start the game server with uvicorn."""

from __future__ import annotations

import logging
import sys

import uvicorn

from chess_mcp.config import ServerConfig, is_loopback
from chess_mcp.server.app import build_app


def run_server(config: ServerConfig) -> None:
    if config.no_auth and not is_loopback(config.host):
        raise SystemExit("--no-auth is only allowed when CHESS_HOST is a loopback address.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = build_app(config)
    token = app.state.chess.token
    link = f"{config.ui_url}/?token={token}" if token else f"{config.ui_url}/"
    print(f"chess-mcp: open {link}", file=sys.stderr, flush=True)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info", ws="websockets")
