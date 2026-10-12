import json
import stat

from chess_mcp.core.game import GameSession
from chess_mcp.core.store import Store


def finished_record(game_id: str) -> dict:
    s = GameSession(game_id=game_id)
    s.play("e4", by="human")
    s.resign("human")
    rec = s.to_record()
    rec["opening"] = "King's Pawn Game"
    return rec


def test_current_round_trip(tmp_path):
    store = Store(tmp_path)
    assert store.load_current() is None
    store.save_current({"a": 1})
    assert store.load_current() == {"a": 1}


def test_corrupt_current_is_set_aside(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "current.json").write_text("{not json")
    assert store.load_current() is None
    assert (tmp_path / "current.json.bad").exists()


def test_discard_current(tmp_path):
    store = Store(tmp_path)
    store.save_current({"a": 1})
    store.discard_current()
    assert store.load_current() is None
    assert (tmp_path / "current.json.bad").exists()


def test_archive_list_and_load(tmp_path):
    store = Store(tmp_path)
    store.archive(finished_record("20261011-100000-aaaa"), "1. e4 0-1")
    store.archive(finished_record("20261011-110000-bbbb"), "1. e4 0-1")
    games = store.list_games()
    assert [g["game_id"] for g in games] == ["20261011-110000-bbbb", "20261011-100000-aaaa"]
    assert games[0]["opening"] == "King's Pawn Game"
    assert games[0]["moves"] == 1
    assert games[0]["reviewed"] is False
    assert store.load_game("20261011-100000-aaaa")["result"] == "0-1"
    assert (tmp_path / "games" / "20261011-100000-aaaa.pgn").read_text() == "1. e4 0-1"
    assert len(store.list_games(limit=1)) == 1


def test_load_game_rejects_bad_ids(tmp_path):
    store = Store(tmp_path)
    assert store.load_game("../current") is None
    assert store.load_game("20261011-100000-zzzz") is None


def test_reviews(tmp_path):
    store = Store(tmp_path)
    store.archive(finished_record("20261011-100000-aaaa"), "")
    assert store.load_review("20261011-100000-aaaa") is None
    store.save_review("20261011-100000-aaaa", {"x": 1})
    assert store.load_review("20261011-100000-aaaa") == {"x": 1}
    assert store.list_games()[0]["reviewed"] is True


def test_token_is_generated_once_and_private(tmp_path):
    store = Store(tmp_path)
    token = store.token()
    assert len(token) >= 24
    assert Store(tmp_path).token() == token
    mode = stat.S_IMODE((tmp_path / "token").stat().st_mode)
    assert mode == 0o600


def test_save_is_atomic_json(tmp_path):
    store = Store(tmp_path)
    store.save_current({"x": "é"})
    assert json.loads((tmp_path / "current.json").read_text(encoding="utf-8")) == {"x": "é"}
    assert not list(tmp_path.glob("*.tmp"))


def test_settings_round_trip_and_tolerate_garbage(tmp_path):
    from chess_mcp.core.store import Store

    store = Store(tmp_path)
    assert store.load_settings() == {}
    store.save_settings({"claude_model": "claude-sonnet-5-5"})
    assert store.load_settings() == {"claude_model": "claude-sonnet-5-5"}
    (tmp_path / "settings.json").write_text("[1, 2]")
    assert store.load_settings() == {}
