# Chess MCP: Design

Date: 2026-10-11
Status: Draft, awaiting review

## Goal

Play chess against Claude. Claude runs in a Claude Code session and plays through
MCP tools. The human plays through a clean web UI, reachable from any device.
Claude's messages appear in the UI and the human can reply.
Claude may consult chess engines (Stockfish first, others later) whenever it
chooses; its moves are its own decisions.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Opponent | Claude in a Claude Code session, via MCP tools |
| Engine role | Claude's choice: engines are advisors Claude may call; Claude picks every move |
| Client | Web UI only, usable from any device (a TUI was considered and dropped) |
| UI scope | Board, move list, Claude chat with reply box, game controls, toggleable eval bar |
| Architecture | Game server lives inside the MCP process (approach 1) |
| Remote play | Server binds 127.0.0.1 by default; set a host (e.g. `0.0.0.0` or a Tailscale IP) to reach it from other devices; non-local binding requires an access token |

## Architecture

One Python process, started by Claude Code as a stdio MCP server, runs two
things on the same asyncio loop:

1. The MCP server (stdio) exposing game tools to Claude.
2. An HTTP + WebSocket server (uvicorn/Starlette) for the web UI.

Both talk to a single in-memory `GameSession`, which persists to disk after
every change.

```
 Claude Code ──stdio──▶ MCP tools ─┐
                                   ├──▶ GameSession ──▶ save file
 Browser ───WebSocket──▶ Hub ──────┘        │
                                            └──▶ Engine registry ──▶ Stockfish
```

### Units

Each unit has one job and a small interface.

**`core/game.py` — GameSession**
- Owns a `chess.Board`, the human's colour, the chat log, game status
  (`active`, `checkmate`, `stalemate`, `draw`, `resigned`, …), and a pending
  draw offer.
- Methods: `new_game(human_color)`, `play(move, by)`, `add_chat(sender, text)`,
  `resign(by)`, `offer_draw(by)`, `answer_draw(accept)`, `snapshot(view)`.
- Validates turn ownership: the human can only move on the human's turn,
  Claude only on Claude's.
- Accepts moves in SAN or UCI.
- Emits change notifications through an `asyncio.Condition` plus a listener
  list. No knowledge of MCP, HTTP or engines.
- Tracks which human messages and moves Claude has not yet seen
  (an "unread for Claude" cursor).

**`core/store.py` — persistence**
- Saves the current game as JSON (FEN history via move list in UCI, human
  colour, chat log, status) to `$XDG_DATA_HOME/chess-mcp/current.json`
  (default `~/.local/share/chess-mcp/current.json`).
- On game end, appends the PGN (with chat as comments) to
  `~/.local/share/chess-mcp/games/<timestamp>.pgn`.
- Loaded on startup, so a restarted session resumes the game.

**`engines/` — engine layer**
- `base.py`: `Engine` protocol with `name`, `analyse(board, limit) -> Analysis`
  (best move, score in centipawns or mate, principal variation, depth) and
  `close()`. `limit` supports time, depth and multipv.
- `uci.py`: `UciEngine` wraps any UCI binary using `chess.engine`'s async API.
  Stockfish is just a configured `UciEngine`.
- `registry.py`: discovers engines and hands them out by name. Stockfish path
  is resolved from `STOCKFISH_PATH`, then `PATH`, then `/usr/games/stockfish`.
  Extra UCI engines can be added via a config file
  (`~/.config/chess-mcp/engines.toml`, name → path + UCI options).
  Engines start lazily on first use.

**`server/hub.py` — UI hub**
- Starlette app with `GET /` (web UI), static files, and `WS /ws`.
- Access token: if `CHESS_MCP_TOKEN` is set, or the host is not a loopback
  address, every request needs the token. When binding non-locally without a
  token configured, one is generated and stored in
  `~/.local/share/chess-mcp/token`. The UI URL Claude reports includes
  `?token=…`; the page keeps it in `localStorage` and sends it on the
  WebSocket handshake. Wrong or missing token → 401 / close code 4401.
