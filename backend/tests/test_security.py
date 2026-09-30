from app.security import hash_token, new_edit_token, token_matches


def test_tokens_are_random_and_long():
    tokens = {new_edit_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 40 for t in tokens)


def test_hash_is_deterministic_and_not_plaintext():
    token = new_edit_token()
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token
    assert len(hash_token(token)) == 64


def test_token_matches():
    token = new_edit_token()
    h = hash_token(token)
    assert token_matches(token, h)
    assert not token_matches(token + "x", h)
    assert not token_matches("", h)
