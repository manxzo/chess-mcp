"""JSON API used by the MCP client (Claude's side)."""

from __future__ import annotations

import asyncio
import functools
import json
import time
from typing import Awaitable, Callable

import chess
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from chess_mcp.core.game import GameError, color_name, parse_color
from chess_mcp.engines.base import EngineError, Limit
from chess_mcp.review.model import KEY_RATINGS
from chess_mcp.server.auth import token_matches
from chess_mcp.server.state import AppState

STATUS = {
    "not_your_turn": 409,
    "game_in_progress": 409,
    "game_over": 409,
    "no_draw_offer": 409,
    "unknown_game": 404,
    "no_engine": 503,
    "engine_failed": 503,
}

Handler = Callable[[AppState, Request, dict], Awaitable[dict | Response]]


def _error(code: str, message: str, status: int | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status or STATUS.get(code, 400))


def endpoint(fn: Handler):
    @functools.wraps(fn)
    async def wrapper(request: Request) -> Response:
        state: AppState = request.app.state.chess
        if state.token is not None:
            header = request.headers.get("authorization", "")
            if not (header.startswith("Bearer ") and token_matches(header[7:], state.token)):
                return _error("unauthorized", "Missing or wrong token.", 401)
        body: dict = {}
        if request.method == "POST":
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw)
                except ValueError:
                    return _error("bad_json", "Body is not valid JSON.")
                if not isinstance(body, dict):
                    return _error("bad_json", "Body must be a JSON object.")
        try:
            result = await fn(state, request, body)
        except GameError as exc:
            return _error(exc.code, exc.message)
        except EngineError as exc:
            return _error("engine_failed", str(exc))
        return result if isinstance(result, Response) else JSONResponse(result)

    return wrapper


def _number(value, name: str, low: float, high: float, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise GameError("bad_request", f"{name} must be a number.") from None
    return max(low, min(high, number))


@endpoint
async def get_game(state, request, body):
    state.mark_claude_seen()
    return state.claude_view(mark_seen=True)


@endpoint
async def wait(state, request, body):
    timeout = _number(request.query_params.get("timeout"), "timeout", 0, 55, 45)
    deadline = time.monotonic() + timeout
    state.claude_wait_started()
    try:
        while True:
            events = state.session.claude_events()
            if events:
                return {"event": events[0], "events": events, "game": state.claude_view(mark_seen=True)}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"event": "still_waiting", "events": []}
            await state.session.wait_for_change(remaining)
    finally:
        state.claude_wait_finished()


@endpoint
async def move(state, request, body):
    text = body.get("move")
    if not isinstance(text, str) or not text.strip():
        raise GameError("bad_request", 'Send {"move": "e4"}.')
    san = state.session.play(text, by="claude")
    message = body.get("message")
    if isinstance(message, str) and message.strip():
        state.session.add_chat("claude", message)
    state.mark_claude_seen()
    return {"played": san, "game": state.claude_view(mark_seen=True)}


@endpoint
async def chat(state, request, body):
    text = body.get("text")
    if not isinstance(text, str):
        raise GameError("bad_request", 'Send {"text": "..."}.')
    state.session.add_chat("claude", text)
    state.mark_claude_seen()
    return {"ok": True}


@endpoint
async def new_game(state, request, body):
    claude = parse_color(str(body.get("claude_color", "black")))
    state.session.new_game(not claude, by="claude")
    return state.claude_view(mark_seen=True)


@endpoint
async def offer_draw(state, request, body):
    state.session.offer_draw("claude")
    return state.claude_view(mark_seen=True)


@endpoint
async def respond_draw(state, request, body):
    state.session.answer_draw("claude", bool(body.get("accept")))
    return state.claude_view(mark_seen=True)


@endpoint
async def resign(state, request, body):
    state.session.resign("claude")
    return state.claude_view(mark_seen=True)


@endpoint
async def engines(state, request, body):
    return {"engines": state.engines.info()}


@endpoint
async def analyze(state, request, body):
    name = str(body.get("engine") or "stockfish")
    depth = _number(body.get("depth"), "depth", 1, 30, None)
    time_s = _number(body.get("time_s"), "time_s", 0.1, 30, None)
    multipv = int(_number(body.get("multipv"), "multipv", 1, 5, 1))
    if depth is None and time_s is None:
        depth = 18
    board = state.session.board.copy()
    if board.outcome(claim_draw=True) is not None:
        raise GameError("game_over", "The game is over; there is nothing to analyse.")
    engine = state.engines.get(name)
    analysis = await engine.analyse(
        board,
        Limit(depth=int(depth) if depth else None, time_s=time_s),
        multipv=min(multipv, board.legal_moves.count()),
    )
    lines = []
    for line in analysis.lines:
        pv = [chess.Move.from_uci(u) for u in line.pv[:10]]
        lines.append({"move": board.san(pv[0]), "score": line.score.text(board.turn), "pv": board.variation_san(pv)})
    state.mark_claude_seen()
    return {"engine": name, "depth": analysis.depth, "side_to_move": color_name(board.turn), "lines": lines}


@endpoint
async def games(state, request, body):
    limit = int(_number(request.query_params.get("limit"), "limit", 1, 50, 10))
    return {"games": state.store.list_games(limit)}


def _review_payload(review: dict, detail: str) -> dict:
    if detail == "full":
        return review
    moves = [] if detail == "summary" else [m for m in review["moves"] if m["rating"] in KEY_RATINGS]
    return {**review, "moves": moves}


@endpoint
async def review(state, request, body):
    game_id = request.path_params["game_id"]
    if game_id == "current":
        if state.session.status == "active":
            raise GameError("game_in_progress", "The current game is still being played. Reviews are available once it ends.")
        game_id = state.session.game_id
    detail = request.query_params.get("detail", "key_moments")
    if detail not in ("summary", "key_moments", "full"):
        raise GameError("bad_request", "detail must be summary, key_moments or full.")
    wait_s = _number(request.query_params.get("wait"), "wait", 0, 300, 30)
    task = state.reviews.start(game_id)
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=wait_s)
    except TimeoutError:
        done, total = state.reviews.progress(game_id) or (0, 0)
        return JSONResponse({"status": "running", "done": done, "total": total}, status_code=202)
    return {"status": "done", "review": _review_payload(result.to_dict(), detail)}


API_ROUTES = [
    Route("/api/game", get_game, methods=["GET"]),
    Route("/api/wait", wait, methods=["GET"]),
    Route("/api/move", move, methods=["POST"]),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/new_game", new_game, methods=["POST"]),
    Route("/api/draw/offer", offer_draw, methods=["POST"]),
    Route("/api/draw/respond", respond_draw, methods=["POST"]),
    Route("/api/resign", resign, methods=["POST"]),
    Route("/api/engines", engines, methods=["GET"]),
    Route("/api/analyze", analyze, methods=["POST"]),
    Route("/api/games", games, methods=["GET"]),
    Route("/api/review/{game_id}", review, methods=["GET"]),
]
