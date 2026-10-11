"""Plain-text renderings of API responses, written for Claude to read."""

from __future__ import annotations


def format_view(v: dict, ui_link: str | None) -> str:
    lines = [f"Game {v['game_id']}. You play {v['you_play']}."]
    if v["status"] == "active":
        lines.append("It is YOUR move." if v["your_turn"] else f"Waiting for the human ({v['turn']}) to move.")
        if v["in_check"]:
            lines.append("The side to move is in check.")
    else:
        lines.append(f"Game over: {v['result']} ({v['reason']}).")
    if v["draw_offer"] == "human":
        lines.append("The human offers a draw. Answer with respond_to_draw(accept=true or false).")
    elif v["draw_offer"] == "claude":
        lines.append("Your draw offer is waiting for the human.")
    if v["last_move"]:
        lines.append(f"Last move: {v['last_move']}")
    lines.append(f"Moves: {v['moves'] or '(none yet)'}")
    if v["new_messages"]:
        lines.append("New messages from the human:")
        lines.extend(f"  > {m}" for m in v["new_messages"])
    lines += ["", "Board (your side at the bottom; uppercase = White):", v["board"], f"FEN: {v['fen']}"]
    if v["legal_moves"]:
        lines.append("Legal moves: " + " ".join(v["legal_moves"]))
    if ui_link:
        lines.append(f"Web UI for the human: {ui_link}")
    return "\n".join(lines)


def format_analysis(r: dict) -> str:
    head = f"{r['engine']} at depth {r['depth']} ({r['side_to_move']} to move; scores from {r['side_to_move']}'s side):"
    body = [f"  {i}. {line['move']}  {line['score']}  {line['pv']}" for i, line in enumerate(r["lines"], 1)]
    return "\n".join([head, *body])


def _move_label(m: dict) -> str:
    number = (m["ply"] + 1) // 2
    return f"{number}. {m['san']}" if m["color"] == "white" else f"{number}... {m['san']}"


def format_review(r: dict, detail: str) -> str:
    lines = [f"Review of game {r['game_id']}: {r['opening'] or 'unknown opening'}. Result {r['result']} ({r['reason']})."]
    for side in ("white", "black"):
        p = r[side]
        accuracy = f"{p['accuracy']:.1f}%" if p["accuracy"] is not None else "n/a"
        counts = ", ".join(f"{k} {v}" for k, v in p["counts"].items() if v)
        lines.append(f"{p['name']} ({side}): accuracy {accuracy}; {counts or 'no moves'}")
    if detail != "summary":
        lines.append("")
        lines.append("All moves:" if detail == "full" else "Key moments:")
        if not r["moves"]:
            lines.append("  (none)")
        for m in r["moves"]:
            best = ""
            if m["best_san"] and m["best_uci"] != m["uci"]:
                best = f"; best was {m['best_san']} ({m['best_line']})"
            lines.append(f"  {_move_label(m)} [{m['rating']}] eval after {m['eval_after']}{best}")
    return "\n".join(lines)


def format_games(games: list[dict]) -> str:
    if not games:
        return "No finished games yet."
    lines = ["Recent games (newest first):"]
    for g in games:
        lines.append(
            f"  {g['game_id']}: human played {g['human_color']}, result {g['result']} ({g['reason']}), "
            f"{g['moves']} plies, {g['opening'] or 'unknown opening'}{', reviewed' if g['reviewed'] else ''}"
        )
    return "\n".join(lines)
