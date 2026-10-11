# Chess MCP: Design

Date: 2026-10-11
Status: Draft, awaiting review

## Goal

Play chess against Claude. Claude runs in a Claude Code session and plays through
MCP tools. The human plays through a clean web UI, hosted on the homelab NUC
and reachable from any device over Tailscale.
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
| Game review | After each game: Stockfish analysis, eval graph, chess.com-style move ratings, accuracy per player |
| Review timing | After the game only; no ratings or review during play |
| Claude coaching | Claude can read the review and talk through key moments |
| Rating rules | Claude's call; thresholds below, kept in one tunable table |
| Architecture | Standalone game server, always running in a container on the NUC. The MCP server is a thin HTTP client that Claude Code runs on any machine (supersedes the earlier "server inside the MCP process" choice) |
| Remote access | Homelab convention: `http://nuc.chess.lan` on the LAN, `http://ts.nuc.chess.lan` over Tailscale, via Caddy on the NUC host. Every request needs an access token |

## Architecture

Two processes from one Python package:

1. **Game server** (`chess-mcp server`): a long-running uvicorn/Starlette app in
   an LXC container on the NUC. It owns the single `GameSession`, the engines,
   the review, and persistence. It serves the web UI, a WebSocket for
   browsers, and a small JSON API for the MCP client.
2. **MCP server** (`chess-mcp mcp`): a stdio FastMCP server that Claude Code
   launches on whatever machine it runs on. It holds no game state; every tool
   is an HTTP call to the game server.

```
 Claude Code ──stdio──▶ MCP client ──HTTP /api──┐        (NUC container)
                                                ├──▶ GameSession ──▶ save files
 Browser ──────────── WebSocket /ws ────────────┤        │
              (both through Caddy on the NUC)   │        ├──▶ Engine registry ──▶ Stockfish
                                                └────────┴──▶ Review
```

The web UI works with no Claude session open: you can browse and review past
games any time. You can only play while Claude is connected and waiting; the
UI shows whether Claude is connected (a `wait_for_turn` call active in the last
60 seconds).

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
  colour, chat log, status) to `<data dir>/current.json`.
- On game end, appends the PGN (with chat as comments) to
  `<data dir>/games/<timestamp>.pgn`.
- Loaded on startup, so a restarted server resumes the game.

**`engines/` — engine layer**
- `base.py`: `Engine` protocol with `name`, `analyse(board, limit) -> Analysis`
  (best move, score in centipawns or mate, principal variation, depth) and
  `close()`. `limit` supports time, depth and multipv.
- `uci.py`: `UciEngine` wraps any UCI binary using `chess.engine`'s async API.
  Stockfish is just a configured `UciEngine`.
- `registry.py`: discovers engines and hands them out by name. Stockfish path
  is resolved from `STOCKFISH_PATH`, then `PATH`, then `/usr/games/stockfish`.
  Extra UCI engines can be added via a config file
  (`<data dir>/engines.toml`, name → path + UCI options).
  Engines start lazily on first use.

**`review/` — game review**

Runs only on finished games (or saved past games). One engine pass per
position, then pure classification logic with no engine calls, so the rules
are unit-testable on fixed numbers.

- `analyzer.py`: for every position in the game, runs Stockfish with
  `multipv=2` at depth 18 (configurable). This gives, per ply: the best move,
  its eval, the second-best move's eval, and (from the next position) the eval
  after the move actually played. Runs as a background job; progress is pushed
  to the UI. Results are cached next to the saved game as
  `<game>.review.json`, so a review is computed once.
- `book.py`: opening detection from the Lichess `chess-openings` dataset
  (CC0, vendored as `data/openings/*.tsv`). A move is **Book** if every move so
  far, including this one, reaches a position in the dataset. Also yields the
  opening name for the review header.
- `classify.py`: rates each move. All thresholds live in one table so they are
  easy to tune.
- `accuracy.py`: per-move and per-player accuracy.

**Win probability.** Evals are converted to the mover's expected score
using Lichess's formula, `win% = 50 + 50 · (2 / (1 + e^(−0.00368208·cp)) − 1)`,
with mate scores mapped to 0 or 100. A move's **loss** is
`win%(best move) − win%(played move)`, from the mover's point of view.

