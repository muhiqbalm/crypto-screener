"""Webhook configuration service for the Trading User Management API.

Provides :class:`WebhookConfigService` which manages creation, retrieval,
update, and deactivation of a user's webhook passphrase configuration stored
in the ``webhook_configs`` table.

Design decisions:
- Passphrases are stored in plaintext in the DB and returned in full in API
  responses (by design — they are shared with TradingView, not secrets in the
  traditional sense).
- Global passphrase uniqueness is enforced across all users so that each
  incoming TradingView webhook can be unambiguously routed to one account.
- Only one active config per user is permitted at any time; callers must
  deactivate the existing config before creating a new one.

Requirements: 8.1, 8.2, 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 11.1, 11.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..user_models import WebhookConfigResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WebhookConfigService
# ---------------------------------------------------------------------------


class WebhookConfigService:
    """Manages webhook passphrase configuration records.

    Each user may have at most one *active* :class:`WebhookConfigResponse`
    at a time.  Passphrases must be globally unique across all users so that
    the TradingView webhook endpoint can resolve the correct account from the
    passphrase alone.

    Args:
        supabase: An initialised Supabase client (``supabase-py``).
    """

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    # ------------------------------------------------------------------
    # Get active config
    # ------------------------------------------------------------------

    async def get_active(self, user_id: str) -> WebhookConfigResponse:
        """Return the active webhook config for *user_id*.

        Queries the ``webhook_configs`` table for the row where
        ``user_id`` matches and ``is_active`` is ``true``.

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            :class:`~..user_models.WebhookConfigResponse` for the active config.

        Raises:
            HTTPException(404): When no active config exists for the user.
            HTTPException(503): On unexpected database errors.
        """
        try:
            response = (
                self._supabase.table("webhook_configs")
                .select("id, passphrase, is_active, created_at")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .single()
                .execute()
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "pgrst116" in exc_str or "no rows" in exc_str or "0 rows" in exc_str:
                raise HTTPException(
                    status_code=404, detail="No active webhook configuration found"
                ) from exc
            logger.error(
                "Database error fetching webhook config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            raise HTTPException(
                status_code=404, detail="No active webhook configuration found"
            )

        return _to_webhook_config_response(response.data)

    # ------------------------------------------------------------------
    # Reactivate config
    # ------------------------------------------------------------------

    async def reactivate(self, user_id: str) -> WebhookConfigResponse:
        """Reactivate the most recent inactive webhook configuration for *user_id*.

        Instead of creating a new record, this method sets ``is_active = True``
        on the most recently deactivated config, preserving the existing
        passphrase and avoiding unnecessary row accumulation in the DB.

        Steps:
        1. Confirms no active config already exists (409 if one does).
        2. Finds the most recent inactive config for this user (404 if none).
        3. Sets ``is_active = True`` on that record.
        4. Returns the reactivated record.

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            :class:`~..user_models.WebhookConfigResponse` with ``is_active=True``.

        Raises:
            HTTPException(404): When no inactive config exists to reactivate.
            HTTPException(409): When the user already has an active config.
            HTTPException(503): On unexpected database errors.
        """
        # 1. Ensure no active config already exists
        await self._assert_no_active_config(user_id)

        # 2. Find the most recent inactive config
        try:
            response = (
                self._supabase.table("webhook_configs")
                .select("id, passphrase, is_active, created_at")
                .eq("user_id", user_id)
                .eq("is_active", False)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching inactive config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            raise HTTPException(
                status_code=404, detail="No inactive webhook configuration found to reactivate"
            )

        config_id = response.data[0]["id"]

        # 3. Set is_active = True on that record
        try:
            self._supabase.table("webhook_configs").update(
                {"is_active": True}
            ).eq("id", config_id).execute()
        except Exception as exc:
            logger.error(
                "Database error reactivating webhook config id=%s for user=%s: %s",
                config_id,
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        return await self.get_active(user_id)

    # ------------------------------------------------------------------
    # Create config
    # ------------------------------------------------------------------

    async def create(self, user_id: str, passphrase: str) -> WebhookConfigResponse:
        """Create a new active webhook configuration for *user_id*.

        Steps:
        1. Validates that no active config already exists for this user (409).
        2. Validates that the passphrase is not already used by any user (409).
        3. Inserts a new record with ``is_active=True``.
        4. Returns the created record.

        Note: The ≥ 8 character minimum on *passphrase* is enforced upstream
        by :class:`~..user_models.WebhookConfigCreateRequest`; this method
        trusts that the Pydantic validation has already run.

        Args:
            user_id: UUID string of the authenticated user.
            passphrase: The plaintext passphrase (≥ 8 chars).

        Returns:
            :class:`~..user_models.WebhookConfigResponse` for the new record.

        Raises:
            HTTPException(409): When the user already has an active config.
            HTTPException(409): When the passphrase is already in use globally.
            HTTPException(503): On unexpected database errors.
        """
        # 1. Check for existing active config (Requirement 9.3)
        await self._assert_no_active_config(user_id)

        # 2. Check global passphrase uniqueness (Requirement 9.4)
        await self._assert_passphrase_unique(passphrase, exclude_user_id=None)

        # 3. Insert the new record
        row: dict[str, Any] = {
            "user_id": user_id,
            "passphrase": passphrase,
            "is_active": True,
        }

        try:
            self._supabase.table("webhook_configs").insert(row).execute()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "duplicate" in exc_str or "unique" in exc_str or "23505" in exc_str:
                raise HTTPException(
                    status_code=409,
                    detail="Passphrase already in use",
                ) from exc
            logger.error(
                "Database error creating webhook config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        # Fetch the newly created record
        return await self.get_active(user_id)

    # ------------------------------------------------------------------
    # Update config
    # ------------------------------------------------------------------

    async def update(self, user_id: str, passphrase: str) -> WebhookConfigResponse:
        """Update the passphrase on the user's active webhook configuration.

        Steps:
        1. Confirms an active config exists for this user (404 if not).
        2. Validates that the new passphrase is not already used by any user
           (409 if so — note: we do NOT exclude the current user's own record
           because the passphrase is changing, so any match is a conflict).
        3. Updates the passphrase on the active record.
        4. Returns the updated record.

        Args:
            user_id: UUID string of the authenticated user.
            passphrase: The new plaintext passphrase (≥ 8 chars, validated upstream).

        Returns:
            Updated :class:`~..user_models.WebhookConfigResponse`.

        Raises:
            HTTPException(404): When no active config exists for the user.
            HTTPException(409): When the new passphrase is already in use globally.
            HTTPException(503): On unexpected database errors.
        """
        # 1. Confirm active config exists (Requirement 10.3)
        existing = await self.get_active(user_id)  # raises 404 if none

        # 2. Check global passphrase uniqueness (Requirement 10.2)
        # We allow the user to "update" to their own current passphrase only
        # if it's effectively a no-op — but to keep the logic simple and
        # consistent with the spec, we check globally (excluding the current
        # record by its ID so a user can re-submit the same passphrase).
        await self._assert_passphrase_unique(passphrase, exclude_config_id=existing.id)

        # 3. Perform the update
        try:
            self._supabase.table("webhook_configs").update(
                {"passphrase": passphrase}
            ).eq("user_id", user_id).eq("is_active", True).execute()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "duplicate" in exc_str or "unique" in exc_str or "23505" in exc_str:
                raise HTTPException(
                    status_code=409,
                    detail="Passphrase already in use",
                ) from exc
            logger.error(
                "Database error updating webhook config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        return await self.get_active(user_id)

    # ------------------------------------------------------------------
    # Deactivate config
    # ------------------------------------------------------------------

    async def deactivate(self, user_id: str) -> WebhookConfigResponse:
        """Deactivate the user's active webhook configuration.

        Sets ``is_active = False`` on the active record without deleting it,
        so the passphrase history is preserved for audit purposes.

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            Updated :class:`~..user_models.WebhookConfigResponse` with
            ``is_active`` set to ``False``.

        Raises:
            HTTPException(404): When no active config exists for the user.
            HTTPException(503): On unexpected database errors.
        """
        # Confirm active config exists (Requirement 11.2)
        await self.get_active(user_id)  # raises 404 if none

        try:
            self._supabase.table("webhook_configs").update(
                {"is_active": False}
            ).eq("user_id", user_id).eq("is_active", True).execute()
        except Exception as exc:
            logger.error(
                "Database error deactivating webhook config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        # Fetch the deactivated record (is_active=False now)
        try:
            response = (
                self._supabase.table("webhook_configs")
                .select("id, passphrase, is_active, created_at")
                .eq("user_id", user_id)
                .eq("is_active", False)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching deactivated config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            raise HTTPException(
                status_code=404, detail="No active webhook configuration found"
            )

        return _to_webhook_config_response(response.data[0])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _assert_no_active_config(self, user_id: str) -> None:
        """Raise HTTP 409 if *user_id* already has an active webhook config.

        Used by :meth:`create` to enforce the one-active-config-per-user rule
        (Requirement 9.3).
        """
        try:
            response = (
                self._supabase.table("webhook_configs")
                .select("id")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error checking active config for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if response.data:
            raise HTTPException(
                status_code=409,
                detail="An active webhook configuration already exists",
            )

    async def _assert_passphrase_unique(
        self,
        passphrase: str,
        *,
        exclude_user_id: str | None = None,
        exclude_config_id: str | None = None,
    ) -> None:
        """Raise HTTP 409 if *passphrase* is already used by any webhook config.

        Optionally excludes rows matching *exclude_config_id* to allow a user
        to update a passphrase to itself without triggering the uniqueness check
        (e.g., when the update value is identical to the existing passphrase).

        Args:
            passphrase: The plaintext passphrase to check for global uniqueness.
            exclude_user_id: When set, exclude rows belonging to this user from
                the uniqueness check (not used in current flows; reserved).
            exclude_config_id: When set, exclude the config row with this ID
                from the uniqueness check (used during :meth:`update`).

        Raises:
            HTTPException(409): When the passphrase already exists in another row.
            HTTPException(503): On unexpected database errors.
        """
        try:
            query = (
                self._supabase.table("webhook_configs")
                .select("id")
                .eq("passphrase", passphrase)
                .limit(1)
            )
            # Apply optional exclusion filters
            if exclude_config_id is not None:
                query = query.neq("id", exclude_config_id)
            if exclude_user_id is not None:
                query = query.neq("user_id", exclude_user_id)

            response = query.execute()
        except Exception as exc:
            logger.error(
                "Database error checking passphrase uniqueness: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if response.data:
            raise HTTPException(
                status_code=409,
                detail="Passphrase already in use",
            )


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _to_webhook_config_response(row: dict[str, Any]) -> WebhookConfigResponse:
    """Convert a raw ``webhook_configs`` table row dict to :class:`WebhookConfigResponse`."""
    return WebhookConfigResponse(
        id=str(row["id"]),
        passphrase=row["passphrase"],
        is_active=bool(row["is_active"]),
        created_at=_parse_iso_datetime(row["created_at"]),
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
