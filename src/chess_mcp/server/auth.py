import hmac


def token_matches(given: str | None, expected: str) -> bool:
    if not given:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())