**Classification rules**, checked in this order; the first match wins.

| Rating | Symbol | Rule |
|---|---|---|
| Book | 📖 | Move is still inside known opening theory (see `book.py`) |
| Brilliant | !! | Played move is the engine's best or within 2% of it; it sacrifices material (the moved piece, or a piece it leaves undefended, can be won with a static exchange loss of at least 2 pawns' worth); the mover had a reasonable alternative (second-best move not losing, i.e. win% ≥ 30); the position after the move is not worse for the mover (win% ≥ 50); and the mover wasn't already completely winning (best win% < 97) |
| Great | ! | Played move is the engine's best; the second-best move is at least 15% worse; there was more than one legal move; and the mover wasn't already completely winning (best win% < 97) |
| Best | ★ | Played move is the engine's first choice |
| Miss | ✕ | The opponent's previous move was rated Mistake or Blunder; the mover now had a winning chance (best win% ≥ 65); and the played move loses more than 10%, handing that chance back |
| Excellent | 👍 | Loss ≤ 2% |
| Good | ✓ | Loss ≤ 5% |
| Inaccuracy | ?! | Loss ≤ 10% |
| Mistake | ? | Loss ≤ 20% |
| Blunder | ?? | Loss > 20% |

The symbols are placeholders for small coloured badges in the UI, using the
familiar colour per rating (teal brilliant, blue great, green best/excellent/
good, brown book, yellow inaccuracy, orange mistake, red miss/blunder).

**Accuracy.** Per move, Lichess's formula:
`accuracy = 103.1668 · e^(−0.04354 · (win%before − win%after)) − 3.1669`,
clamped to 0–100, with win% from the mover's side. Per player, Lichess's
method: the volatility-weighted mean of move accuracies averaged with their
harmonic mean. Book moves count as 100.

**Review output** (`Review` dataclass, also the JSON cached to disk):
opening name, per-player accuracy and counts per rating, and per ply: SAN,
rating, loss, eval after the move, the engine's best move and best line (first
6 moves), and the eval series for the graph.

**`server/app.py` — game server**
- Starlette app with `GET /` (web UI), static files, `WS /ws`, and `/api/*`.
- Access token, always on. Read from `CHESS_TOKEN`; if unset, generated on
  first start and stored in `<data dir>/token`. API calls send
  `Authorization: Bearer <token>`. The browser opens the UI once as
  `/?token=…`; the page stores it in `localStorage`, strips it from the
  address bar, and sends it on the WebSocket handshake. Wrong or missing
  token → 401 / close code 4401. `--no-auth` exists for local development
  only and refuses to start unless bound to a loopback address.
- Caddy sits in front, so the server binds the container's address and trusts
  nothing about the client IP.
- On connect and on every session change, sends a full state snapshot
  (small enough that diffs aren't worth it).
- Accepts client messages: `move`, `chat`, `new_game`, `resign`,
  `offer_draw`, `answer_draw`, `list_games`, and `open_review` (game id).
  The eval bar toggle is purely client-side; the server always sends the
  eval when it has one.
- Review requests start the analysis job if needed and stream
  `review_progress` then `review` messages to the requesting client.

**`server/api.py` — JSON API for the MCP client**

| Method and path | Purpose |
|---|---|
| `GET /api/game` | Claude's view of the game (no background eval) |
| `GET /api/wait?timeout=45` | Long-poll for Claude's next event; also marks Claude as connected |
| `POST /api/move` | `{move, message?}` |
| `POST /api/chat` | `{text}` |
| `POST /api/new_game` | `{claude_color}` |
| `POST /api/draw/offer`, `POST /api/draw/respond`, `POST /api/resign` | Game controls |
| `GET /api/engines`, `POST /api/analyze` | Engine list and analysis of the current position |
| `GET /api/games`, `GET /api/review/{game_id}?detail=&wait=` | Past games; review, starting it if needed and waiting up to `wait` seconds |

Errors return `{"error": code, "message": …}` with a 4xx status.
- After each move, runs a short background Stockfish evaluation
  (depth ~16) and pushes it in the snapshot as `eval`. Skipped silently if no
  engine is available.

**`mcp/tools.py` — Claude's tools** (FastMCP from the `mcp` SDK, calling the
API with `httpx`; configured by `CHESS_SERVER_URL` and `CHESS_TOKEN`)

