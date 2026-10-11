# chess-mcp

Play chess against Claude. Claude plays through MCP tools and may consult
Stockfish whenever it likes; you play in a clean web UI from any device.
After each game you get a review with move ratings (Brilliant … Blunder),
accuracy and an eval graph, and Claude can talk you through it.

## Run locally

```bash
uv sync
uv run chess-mcp server            # prints the link to open, including the access token
```

Then start Claude Code in this folder (it picks up `.mcp.json`) and say
"let's play chess". Claude gives you the web UI link.

Stockfish is found via `STOCKFISH_PATH`, then `PATH`, then `/usr/games/stockfish`.
Extra UCI engines go in `~/.local/share/chess-mcp/engines.toml`:

```toml
[engines.weak]
path = "/home/me/.local/bin/stockfish"
options = { "Skill Level" = 3 }
```

## Use the server on the NUC

```bash
export CHESS_SERVER_URL=http://ts.nuc.chess.lan
export CHESS_TOKEN=...            # from /var/lib/chess-mcp/token in the container
claude                            # in this folder
```

From a machine without this repo, register it once:

```bash
claude mcp add chess --env CHESS_SERVER_URL=http://ts.nuc.chess.lan --env CHESS_TOKEN=... \
  -- uvx --from git+https://github.com/manxzo/chess-mcp chess-mcp mcp
```

## Configuration

| Variable | Default | Used by |
|---|---|---|
| `CHESS_HOST` / `CHESS_PORT` | `127.0.0.1` / `8765` | server |
| `CHESS_DATA_DIR` | `~/.local/share/chess-mcp` | server (and MCP token fallback) |
| `CHESS_TOKEN` | generated into the data dir | both |
| `CHESS_PUBLIC_URL` | `http://HOST:PORT` | server: the link Claude shares |
| `CHESS_REVIEW_DEPTH` / `CHESS_EVAL_DEPTH` | `18` / `14` | server |
| `CHESS_ENGINE_THREADS` | `2` | server |
| `CHESS_SERVER_URL` | `http://127.0.0.1:8765` | MCP |

## Develop

```bash
uv run pytest
```

Design: `docs/superpowers/specs/2026-10-11-chess-mcp-design.md`.
