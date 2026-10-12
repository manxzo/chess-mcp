"""Settings from environment variables."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "chess-mcp"


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = field(default_factory=default_data_dir)
    token: str | None = None
    no_auth: bool = False
    public_url: str | None = None
    review_depth: int = 18
    eval_depth: int = 14
    engine_threads: int = 2
    password: str | None = None
    claude_path: str | None = None

    @classmethod
    def from_env(cls, no_auth: bool = False, env: Mapping[str, str] = os.environ) -> ServerConfig:
        return cls(
            host=env.get("CHESS_HOST", "127.0.0.1"),
            port=int(env.get("CHESS_PORT", "8765")),
            data_dir=Path(env["CHESS_DATA_DIR"]) if env.get("CHESS_DATA_DIR") else default_data_dir(),
            token=env.get("CHESS_TOKEN") or None,
            no_auth=no_auth,
            public_url=env.get("CHESS_PUBLIC_URL") or None,
            review_depth=int(env.get("CHESS_REVIEW_DEPTH", "18")),
            eval_depth=int(env.get("CHESS_EVAL_DEPTH", "14")),
            engine_threads=int(env.get("CHESS_ENGINE_THREADS", "2")),
            password=env.get("CHESS_PASSWORD") or None,
            claude_path=env.get("CHESS_CLAUDE_PATH") or None,
        )

    @property
    def ui_url(self) -> str:
        return (self.public_url or f"http://{self.host}:{self.port}").rstrip("/")

    @property
    def api_url(self) -> str:
        """Where a process on this machine reaches the API (the hosted Claude's MCP client)."""
        host = self.host
        if host in ("", "0.0.0.0", "::"):
            host = "127.0.0.1"
        elif ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port}"


@dataclass
class McpConfig:
    server_url: str
    token: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> McpConfig:
        url = (env.get("CHESS_SERVER_URL") or "http://127.0.0.1:8765").rstrip("/")
        token = env.get("CHESS_TOKEN") or None
        if token is None:
            token_file = (Path(env["CHESS_DATA_DIR"]) if env.get("CHESS_DATA_DIR") else default_data_dir()) / "token"
            if token_file.exists():
                token = token_file.read_text(encoding="utf-8").strip() or None
        return cls(url, token)
