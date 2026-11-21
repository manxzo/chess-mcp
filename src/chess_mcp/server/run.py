"""Start the game server with uvicorn."""

from __future__ import annotations

import copy
import logging
import re
import sys

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from chess_mcp.config import ServerConfig, is_loopback
from chess_mcp.server.app import build_app

_TOKEN = re.compile(r"token=[^&\s\"']+")


class RedactTokenFilter(logging.Filter):
    """Keeps access tokens out of logs (uvicorn logs request paths with their query string)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "token=" in message:
            record.msg = _TOKEN.sub("token=<redacted>", message)
            record.args = ()
        return True


def build_log_config() -> dict:
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["redact_token"] = {"()": RedactTokenFilter}
    for handler in config["handlers"].values():
        handler.setdefault("filters", []).append("redact_token")
    return config


def startup_notice(ui_url: str, token: str | None, token_path: str, tty: bool) -> str:
    if token is None:
        return f"chess-mcp: open {ui_url}/ (no token: --no-auth)"
    if tty:
        return f"chess-mcp: open {ui_url}/?token={token}"
    return f"chess-mcp: serving {ui_url}/ (access token in {token_path})"


def run_server(config: ServerConfig) -> None:
    if config.no_auth and not is_loopback(config.host):
        raise SystemExit("--no-auth is only allowed when CHESS_HOST is a loopback address.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactTokenFilter())
    app = build_app(config)
    token_path = str(config.data_dir / "token") if config.token is None else "CHESS_TOKEN"
    print(startup_notice(config.ui_url, app.state.chess.token, token_path, sys.stderr.isatty()), file=sys.stderr, flush=True)
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
        log_config=build_log_config(),
        access_log=False,
        ws="websockets-sansio",
    )
