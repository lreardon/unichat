import hashlib
import secrets


def generate_session_token() -> str:
    """Generate a cryptographically random 32-byte base64url session token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hash of a session token for storage. Raw tokens never persisted."""
    return hashlib.sha256(token.encode()).hexdigest()
