# chess-mcp

Play chess against Claude. Claude plays through MCP tools and may consult
Stockfish whenever it likes; you play in a clean web UI from any device.
After each game you get a review with move ratings (Brilliant … Blunder),
accuracy and an eval graph, and Claude can talk you through it.

Claude can run in two places: in a Claude Code session on your own machine
(it connects through the MCP client), or hosted by the game server itself.
In the web UI, the Claude settings dialog lets you sign in with your Claude
account, pick the model, and start or stop Claude; the server runs a headless
Claude Code that plays through the same MCP tools. Hosting needs Claude Code
installed where the server runs (`CHESS_CLAUDE_PATH`, or `claude` on `PATH`).

## Run locally

```bash
uv sync
uv run chess-mcp server            # prints the link to open, including the access token
```

Then either open the link, sign in to Claude in the settings dialog and press
Start, or start Claude Code in this folder (it picks up `.mcp.json`) and say
"let's play chess". Claude gives you the web UI link.

The web UI asks for a password. Set `CHESS_PASSWORD`; without it, the access
token printed at startup is the password.

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
| `CHESS_PASSWORD` | unset (the token is the password) | server: what the web UI asks for |
| `CHESS_CLAUDE_PATH` | `claude` on `PATH`, else `~/.local/bin/claude` | server: Claude Code binary for the hosted Claude |
| `CHESS_PUBLIC_URL` | `http://HOST:PORT` | server: the link Claude shares |
| `CHESS_REVIEW_DEPTH` / `CHESS_EVAL_DEPTH` | `18` / `14` | server |
| `CHESS_ENGINE_THREADS` | `2` | server |
| `CHESS_SERVER_URL` | `http://127.0.0.1:8765` | MCP |

## Develop

```bash
uv run pytest
```

Design: `docs/superpowers/specs/2026-10-11-chess-mcp-design.md` and
`docs/superpowers/specs/2026-10-12-hosted-claude-design.md`.
