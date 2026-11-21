import asyncio

import chess
import pytest

from chess_mcp.core.game import GameError, GameSession, parse_color


def human_white() -> GameSession:
    return GameSession(human_color=chess.WHITE)


def test_new_session_starts_with_human_to_move():
    s = human_white()
    assert s.status == "active"
    assert s.side_to_move() == "human"
    assert s.claude_color == chess.BLACK


def test_play_accepts_san_and_uci_and_passes_the_turn():
    s = human_white()
    assert s.play("e4", by="human") == "e4"
    assert s.side_to_move() == "claude"
    assert s.play("c7c5", by="claude") == "c5"
    assert s.side_to_move() == "human"


@pytest.mark.parametrize("text", ["O-O", "0-0", "Nf3+", "Nf3!?", "e2-e4", "E2E4"])
def test_play_accepts_common_notations(text):
    s = human_white()
    if text in ("O-O", "0-0"):
        s.board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    if text.startswith("E") or text.startswith("e"):
        s.play(text, by="human")
        assert s.board.peek().uci() == "e2e4"
    elif text.startswith("N"):
        s.play(text, by="human")
        assert s.board.peek().uci() == "g1f3"
    else:
        s.play(text, by="human")
        assert s.board.peek().uci() == "e1g1"


def test_out_of_turn_move_is_rejected():
    s = human_white()
    with pytest.raises(GameError) as exc:
        s.play("e5", by="claude")
    assert exc.value.code == "not_your_turn"


def test_illegal_move_lists_some_legal_moves():
    s = human_white()
    with pytest.raises(GameError) as exc:
        s.play("e5", by="human")
    assert exc.value.code == "illegal_move"
    assert "Nf3" in exc.value.message


def test_promotion_needs_a_piece():
    s = human_white()
    s.board = chess.Board("7k/P7/8/8/8/8/8/K7 w - - 0 1")
    with pytest.raises(GameError):
        s.play("a7a8", by="human")
    assert s.play("a7a8q", by="human") == "a8=Q+"


def test_checkmate_ends_the_game():
    s = GameSession(human_color=chess.BLACK)
    s.play("f3", by="claude")
    s.play("e5", by="human")
    s.play("g4", by="claude")
    s.play("Qh4#", by="human")
    assert s.status == "checkmate"
    assert s.winner == "black"
    assert s.result == "0-1"
    assert s.reason == "checkmate"
    with pytest.raises(GameError) as exc:
        s.play("a3", by="claude")
    assert exc.value.code == "game_over"


def test_resign():
    s = human_white()
    s.play("e4", by="human")
    s.resign("human")
    assert s.status == "resigned"
    assert s.winner == "black"
    assert s.result == "0-1"
    assert s.reason == "white resigned"


def test_draw_offer_accept_decline_and_errors():
    s = human_white()
    s.offer_draw("human")
    assert s.draw_offer == "human"
    with pytest.raises(GameError) as exc:
        s.answer_draw("human", True)
    assert exc.value.code == "no_draw_offer"
    s.answer_draw("claude", False)
    assert s.draw_offer is None
    s.offer_draw("claude")
    s.answer_draw("human", True)
    assert s.status == "draw_agreed"
    assert s.result == "1/2-1/2"


def test_mutual_draw_offers_end_in_a_draw():
    s = human_white()
    s.offer_draw("human")
    s.offer_draw("claude")
    assert s.status == "draw_agreed"


def test_a_move_declines_the_opponents_offer():
    s = human_white()
    s.offer_draw("claude")
    s.play("e4", by="human")
    assert s.draw_offer is None


def test_new_game_is_refused_mid_game_but_allowed_after_it_ends():
    s = human_white()
    s.play("e4", by="human")
    s.play("e5", by="claude")
    with pytest.raises(GameError) as exc:
        s.new_game(chess.BLACK, by="human")
    assert exc.value.code == "game_in_progress"
    old_id = s.game_id
    s.resign("human")
    s.new_game(chess.BLACK, by="human")
    assert s.game_id != old_id
    assert s.board.move_stack == []
    assert s.human_color == chess.BLACK
    assert s.status == "active"


