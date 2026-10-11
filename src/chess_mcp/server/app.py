"""The Starlette application."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from chess_mcp.config import ServerConfig
from chess_mcp.core.store import Store
from chess_mcp.engines.registry import EngineRegistry
from chess_mcp.server.state import AppState
from chess_mcp.server.ws import websocket_endpoint

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PRESENCE_TICK = 10


async def index(request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    state: AppState = app.state.chess

    async def tick() -> None:
        while True:
            await asyncio.sleep(PRESENCE_TICK)
            state.check_presence()

    ticker = asyncio.create_task(tick())
    state.live.schedule(state.session.board)
    try:
        yield
    finally:
        ticker.cancel()
        await state.engines.close_all()


def build_app(config: ServerConfig, engines: EngineRegistry | None = None) -> Starlette:
    from chess_mcp.server.api import API_ROUTES

    store = Store(config.data_dir)
    if engines is None:
        engines = EngineRegistry.discover(config.data_dir / "engines.toml", threads=config.engine_threads)
    state = AppState(config, store, engines)
    routes = [
        Route("/", index),
        *API_ROUTES,
        WebSocketRoute("/ws", websocket_endpoint),
        Mount("/static", StaticFiles(directory=WEB_DIR), name="static"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.chess = state
    return app
