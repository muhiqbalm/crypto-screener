"""Profile service for the Trading User Management API.

Provides :class:`ProfileService` which implements user profile retrieval
and partial-update operations.

Design decisions:
- ``get_profile`` never includes ``password_hash`` in its response
  (Requirements 6.1, 6.2).
- ``update_profile`` updates **only** the fields present in the request;
  absent optional fields are left unchanged in the database (Requirement 7.1).
- When a new ``password`` is provided it is immediately hashed with bcrypt
  via ``password_utils.hash_password`` before persisting; the plaintext is
  never stored (Requirement 7.2).

Requirements: 6.1, 6.2, 7.1, 7.2, 7.3, 7.4
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..password_utils import hash_password
from ..user_models import ProfileUpdateRequest, UserProfileResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProfileService
# ---------------------------------------------------------------------------


class ProfileService:
    """Handles user profile retrieval and updates.

    Args:
        supabase: An initialised Supabase client (``supabase-py``).
    """

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    # ------------------------------------------------------------------
    # Get profile
    # ------------------------------------------------------------------

    async def get_profile(self, user_id: str) -> UserProfileResponse:
        """Return the profile for *user_id* without exposing ``password_hash``.

        Queries the ``users`` table for the row identified by *user_id* and
        maps it to a :class:`~..user_models.UserProfileResponse`.  The
        ``password_hash`` column is deliberately excluded from the SELECT
        projection to satisfy Requirement 6.2.

        Args:
            user_id: UUID string of the authenticated user (taken from the
                verified JWT ``sub`` claim).

        Returns:
            :class:`~..user_models.UserProfileResponse` for the user.

        Raises:
            HTTPException(404): When no matching user row is found.
            HTTPException(503): On unexpected database errors.
        """
        try:
            response = (
                self._supabase.table("users")
                .select("id, email, name, telegram_chat_id, is_active, created_at")
                .eq("id", user_id)
                .single()
                .execute()
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "pgrst116" in exc_str or "no rows" in exc_str or "0 rows" in exc_str:
                raise HTTPException(status_code=404, detail="User not found") from exc
            logger.error(
                "Database error fetching profile for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            raise HTTPException(status_code=404, detail="User not found")

        return _to_profile_response(response.data)

    # ------------------------------------------------------------------
    # Update profile
    # ------------------------------------------------------------------

    async def update_profile(
        self, user_id: str, update: ProfileUpdateRequest
    ) -> UserProfileResponse:
        """Partially update the profile for *user_id*.

        Only the fields that are explicitly provided (non-``None``) in
        *update* are written to the database.  If ``password`` is included,
        it is hashed with bcrypt before persisting; the plaintext is discarded
        immediately (Requirements 7.1, 7.2).

        The :class:`~..user_models.ProfileUpdateRequest` Pydantic validator
        guarantees that at least one field is non-``None`` before this method
        is called, so a completely empty update is impossible at this layer
        (Requirement 7.4).

        Args:
            user_id: UUID string of the authenticated user.
            update: The validated update payload from the request body.

        Returns:
            :class:`~..user_models.UserProfileResponse` reflecting the
            post-update state of the user row.

        Raises:
            HTTPException(404): When no matching user row is found.
            HTTPException(503): On unexpected database errors.
        """
        # Build the dict of columns to update — only include fields that
        # were explicitly set in the request (non-None).
        patch: dict[str, Any] = {}

        if update.name is not None:
            patch["name"] = update.name

        if update.telegram_chat_id is not None:
            patch["telegram_chat_id"] = update.telegram_chat_id

        if update.password is not None:
            patch["password_hash"] = hash_password(update.password)

        # Perform the UPDATE and return the updated row via .select()
        try:
            response = (
                self._supabase.table("users")
                .update(patch)
                .eq("id", user_id)
                .select("id, email, name, telegram_chat_id, is_active, created_at")
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error updating profile for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            raise HTTPException(status_code=404, detail="User not found")

        return _to_profile_response(response.data[0])


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _to_profile_response(user: dict[str, Any]) -> UserProfileResponse:
    """Convert a raw ``users`` table row dict into a :class:`UserProfileResponse`.

    Note: ``password_hash`` must **not** be present in *user*; the SELECT
    projection in :meth:`ProfileService.get_profile` and
    :meth:`ProfileService.update_profile` ensures this.
    """
    return UserProfileResponse(
        id=str(user["id"]),
        email=user["email"],
        name=user["name"],
        telegram_chat_id=user.get("telegram_chat_id"),
        is_active=bool(user.get("is_active", True)),
        created_at=_parse_iso_datetime(user["created_at"]),
    )


def _parse_iso_datetime(value: Any) -> datetime:
    """Parse an ISO 8601 timestamp string (or ``datetime``) to a UTC-aware ``datetime``.

    Supabase returns timestamps as ISO strings; we normalise to UTC-aware
    ``datetime`` objects.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)
