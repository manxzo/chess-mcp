"""The browser's WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import json

from starlette.websockets import WebSocket, WebSocketDisconnect

from chess_mcp.core.game import GameError, parse_color
from chess_mcp.engines.base import EngineError
from chess_mcp.server.state import AppState


async def websocket_endpoint(ws: WebSocket) -> None:
    state: AppState = ws.app.state.chess
    await ws.accept()
    if not state.accepts(ws.query_params.get("token")):
        await ws.close(code=4401)
        return
    state.sockets.add(ws)
    try:
        await ws.send_json(state.browser_state())
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError
            except ValueError:
                await ws.send_json({"type": "error", "code": "bad_json", "message": "Messages must be JSON objects."})
                continue
            try:
                await handle_message(state, ws, msg)
            except GameError as exc:
                await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
    except WebSocketDisconnect:
        pass
    finally:
        state.sockets.discard(ws)


def _text(msg: dict, key: str) -> str:
    value = msg.get(key)
    if not isinstance(value, str):
        raise GameError("bad_message", f"Missing {key!r}.")
    return value


async def handle_message(state: AppState, ws: WebSocket, msg: dict) -> None:
    session = state.session
    kind = msg.get("type")
    if kind == "move":
        session.play(_text(msg, "move"), by="human")
    elif kind == "chat":
        session.add_chat("human", _text(msg, "text"))
    elif kind == "new_game":
        session.new_game(parse_color(str(msg.get("human_color", "white"))), by="human")
    elif kind == "resign":
        session.resign("human")
    elif kind == "offer_draw":
        session.offer_draw("human")
    elif kind == "answer_draw":
        session.answer_draw("human", bool(msg.get("accept")))
    elif kind == "list_games":
        await ws.send_json({"type": "games", "games": state.store.list_games(50)})
    elif kind == "open_review":
        asyncio.get_running_loop().create_task(send_review(state, ws, _text(msg, "game_id")))
    elif kind == "claude_start":
        await state.claude.start()
    elif kind == "claude_stop":
        await state.claude.stop()
    elif kind == "claude_model":
        await state.claude.set_model(_text(msg, "model"))
    elif kind == "claude_login":
        await state.claude.login()
    elif kind == "claude_login_code":
        await state.claude.submit_code(_text(msg, "code"))
    elif kind == "claude_login_cancel":
        await state.claude.cancel_login()
    elif kind == "claude_logout":
        await state.claude.logout()
    else:
        raise GameError("bad_message", f"Unknown message type {kind!r}.")


async def send_review(state: AppState, ws: WebSocket, game_id: str) -> None:
    """Stream progress, then the review, in order, to one socket."""
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def safe_send(payload: dict) -> None:
        with contextlib.suppress(Exception):
            await ws.send_json(payload)

    def on_progress(gid: str, done: int, total: int) -> None:
        if gid == game_id:
            queue.put_nowait({"type": "review_progress", "game_id": gid, "done": done, "total": total})

    state.reviews.listeners.append(on_progress)
    try:
        future = asyncio.shield(state.reviews.start(game_id))
        while not future.done():
            getter = asyncio.ensure_future(queue.get())
            await asyncio.wait({getter, future}, return_when=asyncio.FIRST_COMPLETED)
            if getter.done():
                await safe_send(getter.result())
            else:
                getter.cancel()
        while not queue.empty():
            await safe_send(queue.get_nowait())
        review = future.result()
        await safe_send({"type": "review", "review": review.to_dict()})
    except GameError as exc:
        await safe_send({"type": "error", "code": exc.code, "message": exc.message})
    except EngineError as exc:
        await safe_send({"type": "error", "code": "engine_failed", "message": str(exc)})
    finally:
        state.reviews.listeners.remove(on_progress)