def test_new_game_with_one_ply_is_allowed():
    s = human_white()
    s.play("e4", by="human")
    s.new_game(chess.WHITE, by="human")
    assert s.board.move_stack == []


def test_chat_validation_and_ids():
    s = human_white()
    with pytest.raises(GameError):
        s.add_chat("human", "   ")
    m1 = s.add_chat("human", "hi")
    m2 = s.add_chat("claude", "x" * 5000)
    assert (m1.id, m2.id) == (1, 2)
    assert len(m2.text) == 2000


def test_chat_still_works_after_the_game_ends():
    s = human_white()
    s.resign("human")
    s.add_chat("claude", "Good game! Want to look at the review?")
    assert s.chat[-1].sender == "claude"


def test_claude_events_and_seen_cursor():
    s = human_white()
    assert s.claude_events() == ["new_game"]
    s.claude_view(mark_seen=True)
    assert s.claude_events() == []
    s.add_chat("human", "good luck")
    s.play("e4", by="human")
    assert s.claude_events() == ["message", "your_move"]
    view = s.claude_view(mark_seen=True)
    assert view["new_messages"] == ["good luck"]
    assert view["your_turn"] is True
    assert "e5" in view["legal_moves"]
    assert s.claude_events() == ["your_move"]


def test_game_over_is_reported_to_claude_once():
    s = human_white()
    s.claude_view(mark_seen=True)
    s.play("e4", by="human")
    s.resign("human")
    assert s.claude_events() == ["game_over"]
    with pytest.raises(GameError) as exc:
        s.play("e5", by="claude")
    assert exc.value.code == "game_over"
    s.claude_view(mark_seen=True)
    assert s.claude_events() == []


def test_draw_offer_event_for_claude():
    s = human_white()
    s.claude_view(mark_seen=True)
    s.offer_draw("human")
    assert "draw_offer" in s.claude_events()


def test_claude_view_board_is_from_claudes_side():
    s = human_white()  # Claude is black, so rank 1 is on top
    view = s.claude_view(mark_seen=False)
    first_line = view["board"].splitlines()[0]
    assert first_line.startswith("1 ")
    assert view["you_play"] == "black"


def test_browser_state_dests_only_on_humans_turn():
    s = human_white()
    state = s.browser_state()
    assert "e4" in state["dests"]["e2"]
    s.play("e4", by="human")
    assert s.browser_state()["dests"] == {}
    assert s.browser_state()["last_move"] == ["e2", "e4"]


async def test_wait_for_change_wakes_and_times_out():
    s = human_white()
    assert await s.wait_for_change(0.01) is False

    async def later():
        await asyncio.sleep(0.01)
        s.play("e4", by="human")

    task = asyncio.create_task(later())
    assert await s.wait_for_change(1.0) is True
    await task


def test_listeners_are_called_on_every_change():
    s = human_white()
    calls = []
    s.listeners.append(lambda: calls.append(s.version))
    s.play("e4", by="human")
    s.add_chat("claude", "hello")
    assert calls == [1, 2]


def test_record_round_trip():
    s = human_white()
    s.play("e4", by="human")
    s.add_chat("human", "hi")
    s.claude_view(mark_seen=True)
    copy = GameSession.from_record(s.to_record())
    assert copy.board.fen() == s.board.fen()
    assert copy.chat == s.chat
    assert copy.claude_events() == ["your_move"]


def test_from_record_rejects_illegal_moves():
    record = human_white().to_record()
    record["moves"] = ["e2e5"]
    with pytest.raises(ValueError):
        GameSession.from_record(record)


def test_pgn_contains_moves_result_and_chat():
    s = human_white()
    s.play("e4", by="human")
    s.add_chat("claude", "Classic.")
    s.resign("human")
    pgn = s.pgn()
    assert "1. e4" in pgn
    assert "0-1" in pgn
    assert "Claude: Classic." in pgn


def test_parse_color():
    assert parse_color("white") == chess.WHITE
    assert parse_color("random") in (chess.WHITE, chess.BLACK)
    with pytest.raises(GameError):
        parse_color("purple")
