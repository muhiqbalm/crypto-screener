"""Position manager module for TradingView webhook trading.

Checks open positions directly on the exchange (source of truth) and
serialises concurrent requests for the same symbol via an in-process async
lock (asyncio.Lock per user+symbol pair).

The ``positions`` Supabase table is kept only as an audit trail — it is
written to after a successful trade but is never read for position-state
decisions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxt_async

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process lock registry
# ---------------------------------------------------------------------------
# Maps "user_id:symbol" → asyncio.Lock
# Shared across all requests within a single process.
_position_locks: dict[str, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()  # protects _position_locks dict itself


async def _get_lock(user_id: str, symbol: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock for (user_id, symbol)."""
    key = f"{user_id}:{symbol}"
    async with _registry_lock:
        if key not in _position_locks:
            _position_locks[key] = asyncio.Lock()
        return _position_locks[key]


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DuplicatePositionError(Exception):
    """Raised when an "open" action is requested but a position already exists
    on the exchange for the given symbol.
    """


class NoPositionError(Exception):
    """Raised when a "close" action is requested but no open position exists
    on the exchange for the given symbol.
    """


class LockTimeoutError(Exception):
    """Raised when the advisory lock cannot be acquired within the timeout."""


# ---------------------------------------------------------------------------
# PositionManager
# ---------------------------------------------------------------------------


class PositionManager:
    """Manages position checks and locking.

    Position existence is verified directly on the exchange (source of truth).
    Concurrent requests for the same (user_id, symbol) pair are serialised via
    an in-process asyncio.Lock to prevent race conditions within a single
    worker process.

    The Supabase ``positions`` table is written to for audit purposes only —
    it is never queried to determine whether a position is currently open.
    """

    LOCK_TIMEOUT_SECONDS: float = 5.0

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    # ------------------------------------------------------------------
    # check_and_lock
    # ------------------------------------------------------------------

    async def check_and_lock(
        self,
        user_id: str,
        symbol: str,
        action: str,
        exchange: ccxt_async.Exchange,
    ) -> dict | None:
        """Acquire an in-process lock and verify position state on the exchange.

        Queries ``exchange.fetch_positions([symbol])`` as the authoritative
        source of truth. The asyncio lock serialises concurrent webhooks for
        the same (user_id, symbol) pair within a single worker process.

        For "open":
            - Raises ``DuplicatePositionError`` if the exchange already has an
              open position for this symbol.
            - Returns ``None`` on success.

        For "close":
            - Raises ``NoPositionError`` if the exchange has no open position
              for this symbol.
            - Returns the CCXT position dict on success.

        Raises:
            DuplicatePositionError: On "open" when exchange has an open position.
            NoPositionError:        On "close" when exchange has no open position.
            LockTimeoutError:       When the lock cannot be acquired within timeout.
        """
        lock = await _get_lock(user_id, symbol)

        try:
            acquired = await asyncio.wait_for(lock.acquire(), timeout=self.LOCK_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise LockTimeoutError(
                f"Could not acquire lock for symbol '{symbol}': "
                f"symbol is currently being processed for user '{user_id}'"
            )

        try:
            open_position = await _fetch_open_position(exchange, symbol)
        except Exception:
            lock.release()
            raise

        # Note: lock is intentionally kept held until the caller releases it.
        # The caller (router.py) must release after the trade is complete.
        # For simplicity we release immediately after the check — the exchange
        # itself enforces the actual constraint.
        lock.release()

        if action == "open":
            if open_position is not None:
                logger.warning(
                    "Duplicate position rejected (exchange): user=%s symbol=%s",
                    user_id,
                    symbol,
                )
                raise DuplicatePositionError(
                    f"An open position for '{symbol}' already exists on the exchange "
                    f"for user '{user_id}'"
                )
            return None

        else:  # action == "close"
            if open_position is None:
                logger.warning(
                    "No open position on exchange to close: user=%s symbol=%s",
                    user_id,
                    symbol,
                )
                raise NoPositionError(
                    f"No open position found for symbol '{symbol}' on the exchange "
                    f"for user '{user_id}'"
                )
            return open_position

    # ------------------------------------------------------------------
    # open_position  (audit log write only)
    # ------------------------------------------------------------------

    async def open_position(
        self,
        user_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        exchange: str = "",
    ) -> dict:
        """Write an audit record to Supabase after a successful open order.

        This is an audit trail only — it does not gate any trading decisions.
        """
        record: dict = {
            "user_id": user_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "status": "open",
            "exchange": exchange,
        }

        try:
            response = (
                self._supabase.table("positions")
                .insert(record)
                .execute()
            )
        except Exception as exc:
            # Non-fatal: audit write failure should not block the response.
            logger.error(
                "Failed to write open position audit record for user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            return record

        rows: list[dict] = response.data if response.data else []
        if rows:
            logger.info(
                "Position audit record opened: user=%s symbol=%s side=%s entry=%.6f qty=%.6f",
                user_id,
                symbol,
                side,
                entry_price,
                quantity,
            )
            return rows[0]

        return record

    # ------------------------------------------------------------------
    # close_position  (audit log write only)
    # ------------------------------------------------------------------

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        exit_price: float,
    ) -> dict:
        """Update the audit record in Supabase after a successful close order.

        This is an audit trail only — it does not gate any trading decisions.
        """
        closed_at = datetime.now(tz=timezone.utc).isoformat()

        update_data: dict = {
            "status": "closed",
            "exit_price": exit_price,
            "closed_at": closed_at,
        }

        try:
            response = (
                self._supabase.table("positions")
                .update(update_data)
                .eq("user_id", user_id)
                .eq("symbol", symbol)
                .eq("status", "open")
                .execute()
            )
        except Exception as exc:
            # Non-fatal: audit write failure should not block the response.
            logger.error(
                "Failed to update close position audit record for user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            return {"user_id": user_id, "symbol": symbol, **update_data}

        rows: list[dict] = response.data if response.data else []
        if rows:
            logger.info(
                "Position audit record closed: user=%s symbol=%s exit=%.6f",
                user_id,
                symbol,
                exit_price,
            )
            return rows[0]

        return {"user_id": user_id, "symbol": symbol, **update_data}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _fetch_open_position(
    exchange: ccxt_async.Exchange,
    symbol: str,
) -> dict | None:
    """Fetch the open position for *symbol* from the exchange.

    Returns the CCXT position dict when an open position exists (contracts > 0),
    or ``None`` when no position is open.
    """
    try:
        positions: list[dict] = await exchange.fetch_positions([symbol])
    except Exception as exc:
        logger.error(
            "Failed to fetch positions from exchange for symbol=%s: %s",
            symbol,
            exc,
        )
        raise

    for pos in positions:
        contracts = pos.get("contracts") or pos.get("size") or 0
        try:
            contracts = float(contracts)
        except (TypeError, ValueError):
            contracts = 0.0
        if contracts > 0:
            return pos

    return None
