import hashlib
import hmac
import secrets


def new_edit_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # Tokens are 256-bit random values, so a fast hash is sufficient (no brute-force risk).
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