| Tool | Purpose |
|---|---|
| `get_game()` | Board (FEN + ASCII), side to move, Claude's colour, move list, status, pending draw offer, unread human messages |
| `wait_for_turn(timeout_s=45)` | Long-polls until it is Claude's move, a human message arrives, a draw is offered, or the game ends. Returns what happened plus the `get_game` view. Returns `"still_waiting"` on timeout so Claude can call again |
| `make_move(move, message=None)` | Plays Claude's move (SAN or UCI), optionally with a chat message |
| `send_message(text)` | Posts a chat message to the web UI |
| `analyze(engine="stockfish", depth=None, time_s=None, multipv=1)` | Runs an engine on the current position |
| `list_engines()` | Names and availability of configured engines |
| `get_review(game="current", detail="key_moments")` | The finished game's review. `key_moments` returns the summary plus only Brilliant, Great, Miss, Mistake and Blunder moves with the best line at each; `full` returns every move. Starts the analysis if not done yet and waits for it. Errors while the game is still in progress |
| `list_games(limit=10)` | Recent finished games with date, result, opening and colours |
| `new_game(claude_color="black")` | Starts a new game |
| `respond_to_draw(accept)` / `offer_draw()` / `resign()` | Game controls for Claude |

Claude's view never includes the background eval. Engine output reaches Claude
only when Claude calls `analyze`, which keeps its play its own.