- On connect and on every session change, sends a full state snapshot
  (small enough that diffs aren't worth it).
- Accepts client messages: `move`, `chat`, `new_game`, `resign`,
  `offer_draw`, `answer_draw`, `set_eval` (eval on/off is per client and
  local to the client; the server just sends eval when it has it).
- After each move, runs a short background Stockfish evaluation
  (depth ~16) and pushes it in the snapshot as `eval`. Skipped silently if no
  engine is available.

**`mcp/tools.py` — Claude's tools** (FastMCP from the `mcp` SDK)

| Tool | Purpose |
|---|---|
| `get_game()` | Board (FEN + ASCII), side to move, Claude's colour, move list, status, pending draw offer, unread human messages |
| `wait_for_turn(timeout_s=45)` | Long-polls until it is Claude's move, a human message arrives, a draw is offered, or the game ends. Returns what happened plus the `get_game` view. Returns `"still_waiting"` on timeout so Claude can call again |
| `make_move(move, message=None)` | Plays Claude's move (SAN or UCI), optionally with a chat message |
| `send_message(text)` | Posts a chat message to the UIs |
| `analyze(engine="stockfish", depth=None, time_s=None, multipv=1)` | Runs an engine on the current position |
| `list_engines()` | Names and availability of configured engines |
| `new_game(claude_color="black")` | Starts a new game |
| `respond_to_draw(accept)` / `offer_draw()` / `resign()` | Game controls for Claude |

Claude's view never includes the background eval. Engine output reaches Claude
only when Claude calls `analyze`, which keeps its play its own.

The MCP server sets `instructions` describing the play loop:
`get_game` → (`wait_for_turn` until it's your move) → think, optionally
`analyze` → `make_move` with a short comment → repeat. `get_game` includes the UI URL (with token) so Claude can tell the human where to play.

**`web/` — web UI** (static, no build step)
- `index.html`, `app.js`, `style.css`.
- Board: chessground (the Lichess board) loaded from a CDN. Legal move
  destinations come from the server snapshot, so no client-side chess logic.
- Layout: board on the left, a single side panel on the right with
  Claude's chat on top, the move list below it, and a reply box at the bottom.
  Controls (new game, colour, resign, draw, flip, eval toggle) sit in a quiet
  icon row under the board. Thin eval bar beside the board when enabled.
- Neutral palette, one accent colour, light and dark themes following the
  system. Stacks vertically on narrow screens.
- Works by touch on phones: tap-to-move as well as drag, board sized to the
  viewport width.
- Reconnects automatically with backoff.

### CLI

`chess-mcp` entry point runs the MCP server (stdio) plus the UI server. This
is what Claude Code launches.

Config via environment variables: `CHESS_MCP_HOST` (default `127.0.0.1`),
`CHESS_MCP_PORT` (default `8765`), `CHESS_MCP_TOKEN` (optional),
`STOCKFISH_PATH`.

## Data flow: one turn

1. Human plays `e4` in the browser → `{"type":"move","move":"e4"}` over WebSocket.
2. Hub calls `session.play("e4", by="human")`; session validates, saves,
   notifies.
3. Hub broadcasts the new snapshot to all connected browsers; background eval starts.
4. Claude's pending `wait_for_turn` wakes and returns
   `{"event":"your_move", "last_move":"e4", ...}`.
5. Claude optionally calls `analyze`, then `make_move("c5", message="Sicilian it is.")`.
6. Session validates and saves; hub broadcasts; the UI shows the move and the
   message.

## Error handling

- Illegal or out-of-turn moves: session raises a typed error. UIs show an
  inline message; MCP tools return a clear error string listing a few legal
  moves.
- No engine available: `analyze` returns a clear error naming the expected
  path and env var; eval bar shows nothing. The game still works.
- Engine crash: `UciEngine` restarts on next call; one retry, then error.
- Port already in use (e.g. a second Claude session): the UI server logs a
  warning to stderr and MCP tools still work, but `get_game` reports that the
  UI server is not running in this process.
- Corrupt save file: renamed to `current.json.bad`, new game started.
- WebSocket drops: clients reconnect with backoff and receive a fresh snapshot.

## Testing

- `pytest` + `pytest-asyncio`.
- Core: move validation, turn ownership, SAN/UCI parsing, game end detection,
  draw offers, unread-for-Claude cursor, save/load round trip.
- Engines: `UciEngine` against real Stockfish, skipped if the binary is absent.
- Hub: Starlette `TestClient` WebSocket tests for snapshot on connect, move
  broadcast, error replies, and token enforcement.
- MCP tools: called directly as functions; `wait_for_turn` tested waking on a
  human move, a chat message, and timeout.
- Manual check: run Claude Code with the MCP registered, play a few moves in
  the browser on this machine and from a phone on the network.

## Setup work outside the code

- The Stockfish engine binary is not installed (only the Python wrapper).
  Install the official Linux x86-64 AVX2 build to `~/.local/bin/stockfish`.
- Register the server with Claude Code via a project `.mcp.json` running
  `uv run chess-mcp`.
- Dependencies: `mcp`, `chess`, `starlette`, `uvicorn`; dev: `pytest`, `pytest-asyncio`, `httpx`. The unused `stockfish`
  wrapper package is removed in favour of `chess.engine`.

## Out of scope (for now)

Terminal UI, clocks and time controls, multiple concurrent games, user
accounts, HTTPS termination (use Tailscale or a reverse proxy), opening books,
engine-vs-engine play.
