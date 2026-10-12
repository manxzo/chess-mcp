# Hosted Claude: start, sign in and pick the model from the web UI

Date: 2026-10-12
Status: Implemented alongside this spec (autonomous session; assumptions listed below)

## Goal

Play from any device without a Claude Code session open on a laptop. The game
server hosts Claude itself: from the web UI you sign in to Claude, choose the
model, and start or stop Claude. The existing path (Claude Code on a laptop
connecting through the MCP client) keeps working unchanged.

## Assumptions made without the user

| Topic | Assumption |
|---|---|
| Where Claude runs | In the game server's container, as a headless Claude Code process (`claude -p`) spawned by the server. |
| Sign-in method | Claude subscription (claude.ai OAuth), the CLI's default. The CLI prints a URL and waits for a pasted code; the server brokers both through the UI. |
| Credentials location | A dedicated `CLAUDE_CONFIG_DIR` under the data dir (`<data dir>/claude`), so the server's sign-in state is exactly what the UI shows and never mixes with a developer's own login. |
| Model list | Fixed: Fable 5.1, Opus 5.5 (default), Sonnet 5.5, Haiku 5.5, by their full model IDs. |
| Claude's lifetime | One long-running process while "started". It ends its turn when a game is reviewed; the server wakes it with a message when the game changes, so it does not poll between games. |
| Crashes | Shown as an error in the UI; the user presses Start again. No automatic restart. |

## How the pieces fit

```
Browser ── WebSocket /ws ──▶ AppState ──▶ ClaudeRunner ──spawns──▶ claude -p (stream-json)
                                  ▲                                   │ stdio MCP
                                  └──── HTTP /api ◀── python -m chess_mcp mcp ◀┘
```

The hosted Claude plays exactly like a laptop Claude: the CLI launches the
package's MCP client, which talks to the same `/api` with the server's token.
Presence (`claude_connected`) is therefore unchanged.

## Units

### `server/claude_runner.py` — `ClaudeRunner`

Owns the Claude Code binary, sign-in, and the playing process. Interface:

- `startup()` / `shutdown()`: refresh auth status on boot; terminate processes on exit.
- `view() -> dict`: what the UI sees (below).
- `login() -> None`: spawn `claude auth login`, parse the sign-in URL from stdout, keep the process waiting for the code. `submit_code(code)`, `cancel_login()`.
- `logout()`: stop Claude if running, run `claude auth logout`, refresh.
- `set_model(id)`: validate against the list, persist, restart Claude if running.
- `start()` / `stop()`.
- `on_session_change()`: called by `AppState` whenever the game changes; nudges an idle Claude.

Process details:

- Binary: `CHESS_CLAUDE_PATH`, else `claude` on `PATH`, else `~/.local/bin/claude`. Missing binary → `available: false`; the UI falls back to the old "use Claude Code" message.
- Environment: `CLAUDE_CONFIG_DIR=<data dir>/claude`; cwd `<data dir>/claude/work` (an empty directory so no project `CLAUDE.md` is picked up).
- Play command:
  `claude -p --input-format stream-json --output-format stream-json --verbose --model <id> --permission-mode dontAsk --allowedTools mcp__chess --strict-mcp-config --mcp-config <json> --disable-slash-commands --restricted --append-system-prompt <text>`.
  The MCP config runs `python -m chess_mcp mcp` (same interpreter as the server) with `CHESS_SERVER_URL=http://<host>:<port>` (loopback if the server binds all interfaces) and `CHESS_TOKEN`.
- Appended system prompt: play through the chess tools only; after the game ends and the review has been discussed, stop and end the turn; the server sends a message when something new happens.
- Stream handling: `system/init` → status `running`; `result` → idle (an `is_error` result is kept as the last error); process exit → `stopped` when requested, else `error` with the stderr tail.
- Nudging: when idle and `session.claude_events()` is non-empty and differs from the events of the last nudge, send one user message naming the events. Comparing against the last nudge prevents a loop if Claude ends its turn without acting. The first message after start is "Let's play chess".
- Stop: SIGTERM, 5 s grace, SIGKILL.
- Sign-in: `claude auth login` with piped stdio; the URL is the first `https://` token in stdout; a 10-minute timeout kills it. The code is written to stdin followed by newline; exit status 0 → refresh auth, otherwise the stdout/stderr tail becomes the error.

Statuses: `stopped`, `starting`, `running`, `stopping`, `error`.

### `AppState`

- Builds the runner; forwards `_on_session_change` to it; includes `runner.view()` under `claude` in every browser state broadcast; the runner's `on_change` callback is `schedule_broadcast`.
- Lifespan runs `startup()` and `shutdown()`.

### `core/store.py`

`load_settings()` / `save_settings(dict)` on `<data dir>/settings.json`. Holds `claude_model`.

### `config.py`

`ServerConfig.claude_path` from `CHESS_CLAUDE_PATH`; `api_url` property for the MCP client's server URL.

### `__main__.py`

`python -m chess_mcp …` runs `main()`, so the hosted CLI can launch the MCP client with the server's own interpreter.

### WebSocket messages (browser → server)

| Type | Fields | Effect |
|---|---|---|
| `claude_start` | | start with the saved model |
| `claude_stop` | | stop |
| `claude_model` | `model` | save; restart if running |
| `claude_login` | | begin sign-in; the URL appears in state |
| `claude_login_code` | `code` | finish sign-in |
| `claude_login_cancel` | | abandon sign-in |
| `claude_logout` | | sign out (stops Claude first) |

Errors use the existing `error` message with codes `claude_unavailable`,
`claude_not_signed_in`, `claude_busy`, `bad_model`, `no_login`.

### State sent to the browser

```json
"claude": {
  "available": true,
  "status": "running",
  "model": "claude-opus-5-5",
  "models": [{"id": "claude-fable-5-1", "name": "Fable 5.1"}, …],
  "error": null,
  "auth": {"logged_in": true, "email": "me@example.com"},
  "login": {"url": null, "busy": false}
}
```

### Web UI

- Panel header gains a Claude button (robot glyph) that opens the Claude dialog.
- Status line: "Claude isn't running" / "Claude is starting…" / "Claude stopped: …" when the runner is available; the old Claude Code hint when it is not.
- Banner: while Claude is not connected, a "Start Claude" button (signed in) or "Sign in to Claude" button (not signed in) when the runner is available.
- Claude dialog: account row (signed in as … / Sign out, or Sign in), the sign-in step (link to open, code input, Continue, Cancel), a model select, a Start/Stop button with the status and last error.

### Deploy

- `bootstrap.sh` installs Claude Code for the `chess` user with the native installer; `chess.service` sets `CHESS_CLAUDE_PATH`; `update.sh` runs `claude update`.

## Testing

- `tests/fake_claude.py`: an executable stand-in for the CLI driven by a directory in `FAKE_CLAUDE_DIR`: `auth status --json` (signed in iff `creds` exists), `auth login` (prints a URL, reads a code, accepts `good`), `auth logout`, and `-p … stream-json` (emits `init`, then for each stdin message an `assistant` line and a `result` line; logs received messages to a file).
- Runner tests: availability, sign-in happy path and bad code, start → running, nudge on session change, no repeated nudge for unchanged events, model change restarts, stop.
- WebSocket tests: `claude` appears in state; each message type; error codes.