The MCP server sets `instructions` describing the play loop:
`get_game` → (`wait_for_turn` until it's your move) → think, optionally
`analyze` → `make_move` with a short comment → repeat. `get_game` includes the UI URL so Claude can tell the human where to play.

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
- **Review mode.** When a game ends, a "Review" button appears; past games
  are reachable from a small "Games" list in the control row. Review mode
  keeps the same layout and swaps the side panel contents:
  - Header with opening name and each player's accuracy.
  - A compact summary of counts per rating for both players.
  - An eval graph (thin area chart, one point per ply) above the move list.
    Clicking a point jumps to that move.
  - The move list with a rating badge beside every move.
  - Selecting a move shows that position on the board, an arrow for the move
    played and, when different, a green arrow for the engine's best move,
    plus the best line in a single line of text under the board.
  - Arrow keys and swipe step through moves.
  - Chat stays available, so Claude's coaching appears alongside.
  - A progress bar shows while the analysis runs.
- Works by touch on phones: tap-to-move as well as drag, board sized to the
  viewport width.
- Reconnects automatically with backoff.

### CLI

- `chess-mcp server` — run the game server. Config: `CHESS_HOST` (default
  `127.0.0.1`), `CHESS_PORT` (default `8765`), `CHESS_TOKEN`,
  `CHESS_DATA_DIR` (default `~/.local/share/chess-mcp`), `CHESS_PUBLIC_URL`
  (the URL reported to Claude, e.g. `http://ts.nuc.chess.lan`),
  `STOCKFISH_PATH`.
- `chess-mcp mcp` — run the stdio MCP server. Config: `CHESS_SERVER_URL`,
  `CHESS_TOKEN`.

For local development both run on the laptop: `chess-mcp server` on
localhost, and `.mcp.json` pointing at it.

## Data flow: one turn

1. Human plays `e4` in the browser → `{"type":"move","move":"e4"}` over WebSocket.
2. Server calls `session.play("e4", by="human")`; session validates, saves,
   notifies.
3. Server broadcasts the new snapshot to all connected browsers; background eval starts.
4. Claude's pending `wait_for_turn` (an open `GET /api/wait`) wakes and returns
   `{"event":"your_move", "last_move":"e4", ...}`.
5. Claude optionally calls `analyze`, then `make_move("c5", message="Sicilian it is.")`.
6. The MCP client posts to `/api/move`; session validates and saves; server broadcasts; the UI shows the move and the
   message.

## Error handling

- Illegal or out-of-turn moves: session raises a typed error. The UI shows an
  inline message; MCP tools return a clear error string listing a few legal
  moves.
- No engine available: `analyze` returns a clear error naming the expected
  path and env var; eval bar shows nothing. The game still works.
- Engine crash: `UciEngine` restarts on next call; one retry, then error.
- Game server unreachable: every MCP tool returns a clear error naming
  `CHESS_SERVER_URL`. `wait_for_turn` retries quietly for up to its timeout
  first, so a server restart mid-game is invisible to Claude.
- Two Claude sessions connected: both may wait, but only the first
  `make_move` for a turn succeeds; the second gets "not your turn".
- Server restart: the game reloads from disk; browsers and the MCP client
  reconnect.
- Corrupt save file: renamed to `current.json.bad`, new game started.
- WebSocket drops: clients reconnect with backoff and receive a fresh snapshot.

## Testing

- `pytest` + `pytest-asyncio`.
- Core: move validation, turn ownership, SAN/UCI parsing, game end detection,
  draw offers, unread-for-Claude cursor, save/load round trip.
- Engines: `UciEngine` against real Stockfish, skipped if the binary is absent.
- Server: Starlette `TestClient` tests for the WebSocket (snapshot on
  connect, move broadcast, error replies) and the API (each endpoint, the
  long-poll waking and timing out), plus token enforcement on both.
- Review: `classify.py` tested on hand-built eval tables for every rating,
  including edge cases (mate scores, only-move positions, sacrifices that
  fail). `accuracy.py` tested against known Lichess values. `book.py` tested on
  a mainline opening and a sideline that leaves theory. One end-to-end test
  reviews a short known game with real Stockfish (skipped without the binary)
  and checks that an obvious blunder is rated Blunder.
- MCP tools: called directly against an in-process game server (`httpx`
  ASGI transport), so tool → API → session is tested end to end.
- Manual check: play a game against Claude locally, then again after
  deployment from a phone over Tailscale, and open the review.

## Setup and deployment

**Local development.** The Stockfish binary is not installed (only the
Python wrapper). Install the official Linux x86-64 AVX2 build to
`~/.local/bin/stockfish`. Dependencies: `mcp`, `chess`, `starlette`,
`uvicorn`, `httpx`; dev: `pytest`, `pytest-asyncio`. The unused `stockfish`
wrapper package is removed in favour of `chess.engine`.

**NUC container**, done after the app works locally and following
`~/homelab` conventions:
- New entry in `~/homelab/services.yaml`: guest `chess`, node `nuc`, type
  `ct`, the next free vmid and static IP on the NUC, port `8765`, name
  `nuc.chess.lan` (and so `ts.nuc.chess.lan`), firewall group `site`
  (app port from the hosts, ssh from LAN+tailnet). Guest files under
  `~/homelab/guests/chess/` copied from `guests/_template/`.
- Created from the shared Ubuntu 26.04 template; unprivileged; 2 cores,
  1 GB RAM, 8 GB disk. Stockfish runs here, so analysis speed depends on
  these cores.
- Inside: `uv`, Stockfish (official AVX2 binary), the app cloned from
  GitHub (a read-only deploy key if the repo is private), and a systemd unit running `chess-mcp server` as an unprivileged
  `chess` user with `CHESS_HOST` set to the container IP and
  `CHESS_PUBLIC_URL=http://ts.nuc.chess.lan`. Data and the token live in
  `/var/lib/chess-mcp`, which the nightly container backups already cover.
- `lab sync` publishes DNS and the Caddy route. WebSockets pass through
  Caddy unchanged.
- Updates: `git pull` and restart the service (a small script in the repo).

**Claude Code** on any machine: a project `.mcp.json` runs
`uv run chess-mcp mcp` with `CHESS_SERVER_URL=http://ts.nuc.chess.lan` and the
token read from the environment, so the token is never committed.

## Out of scope (for now)

Live move ratings during play, a terminal UI, clocks and time controls,
multiple concurrent games, user accounts, HTTPS (traffic stays on the LAN and
tailnet), engine opening books for play, engine-vs-engine games, and exposing
the UI to the public internet.
