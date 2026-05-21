"""Authentication service for the Trading User Management API.

Provides :class:`AuthService` which implements user registration, login,
token refresh, and logout operations.

Design decisions:
- Passwords are hashed with bcrypt via ``password_utils`` (never stored plain).
- Access tokens are signed JWTs produced by ``jwt_utils.create_access_token``.
- Refresh tokens are ``secrets.token_hex(32)`` (64-char hex); only the
  SHA-256 digest is persisted in ``user_tokens``.  This is safe because
  256 bits of entropy makes rainbow tables infeasible (see design.md).
- Login / refresh errors deliberately return generic 401 messages to prevent
  user enumeration (Requirements 2.3, 3.2).

Requirements: 1.1, 1.3, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5,
              3.1, 3.2, 3.3, 3.4, 4.1
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from ..config import TradingSettings
from ..jwt_utils import create_access_token
from ..password_utils import hash_password, verify_password
from ..user_models import AccessTokenResponse, TokenResponse, UserProfileResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_hex(token: str) -> str:
    """Return the lower-case SHA-256 hex digest of *token*."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class AuthService:
    """Handles user registration, JWT-based login, refresh, and logout.

    Args:
        supabase: An initialised Supabase client (``supabase-py``).
        settings: The :class:`~..config.TradingSettings` instance that
            provides JWT secret and token expiry configuration.
    """

    def __init__(self, supabase: Any, settings: TradingSettings) -> None:
        self._supabase = supabase
        self._settings = settings

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(
        self,
        email: str,
        name: str,
        password: str,
        telegram_chat_id: str | None = None,
    ) -> UserProfileResponse:
        """Create a new user account.

        1. Hashes the plaintext password with bcrypt.
        2. Inserts a new row into the ``users`` table.
        3. Returns the created user profile.

        Args:
            email: The user's email address (must be unique).
            name: The user's display name.
            password: The plaintext password (≥ 8 chars, validated upstream).
            telegram_chat_id: Optional Telegram chat ID for notifications.

        Returns:
            :class:`~..user_models.UserProfileResponse` for the new user.

        Raises:
            HTTPException(409): When the email already exists in ``users``.
            HTTPException(503): On unexpected database errors.
        """
        password_hash = hash_password(password)

        row: dict[str, Any] = {
            "email": email,
            "name": name,
            "password_hash": password_hash,
            "is_active": True,
        }
        if telegram_chat_id is not None:
            row["telegram_chat_id"] = telegram_chat_id

        try:
            response = self._supabase.table("users").insert(row).execute()
        except Exception as exc:
            exc_str = str(exc).lower()
            # Supabase / PostgREST surfaces unique violations in various ways;
            # we check for the email uniqueness constraint by inspecting the
            # error message text.
            if "duplicate" in exc_str or "unique" in exc_str or "23505" in exc_str:
                raise HTTPException(
                    status_code=409,
                    detail="Email already registered",
                ) from exc
            logger.error(
                "Database error during register for email=%s: %s",
                email,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=503,
                detail="Service unavailable",
            ) from exc

        if not response.data:
            # Insert succeeded but returned no rows — should not happen with
            # Supabase's default ``RETURNING`` behaviour, but guard anyway.
            logger.error(
                "User insert for email=%s returned no data", email
            )
            raise HTTPException(status_code=503, detail="Service unavailable")

        # Check for duplicate-key error surfaced inside response.data
        # (some Supabase client versions return the error in the response body
        # rather than raising).
        if isinstance(response.data, dict) and response.data.get("code") == "23505":
            raise HTTPException(
                status_code=409,
                detail="Email already registered",
            )

        user = response.data[0]
        return _to_profile_response(user)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> TokenResponse:
        """Authenticate a user and issue JWT + refresh token.

        1. Looks up the user by email.
        2. Verifies the bcrypt password hash.
        3. Checks ``is_active``.
        4. Issues a signed JWT access token.
        5. Generates a cryptographically random refresh token (hex-64).
        6. Persists the SHA-256 hash of the refresh token in ``user_tokens``.
        7. Returns the full token response.

        Args:
            email: The user's email address.
            password: The plaintext password to verify.

        Returns:
            :class:`~..user_models.TokenResponse` with access and refresh tokens.

        Raises:
            HTTPException(401): For wrong email, wrong password, or inactive user.
            HTTPException(503): On unexpected database errors.
        """
        # --- Fetch user by email ----------------------------------------
        try:
            user_resp = (
                self._supabase.table("users")
                .select("id, email, name, password_hash, telegram_chat_id, is_active, created_at")
                .eq("email", email)
                .single()
                .execute()
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            # PostgREST returns a "PGRST116" code when `.single()` finds no rows.
            if "pgrst116" in exc_str or "no rows" in exc_str or "0 rows" in exc_str:
                raise HTTPException(status_code=401, detail="Invalid credentials") from exc
            logger.error(
                "Database error during login for email=%s: %s", email, exc, exc_info=True
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not user_resp.data:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        user = user_resp.data

        # --- Verify password --------------------------------------------
        stored_hash: str = user.get("password_hash", "")
        if not stored_hash or not verify_password(password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # --- Check is_active --------------------------------------------
        if not user.get("is_active", False):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        user_id: str = user["id"]

        # --- Issue JWT access token -------------------------------------
        access_token = create_access_token(
            user_id=user_id,
            secret=self._settings.jwt_secret,
            expire_minutes=self._settings.access_token_expire_minutes,
        )

        # --- Generate and persist refresh token -------------------------
        plain_refresh = secrets.token_hex(32)  # 64-char hex, 256 bits entropy
        token_hash = _sha256_hex(plain_refresh)

        expires_at = datetime.now(timezone.utc) + timedelta(
            days=self._settings.refresh_token_expire_days
        )

        try:
            self._supabase.table("user_tokens").insert(
                {
                    "user_id": user_id,
                    "token_hash": token_hash,
                    "expires_at": expires_at.isoformat(),
                }
            ).execute()
        except Exception as exc:
            logger.error(
                "Failed to persist refresh token for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        return TokenResponse(
            access_token=access_token,
            refresh_token=plain_refresh,
        )

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    async def refresh(self, refresh_token: str) -> AccessTokenResponse:
        """Exchange a valid refresh token for a new JWT access token.

        1. Computes SHA-256 hash of the incoming refresh token.
        2. Looks up the hash in ``user_tokens``.
        3. If not found → 401.
        4. If ``expires_at`` is in the past → delete the record and return 401.
        5. Checks that the associated user has ``is_active = true``.
        6. Issues a new JWT access token.

        Args:
            refresh_token: The plaintext refresh token previously returned
                by :meth:`login`.

        Returns:
            :class:`~..user_models.AccessTokenResponse` with a new JWT.

        Raises:
            HTTPException(401): For invalid, expired, or inactive-user tokens.
            HTTPException(503): On unexpected database errors.
        """
        token_hash = _sha256_hex(refresh_token)

        # --- Look up token record ---------------------------------------
        try:
            token_resp = (
                self._supabase.table("user_tokens")
                .select("id, user_id, expires_at")
                .eq("token_hash", token_hash)
                .single()
                .execute()
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "pgrst116" in exc_str or "no rows" in exc_str or "0 rows" in exc_str:
                raise HTTPException(
                    status_code=401, detail="Invalid or expired refresh token"
                ) from exc
            logger.error(
                "Database error during refresh token lookup: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not token_resp.data:
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token"
            )

        token_record = token_resp.data
        token_id: str = token_record["id"]
        user_id: str = token_record["user_id"]

        # --- Check expiry -----------------------------------------------
        expires_at_raw: str = token_record["expires_at"]
        expires_at = _parse_iso_datetime(expires_at_raw)
        now = datetime.now(timezone.utc)

        if expires_at <= now:
            # Delete the expired record as required by Req 3.3
            try:
                self._supabase.table("user_tokens").delete().eq("id", token_id).execute()
            except Exception as del_exc:
                logger.warning(
                    "Failed to delete expired token id=%s: %s", token_id, del_exc
                )
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token"
            )

        # --- Check user is_active ----------------------------------------
        try:
            user_resp = (
                self._supabase.table("users")
                .select("is_active")
                .eq("id", user_id)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching user=%s during refresh: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not user_resp.data or not user_resp.data.get("is_active"):
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token"
            )

        # --- Issue new JWT access token ---------------------------------
        access_token = create_access_token(
            user_id=user_id,
            secret=self._settings.jwt_secret,
            expire_minutes=self._settings.access_token_expire_minutes,
        )

        return AccessTokenResponse(access_token=access_token)

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    async def logout(self, user_id: str) -> None:
        """Revoke all refresh tokens for *user_id*.

        Deletes every row in ``user_tokens`` where ``user_id`` matches,
        effectively ending all active sessions for the user.

        Args:
            user_id: UUID string of the authenticated user.

        Raises:
            HTTPException(503): On unexpected database errors.
        """
        try:
            self._supabase.table("user_tokens").delete().eq(
                "user_id", user_id
            ).execute()
        except Exception as exc:
            logger.error(
                "Database error during logout for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _to_profile_response(user: dict[str, Any]) -> UserProfileResponse:
    """Convert a raw ``users`` table row dict into a :class:`UserProfileResponse`."""
    return UserProfileResponse(
        id=str(user["id"]),
        email=user["email"],
        name=user["name"],
        telegram_chat_id=user.get("telegram_chat_id"),
        is_active=bool(user.get("is_active", True)),
        created_at=_parse_iso_datetime(user["created_at"]),
    )


def _parse_iso_datetime(value: Any) -> datetime:
    """Parse an ISO 8601 timestamp string (or ``datetime``) to a UTC ``datetime``.

    Supabase returns timestamps as ISO strings; we normalise to UTC-aware
    ``datetime`` objects.
    """
    if isinstance(value, datetime):
        # Ensure timezone-aware
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    # String: try fromisoformat (Python 3.11+ handles 'Z' suffix; earlier
    # versions need the trailing 'Z' replaced with '+00:00').
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)
