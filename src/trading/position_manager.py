"""Position manager module for TradingView webhook trading.

Tracks open positions per user per symbol, enforces the one-position-per-symbol-per-user
constraint, and serialises concurrent requests via PostgreSQL advisory locks.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.2, 9.4
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DuplicatePositionError(Exception):
    """Raised when an "open" action is requested but a position already exists.

    Requirement 6.2: If an "open" action is received and the user already has
    an open position for the same symbol, the Position_Manager SHALL reject the
    trade with a duplicate position error before any order is placed.
    """


class NoPositionError(Exception):
    """Raised when a "close" action is requested but no open position exists.

    Requirement 6.3: If a "close" action is received and no open position exists
    for the symbol, the Position_Manager SHALL reject the trade with a
    no-position-found error before any order is placed.
    """


class LockTimeoutError(Exception):
    """Raised when the advisory lock cannot be acquired within the timeout.

    Requirement 9.4: If the Position_Manager cannot acquire the database lock
    within the 5-second timeout, the trade SHALL be rejected with a conflict
    error.
    """


# ---------------------------------------------------------------------------
# Helper: deterministic 32-bit lock key
# ---------------------------------------------------------------------------


def _lock_key(user_id: str, symbol: str) -> int:
    """Produce a stable 32-bit integer advisory lock key for (user_id, symbol).

    Uses the first 4 bytes of the SHA-256 digest of the concatenated string
    ``"{user_id}:{symbol}"`` to spread keys uniformly while keeping them
    within the PostgreSQL bigint range accepted by ``pg_advisory_xact_lock``.

    The result fits in a signed 32-bit integer (value in [0, 2**31-1]) so that
    ``pg_advisory_xact_lock(key)`` works without overflow.
    """
    raw = f"{user_id}:{symbol}".encode()
    digest = hashlib.sha256(raw).digest()
    # Interpret first 4 bytes as unsigned int, then mask to signed 32-bit range.
    unsigned = int.from_bytes(digest[:4], byteorder="big")
    return unsigned & 0x7FFFFFFF


# ---------------------------------------------------------------------------
# PositionManager
# ---------------------------------------------------------------------------


class PositionManager:
    """Manages open positions, advisory locking, and position lifecycle.

    Each public method interacts with the Supabase-backed ``positions`` table.
    Concurrent requests for the same (user_id, symbol) pair are serialised via
    PostgreSQL ``pg_advisory_xact_lock`` so that the check-then-act sequence is
    atomic at the database level.

    Requirements: 6.1–6.6, 9.2, 9.4
    """

    # Timeout in milliseconds for statement_timeout (lock acquisition).
    # Corresponds to lock_timeout_seconds = 5 from TradingSettings.
    LOCK_TIMEOUT_MS: int = 5000

    def __init__(self, supabase: Any) -> None:
        """Initialise the manager.

        Args:
            supabase: A Supabase client instance (sync or async).
                      The client must expose ``.rpc()`` and ``.table()`` methods.
        """
        self._supabase = supabase

    # ------------------------------------------------------------------
    # check_and_lock
    # ------------------------------------------------------------------

    async def check_and_lock(
        self,
        user_id: str,
        symbol: str,
        action: str,
    ) -> dict | None:
        """Acquire an advisory lock for (user_id, symbol) and validate the action.

        The lock is scoped to the current database transaction via
        ``pg_advisory_xact_lock``.  Before acquiring the lock the session's
        ``statement_timeout`` is set to ``LOCK_TIMEOUT_MS`` milliseconds so that
        the lock attempt itself fails fast when another session holds the lock.

        For "open":
            - Checks that *no* open position already exists.
            - Returns ``None`` on success.
            - Raises ``DuplicatePositionError`` if a position is found.

        For "close":
            - Checks that an open position *does* exist.
            - Returns the position record dict on success.
            - Raises ``NoPositionError`` if no position is found.

        Raises:
            DuplicatePositionError: On "open" when a position already exists.
            NoPositionError:        On "close" when no open position exists.
            LockTimeoutError:       When the advisory lock cannot be acquired
                                    within LOCK_TIMEOUT_MS milliseconds.

        Requirements: 6.1, 6.2, 6.3, 9.2, 9.4
        """
        lock_key = _lock_key(user_id, symbol)

        # Set statement_timeout so the lock acquisition fails fast.
        # Requirement 9.2: 5-second lock wait timeout.
        try:
            self._supabase.rpc(
                "set_config",
                {
                    "setting": "statement_timeout",
                    "value": str(self.LOCK_TIMEOUT_MS),
                },
            ).execute()
        except Exception as exc:
            logger.warning(
                "Could not set statement_timeout before advisory lock: %s", exc
            )
            # Non-fatal — proceed with default timeout.

        # Acquire transaction-scoped advisory lock.
        # Requirement 9.2: pg_advisory_xact_lock serialises concurrent requests.
        try:
            self._supabase.rpc(
                "pg_advisory_xact_lock",
                {"key": lock_key},
            ).execute()
        except Exception as exc:
            error_str = str(exc).lower()
            if "timeout" in error_str or "canceling" in error_str or "statement" in error_str:
                logger.warning(
                    "Advisory lock timeout for user=%s symbol=%s: %s",
                    user_id,
                    symbol,
                    exc,
                )
                raise LockTimeoutError(
                    f"Could not acquire lock for symbol '{symbol}': "
                    f"symbol is currently being processed for user '{user_id}'"
                ) from exc
            logger.error(
                "Unexpected error acquiring advisory lock user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            raise LockTimeoutError(
                f"Lock acquisition failed for symbol '{symbol}': {exc}"
            ) from exc

        # Query for an existing open position.
        try:
            response = (
                self._supabase.table("positions")
                .select("id, user_id, symbol, side, entry_price, quantity, status, opened_at")
                .eq("user_id", user_id)
                .eq("symbol", symbol)
                .eq("status", "open")
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error querying positions for user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            raise

        rows: list[dict] = response.data if response.data else []

        if action == "open":
            # Requirement 6.1, 6.2: reject duplicate open positions.
            if rows:
                existing = rows[0]
                logger.warning(
                    "Duplicate position rejected: user=%s symbol=%s existing_id=%s",
                    user_id,
                    symbol,
                    existing.get("id"),
                )
                raise DuplicatePositionError(
                    f"User '{user_id}' already has an open position for symbol '{symbol}'"
                )
            return None

        else:  # action == "close"
            # Requirement 6.3: reject close when no open position exists.
            if not rows:
                logger.warning(
                    "No open position to close: user=%s symbol=%s",
                    user_id,
                    symbol,
                )
                raise NoPositionError(
                    f"No open position found for symbol '{symbol}' and user '{user_id}'"
                )
            return rows[0]

    # ------------------------------------------------------------------
    # open_position
    # ------------------------------------------------------------------

    async def open_position(
        self,
        user_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
    ) -> dict:
        """Create a position record after a successful open order fill.

        Only the *actual filled quantity* from the exchange response should be
        supplied — partial fills are recorded as-is (Requirement 6.6).

        Args:
            user_id:     UUID string of the owning user.
            symbol:      CCXT unified symbol (e.g., "BTC/USDT:USDT").
            side:        "long" or "short".
            entry_price: Fill price from the exchange order response.
            quantity:    Filled quantity from the exchange order response.

        Returns:
            The newly inserted position record dict.

        Requirements: 6.4, 6.6
        """
        record: dict = {
            "user_id": user_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "status": "open",
        }

        try:
            response = (
                self._supabase.table("positions")
                .insert(record)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Failed to create position record for user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            raise

        rows: list[dict] = response.data if response.data else []
        if rows:
            position = rows[0]
            logger.info(
                "Position opened: id=%s user=%s symbol=%s side=%s entry=%.6f qty=%.6f",
                position.get("id"),
                user_id,
                symbol,
                side,
                entry_price,
                quantity,
            )
            return position

        # Fallback: return the record we attempted to insert (no server-generated id).
        logger.warning(
            "Position insert returned no rows for user=%s symbol=%s — returning input record",
            user_id,
            symbol,
        )
        return record

    # ------------------------------------------------------------------
    # close_position
    # ------------------------------------------------------------------

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        exit_price: float,
    ) -> dict:
        """Mark an open position as closed with the given exit price.

        Sets ``status = 'closed'``, records ``exit_price``, and stamps
        ``closed_at`` with the current UTC timestamp (ISO 8601).

        Only the *actual filled quantity* from the exchange response was used
        to place the closing order — this method reflects whatever quantity was
        recorded when the position was opened (Requirement 6.6).

        Args:
            user_id:    UUID string of the owning user.
            symbol:     CCXT unified symbol (e.g., "BTC/USDT:USDT").
            exit_price: Fill price from the exchange close-order response.

        Returns:
            The updated position record dict.

        Requirements: 6.5, 6.6
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
            logger.error(
                "Failed to close position record for user=%s symbol=%s: %s",
                user_id,
                symbol,
                exc,
            )
            raise

        rows: list[dict] = response.data if response.data else []
        if rows:
            position = rows[0]
            logger.info(
                "Position closed: id=%s user=%s symbol=%s exit=%.6f",
                position.get("id"),
                user_id,
                symbol,
                exit_price,
            )
            return position

        # Fallback: return a minimal record when the update response is empty.
        logger.warning(
            "Position close update returned no rows for user=%s symbol=%s — "
            "returning update data",
            user_id,
            symbol,
        )
        return {
            "user_id": user_id,
            "symbol": symbol,
            **update_data,
        }
