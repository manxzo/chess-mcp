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

Opponents: each saved opponent is a name and a free-text description of their
strength, playing style and personality. Pick one when starting a game, or
create your own. Claude plays as that character and chooses every move itself:
the description decides how strongly it plays and how much it consults
Stockfish, and you can ask in chat for an easier or harder game. Undo takes
back your last move (and the reply to it). Reviews, the eval bar and Claude's
coaching always use the full engine.

Stockfish is found via `STOCKFISH_PATH`, then `PATH`, then `/usr/games/stockfish`.
Extra UCI engines go in `~/.local/share/chess-mcp/engines.toml`:

```toml
[engines.weak]
path = "/home/me/.local/bin/stockfish"
options = { "Skill Level" = 3 }
```

## Use a server on another machine

The game server can run on an always-on machine while Claude Code runs on
your laptop. `deploy/` has a bootstrap script, a systemd unit and an update
script for a fresh Ubuntu host or container; set `CHESS_PUBLIC_URL` in
`deploy/chess.service` to the address you reach it at.

The server has no TLS of its own. Keep it on a private network or VPN, or put
a reverse proxy with HTTPS in front of it.

```bash
export CHESS_SERVER_URL=http://chess.example.com
export CHESS_TOKEN=...            # from /var/lib/chess-mcp/token on the server
claude                            # in this folder
```

From a machine without this repo, register it once:

```bash
claude mcp add chess --env CHESS_SERVER_URL=http://chess.example.com --env CHESS_TOKEN=... \
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
| `CHESS_AGENT_CMD` | unset | server: a shell command that runs any headless agent (e.g. `codex exec "..."`) as the opponent; replaces the hosted Claude and adds a Start opponent button |
| `CHESS_PUBLIC_URL` | `http://HOST:PORT` | server: the link Claude shares |
| `CHESS_REVIEW_DEPTH` / `CHESS_EVAL_DEPTH` | `18` / `14` | server |
| `CHESS_ENGINE_THREADS` | `2` | server |
| `CHESS_SERVER_URL` | `http://127.0.0.1:8765` | MCP |

## Develop

```bash
uv run pytest
```

## License

GPL-3.0-or-later (see `LICENSE`), because it builds on
[python-chess](https://github.com/niklasf/python-chess) and
[chessground](https://github.com/lichess-org/chessground), which are both GPL-3.0.
The bundled opening names come from the Lichess
[chess-openings](https://github.com/lichess-org/chess-openings) dataset (CC0).
Stockfish is not bundled; install it separately.
