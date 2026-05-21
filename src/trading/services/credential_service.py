"""Credential service for the Trading User Management API.

Provides :class:`CredentialService` which implements listing, upserting, and
deleting per-user per-exchange API credentials in the ``exchange_credentials``
table.

Design decisions:
- All credential fields (``api_key``, ``secret``, ``api_passphrase``) are
  encrypted via the existing :class:`~..credentials.CredentialStore` Fernet
  mechanism before being written to the database (Requirement 13.1).
- Responses are always :class:`~..user_models.CredentialSummaryResponse`
  instances, which contain **no** key/secret/passphrase fields
  (Requirements 12.2, 13.4).
- ``delete_credentials`` validates that the requested exchange is one of
  ``"binance"`` or ``"okx"`` before attempting the delete, and raises 404
  when no matching row exists (Requirements 14.2, 14.3).

Requirements: 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.3
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..credentials import CredentialStore
from ..user_models import CredentialSummaryResponse, CredentialUpsertRequest

logger = logging.getLogger(__name__)

# Supported exchanges — kept as a frozenset for O(1) membership tests.
_SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"binance", "okx"})


# ---------------------------------------------------------------------------
# CredentialService
# ---------------------------------------------------------------------------


class CredentialService:
    """Manages per-user per-exchange API credentials.

    Args:
        supabase: An initialised Supabase client (``supabase-py``).
        credential_store: The :class:`~..credentials.CredentialStore` instance
            that handles Fernet encryption / decryption of credential fields.
    """

    def __init__(self, supabase: Any, credential_store: CredentialStore) -> None:
        self._supabase = supabase
        self._credential_store = credential_store

    # ------------------------------------------------------------------
    # List credentials
    # ------------------------------------------------------------------

    async def list_credentials(self, user_id: str) -> list[CredentialSummaryResponse]:
        """Return a summary of all configured exchanges for *user_id*.

        Queries the ``exchange_credentials`` table for all rows belonging to
        *user_id* and returns a list of :class:`~..user_models.CredentialSummaryResponse`
        objects.  The list is empty when the user has no credentials
        (Requirement 12.3).  API keys and secrets are never included in the
        response (Requirement 12.2).

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            A (possibly empty) list of :class:`~..user_models.CredentialSummaryResponse`.

        Raises:
            HTTPException(503): On unexpected database errors.
        """
        try:
            response = (
                self._supabase.table("exchange_credentials")
                .select("exchange, created_at")
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error listing credentials for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        rows: list[dict[str, Any]] = response.data if response.data else []
        return [_to_credential_summary(row) for row in rows]

    # ------------------------------------------------------------------
    # Upsert credentials
    # ------------------------------------------------------------------

    async def upsert_credentials(
        self,
        user_id: str,
        req: CredentialUpsertRequest,
    ) -> CredentialSummaryResponse:
        """Encrypt and upsert exchange credentials for *user_id*.

        Uses :meth:`~..credentials.CredentialStore.store_credentials` to
        encrypt ``api_key``, ``secret``, and the optional ``api_passphrase``
        with Fernet before writing to the database.  The upsert is keyed on
        ``(user_id, exchange)``, so calling this method twice for the same
        exchange replaces the existing row (Requirement 13.1).

        After the upsert the method fetches the stored row to obtain the
        canonical ``created_at`` timestamp that will be returned in the
        response.

        Args:
            user_id: UUID string of the authenticated user.
            req: The validated :class:`~..user_models.CredentialUpsertRequest`
                containing exchange, api_key, secret, and optional passphrase.

        Returns:
            :class:`~..user_models.CredentialSummaryResponse` with no key
            or secret values (Requirements 13.4).

        Raises:
            HTTPException(503): On unexpected database errors.
        """
        try:
            await self._credential_store.store_credentials(
                user_id=user_id,
                exchange=req.exchange,
                api_key=req.api_key,
                secret=req.secret,
                passphrase=req.api_passphrase,
            )
        except Exception as exc:
            logger.error(
                "Error storing credentials for user=%s exchange=%s: %s",
                user_id,
                req.exchange,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        # Fetch the stored row to get the canonical created_at timestamp
        try:
            fetch_resp = (
                self._supabase.table("exchange_credentials")
                .select("exchange, created_at")
                .eq("user_id", user_id)
                .eq("exchange", req.exchange)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching credential after upsert for user=%s exchange=%s: %s",
                user_id,
                req.exchange,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not fetch_resp.data:
            logger.error(
                "Credential row missing after upsert for user=%s exchange=%s",
                user_id,
                req.exchange,
            )
            raise HTTPException(status_code=503, detail="Service unavailable")

        return _to_credential_summary(fetch_resp.data)

    # ------------------------------------------------------------------
    # Delete credentials
    # ------------------------------------------------------------------

    async def delete_credentials(self, user_id: str, exchange: str) -> dict[str, str]:
        """Delete the credential record for *user_id* on *exchange*.

        Validates that *exchange* is one of the supported values before
        attempting the delete.  Raises 404 when no matching row exists
        (Requirements 14.2, 14.3).

        Args:
            user_id: UUID string of the authenticated user.
            exchange: Exchange identifier to delete (must be ``"binance"``
                or ``"okx"``).

        Returns:
            ``{"message": "Credentials removed"}`` on success.

        Raises:
            HTTPException(422): When *exchange* is not ``"binance"`` or ``"okx"``.
            HTTPException(404): When no credential row exists for the pair.
            HTTPException(503): On unexpected database errors.
        """
        if exchange not in _SUPPORTED_EXCHANGES:
            raise HTTPException(
                status_code=422,
                detail=f"Exchange must be one of: {sorted(_SUPPORTED_EXCHANGES)}",
            )

        # Confirm the row exists before deleting so we can return 404 if absent.
        try:
            check_resp = (
                self._supabase.table("exchange_credentials")
                .select("exchange")
                .eq("user_id", user_id)
                .eq("exchange", exchange)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error checking credential existence for user=%s exchange=%s: %s",
                user_id,
                exchange,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        rows: list[dict[str, Any]] = check_resp.data if check_resp.data else []
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"No credentials found for exchange '{exchange}'",
            )

        # Perform the delete
        try:
            self._supabase.table("exchange_credentials").delete().eq(
                "user_id", user_id
            ).eq("exchange", exchange).execute()
        except Exception as exc:
            logger.error(
                "Database error deleting credentials for user=%s exchange=%s: %s",
                user_id,
                exchange,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        return {"message": "Credentials removed"}


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _to_credential_summary(row: dict[str, Any]) -> CredentialSummaryResponse:
    """Convert a raw ``exchange_credentials`` row dict into a
    :class:`~..user_models.CredentialSummaryResponse`.

    Only ``exchange`` and ``created_at`` are read from *row*; key/secret
    fields are deliberately ignored even if present (Requirement 12.2).
    """
    return CredentialSummaryResponse(
        exchange=row["exchange"],
        is_configured=True,
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
