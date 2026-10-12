"""HTTP client for the game server's /api."""

from __future__ import annotations

import httpx


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ApiClient:
    def __init__(self, base_url: str, token: str | None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(base_url=self.base_url, headers=headers, transport=transport, timeout=30)

    async def _request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None, timeout: float = 30) -> dict:
        try:
            response = await self._http.request(method, path, json=json, params=params, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise ApiError(
                "timeout",
                f"The chess server at {self.base_url} took too long to answer ({exc.__class__.__name__}). "
                "It may be busy (for example, reviewing a game); try again in a moment.",
            ) from exc
        except httpx.TransportError as exc:
            raise ApiError(
                "unreachable",
                f"Can't reach the chess server at {self.base_url} ({exc.__class__.__name__}). "
                "Check that it is running and that CHESS_SERVER_URL is right.",
            ) from exc
        if response.status_code == 401:
            raise ApiError("unauthorized", "The chess server rejected the token. Check CHESS_TOKEN.")
        try:
            data = response.json()
        except ValueError:
            raise ApiError("bad_response", f"Unexpected response from the chess server (HTTP {response.status_code}).") from None
        if response.status_code >= 400:
            raise ApiError(data.get("error", "error"), data.get("message", "Request failed."))
        return data

    async def game(self) -> dict:
        return await self._request("GET", "/api/game")

    async def wait(self, timeout: float) -> dict:
        return await self._request("GET", "/api/wait", params={"timeout": timeout}, timeout=timeout + 15)

    async def move(self, move: str, message: str | None = None) -> dict:
        return await self._request("POST", "/api/move", json={"move": move, "message": message})

    async def chat(self, text: str) -> dict:
        return await self._request("POST", "/api/chat", json={"text": text})

    async def new_game(self, claude_color: str) -> dict:
        return await self._request("POST", "/api/new_game", json={"claude_color": claude_color})

    async def offer_draw(self) -> dict:
        return await self._request("POST", "/api/draw/offer")

    async def respond_draw(self, accept: bool) -> dict:
        return await self._request("POST", "/api/draw/respond", json={"accept": accept})

    async def resign(self) -> dict:
        return await self._request("POST", "/api/resign")

    async def engines(self) -> dict:
        return await self._request("GET", "/api/engines")

    async def analyze(self, engine: str, depth: int | None, time_s: float | None, multipv: int) -> dict:
        body = {"engine": engine, "depth": depth, "time_s": time_s, "multipv": multipv}
        return await self._request("POST", "/api/analyze", json=body, timeout=60)

    async def suggest(self) -> dict:
        return await self._request("POST", "/api/suggest", timeout=30)

    async def games(self, limit: int) -> dict:
        return await self._request("GET", "/api/games", params={"limit": limit})

    async def review(self, game_id: str, detail: str, wait: float) -> dict:
        params = {"detail": detail, "wait": wait}
        return await self._request("GET", f"/api/review/{game_id}", params=params, timeout=wait + 15)

    async def aclose(self) -> None:
        await self._http.aclose()
