"""Position manager module for TradingView webhook trading.

Checks open positions directly on the exchange (source of truth) and
serialises concurrent requests for the same symbol via an in-process async
lock (asyncio.Lock per user+symbol pair).

The ``positions`` table records what the bot itself opened. A "close" is
executed only when such a record exists (``get_open_record``), so a failed
write of that record is retried and then raised, never swallowed.
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


class PositionRecordError(Exception):
    """Raised when a position record could not be written after a retry.

    The order behind it is already filled, so the caller must alert a human:
    closes depend on this record (see ``get_open_record``).
    """


# ---------------------------------------------------------------------------
# PositionManager
# ---------------------------------------------------------------------------


class PositionManager:
    """Manages position checks and locking.

    Position existence is verified directly on the exchange (source of truth).
    Concurrent requests for the same (user_id, symbol) pair are serialised via
    an in-process asyncio.Lock to prevent race conditions within a single
    worker process.

    Whether a position is open is always decided by the exchange. The
    ``positions`` table decides whether the bot opened it (closes are limited
    to bot-opened positions).
    """

    LOCK_TIMEOUT_SECONDS: float = 5.0
    # Checks after an open order got no answer: wait, then ask the exchange.
    # Worst case 3 x (wait + 4 s) = 18 s, inside the 30 s shutdown drain.
    OPEN_CONFIRM_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 3.0)
    OPEN_CONFIRM_CALL_TIMEOUT_SECONDS: float = 4.0
    # One retry, like TradeLogger. The local SQLite client blocks for up to
    # 10 s per attempt on a locked file, so more attempts would stall the app.
    RECORD_WRITE_ATTEMPTS: int = 2
    RECORD_RETRY_DELAY_SECONDS: float = 0.5

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

        # On success the lock stays held so that the order cannot race another
        # webhook; the caller must call release_lock() once the order is done.
        try:
            open_position = await _fetch_open_position(exchange, symbol)
        except Exception:
            lock.release()
            raise

        if action == "open":
            if open_position is not None:
                lock.release()
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
                lock.release()
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

    async def confirm_unanswered_open(
        self,
        exchange: ccxt_async.Exchange,
        symbol: str,
        side: str,
    ) -> tuple[str, dict | None, str]:
        """Ask the exchange whether an open order that got no answer was filled.

        Call only while the lock from ``check_and_lock("open")`` is still held:
        that check saw no position, so a position that appears now comes from
        the order that was just sent. The order itself is never sent again.

        Returns ``(outcome, position, note)`` where outcome is
          * ``"filled"``  - the exchange shows the position (returned);
          * ``"flat"``    - every check answered and the last one showed no position;
          * ``"unknown"`` - the exchange could not be read, or shows the other side.
        """
        note = "the exchange was not checked"
        for delay in self.OPEN_CONFIRM_DELAYS_SECONDS:
            await asyncio.sleep(delay)
            try:
                position = await asyncio.wait_for(
                    _fetch_open_position(exchange, symbol),
                    timeout=self.OPEN_CONFIRM_CALL_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                note = f"the position check failed ({exc!r})"
                continue
            if position is None:
                note = ""
                continue
            position_side = str(position.get("side") or "").lower()
            if position_side and position_side != side:
                return "unknown", None, f"the exchange shows a {position_side} position"
            return "filled", position, ""
        return ("unknown", None, note) if note else ("flat", None, "")

    def release_lock(self, user_id: str, symbol: str) -> None:
        """Release the lock left held by a successful check_and_lock()."""
        lock = _position_locks.get(f"{user_id}:{symbol}")
        if lock is not None and lock.locked():
            lock.release()

    # ------------------------------------------------------------------
    # Bot-owned position records
    # ------------------------------------------------------------------

    def get_open_record(self, user_id: str, symbol: str) -> dict | None:
        """Return the newest open position the bot itself recorded, or None.

        Closes are limited to what the bot opened so that a manual position on
        the same account is never closed by a strategy signal.
        """
        response = (
            self._supabase.table("positions")
            .select("*")
            .eq("user_id", user_id)
            .eq("symbol", symbol)
            .eq("status", "open")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def mark_missing(self, user_id: str, symbol: str) -> None:
        """Mark open records as gone when the exchange no longer holds them."""
        try:
            (
                self._supabase.table("positions")
                .update({
                    "status": "missing",
                    "closed_at": datetime.now(tz=timezone.utc).isoformat(),
                })
                .eq("user_id", user_id)
                .eq("symbol", symbol)
                .eq("status", "open")
                .execute()
            )
        except Exception as exc:
            logger.error("Failed to mark missing position user=%s symbol=%s: %s", user_id, symbol, exc)

    async def _write_record(self, write: Any, what: str, user_id: str, symbol: str) -> Any:
        """Run a position-record write, retrying briefly; raise if it keeps failing."""
        last_exc: Exception | None = None
        for attempt in range(1, self.RECORD_WRITE_ATTEMPTS + 1):
            try:
                return write()
            except Exception as exc:
                last_exc = exc
                logger.error(
                    "Failed to %s position record for user=%s symbol=%s (attempt %d/%d): %s",
                    what,
                    user_id,
                    symbol,
                    attempt,
                    self.RECORD_WRITE_ATTEMPTS,
                    exc,
                )
                if attempt < self.RECORD_WRITE_ATTEMPTS:
                    await asyncio.sleep(self.RECORD_RETRY_DELAY_SECONDS)
        raise PositionRecordError(
            f"could not {what} the position record after "
            f"{self.RECORD_WRITE_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

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
        exchange: str = "",
    ) -> dict:
        """Write the position record after a successful open order.

        A later "close" is only executed when this record exists, so a write
        that still fails after a retry raises ``PositionRecordError``.
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

        response = await self._write_record(
            lambda: self._supabase.table("positions").insert(record).execute(),
            "write",
            user_id,
            symbol,
        )

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
    # close_position
    # ------------------------------------------------------------------

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        exit_price: float,
    ) -> dict:
        """Mark the position record closed after a successful close order.

        A record left "open" would let a later close signal act on a position
        the bot no longer owns, so a write that still fails after a retry
        raises ``PositionRecordError``.
        """
        closed_at = datetime.now(tz=timezone.utc).isoformat()

        update_data: dict = {
            "status": "closed",
            "exit_price": exit_price,
            "closed_at": closed_at,
        }

        response = await self._write_record(
            lambda: (
                self._supabase.table("positions")
                .update(update_data)
                .eq("user_id", user_id)
                .eq("symbol", symbol)
                .eq("status", "open")
                .execute()
            ),
            "close",
            user_id,
            symbol,
        )

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
