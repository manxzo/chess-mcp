# Difficulty (Elo) and the chess.com-style UI

Date: 2026-10-12
Status: Implemented alongside this spec

## Decisions (from the user)

| Topic | Decision |
|---|---|
| Difficulty | A target Elo. Claude keeps choosing the moves, but is told the target and gets a move suggestion from Stockfish limited to that strength each turn; it may deviate. A "Claude" setting (no target) keeps Claude's own play. |
| Elo range | 1320 to 3190, what Stockfish's `UCI_Elo` supports. Presets in the UI; the slider snaps to 10. |
| Mobile UI | chess.com-style: board screen with a bottom tab bar (Play, Review, Chat, More), a horizontal move strip under the board, sheets for chat and settings. Sounds (synthesised, no assets), premoves, piece animations, move arrows in review. |
| Desktop UI | Board with player bars on the left; right panel with tabs (Moves, Chat, Review) and the game actions. Same visual language as today, tightened. |
| Purpose | Self-improvement: reviews, live eval and Claude's coaching stay at full engine strength; only the opponent's move suggestion is limited. |

## Backend

### Engine strength
`EngineRegistry.limited(elo)` returns a dedicated Stockfish process with `UCI_LimitStrength=true`,
`UCI_Elo=<elo>`, one thread. One instance is kept per Elo; changing the Elo closes the old one lazily.
The suggestion search is `Limit(time_s=1.0)` so weak settings stay weak.

### Settings and game record
- `settings.json` gains `elo` (int or null). Null means "Claude": no target.
- Each game records `elo` at its start (`GameSession.elo`), shown in past games and reviews.

### API and MCP
- `claude_view` gains `target_elo`; `format_view` tells Claude the target and how to use it.
- `POST /api/suggest` → `{elo, move, score, pv}` from the limited engine for the current position;
  409 `game_over`, 400 `no_target` when no Elo is set, 409 `not_your_turn` unless it is Claude's move.
- MCP tool `suggest_move()` wraps it.

### WebSocket
- `set_difficulty {elo: int|null}` any time; `new_game` accepts an optional `elo`.
- Browser state gains `difficulty: {elo, min: 1320, max: 3190}` and each game's `elo`.

## Frontend (Codex brief in `docs/superpowers/specs/2026-10-12-ui-brief.md`)

See the brief for the screen-by-screen design; it is the contract Codex implemented against.
