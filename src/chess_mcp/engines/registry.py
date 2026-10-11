"""Where engines come from: Stockfish discovery plus an optional engines.toml."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from chess_mcp.engines.base import Engine, EngineError
from chess_mcp.engines.uci import UciEngine


def find_stockfish() -> str | None:
    env = os.environ.get("STOCKFISH_PATH")
    if env and os.access(env, os.X_OK):
        return env
    found = shutil.which("stockfish")
    if found:
        return found
    if os.access("/usr/games/stockfish", os.X_OK):
        return "/usr/games/stockfish"
    return None


@dataclass
class EngineSpec:
    name: str
    path: str
    options: dict = field(default_factory=dict)


class EngineRegistry:
    def __init__(self, specs: list[EngineSpec]):
        self._specs = {s.name: s for s in specs}
        self._engines: dict[str, Engine] = {}
        self._dedicated: dict[str, Engine] = {}

    @classmethod
    def discover(cls, config_file: Path | None, threads: int = 2) -> EngineRegistry:
        specs: dict[str, EngineSpec] = {}
        stockfish = find_stockfish()
        if stockfish:
            specs["stockfish"] = EngineSpec("stockfish", stockfish, {"Threads": threads, "Hash": 128})
        if config_file is not None and Path(config_file).exists():
            data = tomllib.loads(Path(config_file).read_text(encoding="utf-8"))
            for name, entry in data.get("engines", {}).items():
                specs[name] = EngineSpec(name, str(entry["path"]), dict(entry.get("options", {})))
        return cls(list(specs.values()))

    @classmethod
    def with_engines(cls, engines: dict[str, Engine], dedicated: dict[str, Engine] | None = None) -> EngineRegistry:
        registry = cls([EngineSpec(name, "<in-process>", {}) for name in engines])
        registry._engines = dict(engines)
        registry._dedicated = dict(dedicated) if dedicated is not None else dict(engines)
        return registry

    def names(self) -> list[str]:
        return list(self._specs)

    def _available(self, name: str) -> bool:
        if name in self._engines:
            return True
        spec = self._specs.get(name)
        return spec is not None and os.access(spec.path, os.X_OK)

    def has(self, name: str) -> bool:
        return self._available(name)

    def info(self) -> list[dict]:
        return [{"name": s.name, "path": s.path, "available": self._available(s.name)} for s in self._specs.values()]

    def get(self, name: str = "stockfish") -> Engine:
        """The shared instance, used for quick work (live eval, Claude's analyze)."""
        if name not in self._engines:
            self._engines[name] = self._create(name)
        return self._engines[name]

    def dedicated(self, name: str = "stockfish") -> Engine:
        """A second, separate process for long jobs (reviews), so they never block the shared one."""
        if name not in self._dedicated:
            self._dedicated[name] = self._create(name)
        return self._dedicated[name]

    def _create(self, name: str) -> Engine:
        spec = self._specs.get(name)
        if spec is None:
            known = ", ".join(self._specs) or "none"
            raise EngineError(f"Unknown engine {name!r}. Available: {known}. Stockfish is found via STOCKFISH_PATH or PATH.")
        if not os.access(spec.path, os.X_OK):
            raise EngineError(f"{name} not found at {spec.path}. Install it or set STOCKFISH_PATH.")
        return UciEngine(spec.name, spec.path, spec.options)

    async def close_all(self) -> None:
        for engine in {id(e): e for e in [*self._engines.values(), *self._dedicated.values()]}.values():
            await engine.close()
