"""Trade audit logger for the TradingView webhook trading module.

Records every trade execution attempt to the ``trade_logs`` table in Supabase,
providing a complete audit trail per Requirements 8.1–8.5.

Key behaviours:
- Every call to ``log_trade`` persists a record *before* the webhook response
  is returned (Requirement 8.4).
- ``error_details`` is silently truncated to at most 1 024 characters before
  storage (Requirement 8.2).
- On a database write failure the write is retried exactly once.  If the retry
  also fails the exception is re-raised so the calling router can return HTTP
  500 (Requirement 8.5).
- The ``created_at`` timestamp is generated in the logger itself as an ISO 8601
  UTC string (Requirement 8.1).
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Maximum length (in characters) for the error_details column (Requirement 8.2)
_ERROR_DETAILS_MAX_LEN = 1024


class TradeLogger:
    """Persists trade audit records to the ``trade_logs`` Supabase table.

    Args:
        supabase: A Supabase client instance (sync or async).  The same style
            of synchronous chained-query client used elsewhere in the module
            (e.g. ``auth.py``) is expected.
    """

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def log_trade(
        self,
        user_id: str,
        symbol: str,
        action: str,
        side: str,
        exchange: str,
        size_value: float,
        status: str,
        order_id: str | None = None,
        fill_price: float | None = None,
        filled_quantity: float | None = None,
        error_details: str | None = None,
    ) -> dict:
        """Record a single trade attempt to the ``trade_logs`` table.

        The record is written synchronously (relative to the webhook request
        lifecycle) so that it is persisted before the HTTP response is
        returned (Requirement 8.4).

        On a transient database write failure the insert is retried once.
        If the retry also fails the exception propagates to the caller
        (Requirement 8.5), causing the webhook endpoint to return HTTP 500.

        Args:
            user_id: UUID of the authenticated user.
            symbol: CCXT unified symbol (e.g. ``"BTC/USDT:USDT"``).
            action: One of ``"open"`` or ``"close"``.
            side: One of ``"long"`` or ``"short"``.
            exchange: Exchange name (e.g. ``"binance"`` or ``"okx"``).
            size_value: The order size as provided in the payload.
            status: One of ``"success"``, ``"failed"``, or ``"rejected"``.
            order_id: Exchange-assigned order ID, or ``None`` when the order
                was never submitted.
            fill_price: Execution price from the exchange response, or
                ``None`` if the order was not filled.
            filled_quantity: Filled quantity from the exchange response, or
                ``None`` if the order was not filled.
            error_details: Human-readable error description.  Truncated to
                1 024 characters before storage (Requirement 8.2).

        Returns:
            The inserted row as returned by Supabase (a dict).

        Raises:
            Exception: Propagates the database exception if both the initial
                write and the single retry fail.
        """
        # Truncate error_details to at most 1024 characters (Requirement 8.2)
        if error_details is not None and len(error_details) > _ERROR_DETAILS_MAX_LEN:
            error_details = error_details[:_ERROR_DETAILS_MAX_LEN]

        # ISO 8601 UTC timestamp (Requirement 8.1)
        created_at = datetime.now(tz=timezone.utc).isoformat()

        record = {
            "user_id": user_id,
            "symbol": symbol,
            "action": action,
            "side": side,
            "exchange": exchange,
            "size_value": size_value,
            "status": status,
            "order_id": order_id,
            "fill_price": fill_price,
            "filled_quantity": filled_quantity,
            "error_details": error_details,
            "created_at": created_at,
        }

        return await self._insert_with_retry(record)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _insert_with_retry(self, record: dict) -> dict:
        """Attempt to insert *record* into ``trade_logs``, retrying once on failure.

        Args:
            record: The fully-formed row to insert.

        Returns:
            The inserted row dict from Supabase.

        Raises:
            Exception: Re-raises the exception from the second (retry) attempt
                if both attempts fail.
        """
        try:
            return self._do_insert(record)
        except Exception as first_exc:
            logger.warning(
                "Trade log write failed (attempt 1/2): %s — retrying…",
                first_exc,
            )

        # Single retry (Requirement 8.5)
        try:
            return self._do_insert(record)
        except Exception as second_exc:
            logger.error(
                "Trade log write failed after retry (attempt 2/2): %s",
                second_exc,
                exc_info=True,
            )
            raise

    def _do_insert(self, record: dict) -> dict:
        """Execute the actual Supabase insert and return the inserted row.

        Args:
            record: The row to insert.

        Returns:
            The first element of ``response.data`` (the inserted row as dict).

        Raises:
            Exception: Any exception raised by the Supabase client.
        """
        response = (
            self._supabase.table("trade_logs")
            .insert(record)
            .execute()
        )
        return response.data[0] if response.data else record
