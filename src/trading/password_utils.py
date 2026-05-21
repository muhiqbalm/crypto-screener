"""
Password hashing and verification utilities using passlib[bcrypt].

Requirements: 1.6, 7.2
"""

from passlib.context import CryptContext

_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt. Returns the hashed string."""
    return _ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash. Returns True if they match."""
    return _ctx.verify(plain, hashed)
