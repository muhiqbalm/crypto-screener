"""Monitoring service for the Trading User Management API.

Provides :class:`MonitoringService` which implements querying open positions,
closed position history, and trade log entries for an authenticated user.

Design decisions:
- ``get_open_positions`` queries positions where ``status = 'open'`` (or
  equivalent) for the given user and returns an empty list when none exist
  (Requirement 15.2).
- ``get_position_history`` queries closed positions ordered by ``closed_at``
  descending so the most recent close appears first (Requirements 16.1, 16.3).
- ``get_trade_log`` queries the trade log ordered by ``created_at`` descending
  so the most recent entry appears first (Requirements 17.1, 17.3).
- All three methods return an empty list (never 404) when there are no records
  for the user (Requirements 15.2, 16.2, 17.2).

Requirements: 15.1, 15.2, 16.1, 16.2, 16.3, 17.1, 17.2, 17.3
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..user_models import ClosedPositionResponse, OpenPositionResponse, TradeLogResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MonitoringService
# ---------------------------------------------------------------------------


class MonitoringService:
    """Handles querying of positions and trade log for a user.

    Args:
        supabase: An initialised Supabase client (``supabase-py``).
    """

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    # ------------------------------------------------------------------
    # Open positions
    # ------------------------------------------------------------------

    async def get_open_positions(self, user_id: str) -> list[OpenPositionResponse]:
        """Return all open positions for *user_id*.

        Queries the ``positions`` table for rows belonging to *user_id* that
        have not yet been closed (i.e. ``status = 'open'`` or ``closed_at``
        is NULL).  Returns an empty list when no open positions exist
        (Requirement 15.2).

        Each returned record contains: ``id``, ``symbol``, ``side``,
        ``entry_price``, ``quantity``, ``opened_at``, and ``exchange``
        (Requirement 15.1).

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            List of :class:`~..user_models.OpenPositionResponse` (may be empty).

        Raises:
            HTTPException(503): On unexpected database errors.
        """
        try:
            response = (
                self._supabase.table("positions")
                .select("id, symbol, side, entry_price, quantity, opened_at, exchange")
                .eq("user_id", user_id)
                .is_("closed_at", "null")
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching open positions for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            return []

        return [_to_open_position_response(row) for row in response.data]

    # ------------------------------------------------------------------
    # Position history
    # ------------------------------------------------------------------

    async def get_position_history(self, user_id: str) -> list[ClosedPositionResponse]:
        """Return all closed positions for *user_id* ordered by ``closed_at`` DESC.

        Queries the ``positions`` table for rows belonging to *user_id* that
        have a non-NULL ``closed_at`` value, ordering by ``closed_at``
        descending so the most recently closed position appears first
        (Requirements 16.1, 16.3).  Returns an empty list when no closed
        positions exist (Requirement 16.2).

        Each returned record contains: ``id``, ``symbol``, ``side``,
        ``entry_price``, ``exit_price``, ``quantity``, ``opened_at``,
        ``closed_at``, and ``exchange`` (Requirement 16.1).

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            List of :class:`~..user_models.ClosedPositionResponse` ordered by
            ``closed_at`` descending (may be empty).

        Raises:
            HTTPException(503): On unexpected database errors.
        """
        try:
            response = (
                self._supabase.table("positions")
                .select(
                    "id, symbol, side, entry_price, exit_price, "
                    "quantity, opened_at, closed_at, exchange"
                )
                .eq("user_id", user_id)
                .not_.is_("closed_at", "null")
                .order("closed_at", desc=True)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching position history for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            return []

        return [_to_closed_position_response(row) for row in response.data]

    # ------------------------------------------------------------------
    # Trade log
    # ------------------------------------------------------------------

    async def get_trade_log(self, user_id: str) -> list[TradeLogResponse]:
        """Return all trade log entries for *user_id* ordered by ``created_at`` DESC.

        Queries the ``trade_logs`` table for all rows belonging to *user_id*,
        ordering by ``created_at`` descending so the most recent trade appears
        first (Requirements 17.1, 17.3).  Returns an empty list when no
        entries exist (Requirement 17.2).

        Each returned record contains: ``id``, ``symbol``, ``action``,
        ``side``, ``exchange``, ``size_value``, ``status``, ``order_id``,
        ``fill_price``, ``filled_quantity``, ``error_details``, and
        ``created_at`` (Requirement 17.1).

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            List of :class:`~..user_models.TradeLogResponse` ordered by
            ``created_at`` descending (may be empty).

        Raises:
            HTTPException(503): On unexpected database errors.
        """
        try:
            response = (
                self._supabase.table("trade_logs")
                .select(
                    "id, symbol, action, side, exchange, size_value, "
                    "status, order_id, fill_price, filled_quantity, "
                    "error_details, created_at"
                )
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error fetching trade log for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        if not response.data:
            return []

        return [_to_trade_log_response(row) for row in response.data]


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


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


def _to_open_position_response(row: dict[str, Any]) -> OpenPositionResponse:
    """Convert a raw ``positions`` table row dict to an :class:`OpenPositionResponse`."""
    return OpenPositionResponse(
        id=str(row["id"]),
        symbol=str(row["symbol"]),
        side=str(row["side"]),
        entry_price=float(row["entry_price"]),
        quantity=float(row["quantity"]),
        opened_at=_parse_iso_datetime(row["opened_at"]),
        exchange=str(row["exchange"]),
    )


def _to_closed_position_response(row: dict[str, Any]) -> ClosedPositionResponse:
    """Convert a raw ``positions`` table row dict to a :class:`ClosedPositionResponse`."""
    return ClosedPositionResponse(
        id=str(row["id"]),
        symbol=str(row["symbol"]),
        side=str(row["side"]),
        entry_price=float(row["entry_price"]),
        exit_price=float(row["exit_price"]),
        quantity=float(row["quantity"]),
        opened_at=_parse_iso_datetime(row["opened_at"]),
        closed_at=_parse_iso_datetime(row["closed_at"]),
        exchange=str(row["exchange"]),
    )


def _to_trade_log_response(row: dict[str, Any]) -> TradeLogResponse:
    """Convert a raw ``trade_logs`` table row dict to a :class:`TradeLogResponse`."""
    return TradeLogResponse(
        id=str(row["id"]),
        symbol=str(row["symbol"]),
        action=str(row["action"]),
        side=str(row["side"]),
        exchange=str(row["exchange"]),
        size_value=float(row["size_value"]),
        status=str(row["status"]),
        order_id=str(row["order_id"]) if row.get("order_id") is not None else None,
        fill_price=float(row["fill_price"]) if row.get("fill_price") is not None else None,
        filled_quantity=(
            float(row["filled_quantity"])
            if row.get("filled_quantity") is not None
            else None
        ),
        error_details=(
            str(row["error_details"]) if row.get("error_details") is not None else None
        ),
        created_at=_parse_iso_datetime(row["created_at"]),
    )
