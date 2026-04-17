from packages.core.session_token import generate_session_token, hash_token


def test_generate_session_token_length() -> None:
    token = generate_session_token()
    # 32 bytes base64url = 43 characters
    assert len(token) >= 40


def test_generate_session_token_uniqueness() -> None:
    tokens = {generate_session_token() for _ in range(100)}
    assert len(tokens) == 100


def test_hash_token_deterministic() -> None:
    token = "test-token-value"
    assert hash_token(token) == hash_token(token)


def test_hash_token_differs_for_different_input() -> None:
    assert hash_token("token-a") != hash_token("token-b")


def test_hash_token_is_hex_sha256() -> None:
    h = hash_token("anything")
    assert len(h) == 64  # SHA-256 hex digest
    assert all(c in "0123456789abcdef" for c in h)
