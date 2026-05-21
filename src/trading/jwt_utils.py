"""JWT utility functions for the trading API.

Provides helpers for creating and decoding HS256-signed access tokens.
The ``JWTError`` exception from ``jose`` is re-exported so callers only
need to import from this module.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt  # noqa: F401  (JWTError re-exported for callers)

__all__ = ["create_access_token", "decode_access_token", "JWTError"]


def create_access_token(user_id: str, secret: str, expire_minutes: int) -> str:
    """Return a signed HS256 JWT with ``sub``, ``exp``, and ``iat`` claims.

    Args:
        user_id: The user's UUID string, stored in the ``sub`` claim.
        secret: The HMAC-SHA256 signing secret (``TRADING_JWT_SECRET``).
        expire_minutes: Number of minutes until the token expires.

    Returns:
        A compact, URL-safe JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    """Decode and verify a JWT.

    Args:
        token: The compact JWT string to verify.
        secret: The HMAC-SHA256 signing secret used to verify the signature.

    Returns:
        The decoded payload as a plain ``dict``.

    Raises:
        JWTError: If the signature is invalid, the token is expired, or the
            token is otherwise malformed.
    """
    return jwt.decode(token, secret, algorithms=["HS256"])
