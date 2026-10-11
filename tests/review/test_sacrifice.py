import chess

from chess_mcp.review.sacrifice import is_sacrifice, material_given_up, see


def given(fen: str, san: str) -> int:
    board = chess.Board(fen)
    return material_given_up(board, board.parse_san(san))


def test_see_defended_piece_is_an_even_trade():
    board = chess.Board("4k3/8/3p4/4n3/8/5N2/8/4K3 w - - 0 1")
    assert see(board, chess.E5, chess.WHITE) == 0


def test_see_undefended_piece_is_won():
    board = chess.Board("4k3/8/8/4n3/8/5N2/8/4K3 w - - 0 1")
    assert see(board, chess.E5, chess.WHITE) == 3


def test_greek_gift_is_a_sacrifice():
    fen = "r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQ - 0 7"
    assert given(fen, "Bxh7+") == 2
    board = chess.Board(fen)
    assert is_sacrifice(board, board.parse_san("Bxh7+"))


def test_quiet_developing_moves_are_not_sacrifices():
    assert given(chess.STARTING_FEN, "e4") == 0
    assert given("rnbqkb1r/pppp1ppp/5n2/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 2 3", "Bc4") == 0


def test_hanging_the_queen_counts():
    board = chess.Board("rnbqkbnr/1ppppppp/p7/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    board.push_san("Qg4")
    board.push_san("a5")
    assert material_given_up(board, board.parse_san("Qxg7")) == 8


def test_mating_capture_is_not_a_sacrifice():
    assert given("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "Qxf7#") < 2


def test_promotion_is_a_gain():
    board = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    assert material_given_up(board, chess.Move.from_uci("a7a8q")) < 0
