from chess_mcp.review.book import book_plies, load_book, opening_name


def test_book_loads():
    book = load_book()
    assert len(book.positions) > 5000


def test_mainline_stays_in_book():
    assert book_plies(["e2e4", "e7e5", "g1f3", "b8c6"]) == 4


def test_leaving_theory():
    assert book_plies(["e2e4", "a7a6", "d1g4", "a6a5", "g4g7", "f8g7"]) == 2


def test_opening_name():
    assert opening_name(["e2e4", "c7c5", "g1f3"]) == "B27 Sicilian Defense"
    assert opening_name([]) is None
