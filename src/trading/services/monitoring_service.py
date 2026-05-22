"""Monitoring service for the Trading User Management API.

Open positions are fetched directly from the exchange (source of truth),
so they reflect all positions regardless of how they were opened — via
webhook, manually on the exchange UI, or any other method.

Closed position history and trade log entries are still read from Supabase
(audit trail written by the webhook pipeline).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..connector import AuthenticationError, TradingConnector
from ..credentials import CredentialStore, MissingCredentialsError
from ..user_models import ClosedPositionResponse, OpenPositionResponse, TradeLogResponse

logger = logging.getLogger(__name__)


class MonitoringService:
    """Handles querying of positions and trade log for a user.

    Args:
        supabase:         An initialised Supabase client.
        credential_store: A :class:`~..credentials.CredentialStore` instance
                          used to retrieve exchange API keys for the user.
        trading_connector: A :class:`~..connector.TradingConnector` instance
                           used to create authenticated exchange connections.
    """

    def __init__(
        self,
        supabase: Any,
        credential_store: CredentialStore,
        trading_connector: TradingConnector,
    ) -> None:
        self._supabase = supabase
        self._credential_store = credential_store
        self._trading_connector = trading_connector

    # ------------------------------------------------------------------
    # Open positions  (source of truth: exchange)
    # ------------------------------------------------------------------

    async def get_open_positions(self, user_id: str) -> list[OpenPositionResponse]:
        """Return all open positions for *user_id* by querying each configured exchange.

        Iterates over every exchange the user has credentials for, fetches
        live positions, and returns only those with a non-zero contract size.
        If an exchange connection fails the error is logged and that exchange
        is skipped — partial results are returned rather than a hard 503.

        Returns an empty list when no open positions exist on any exchange.

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            List of :class:`~..user_models.OpenPositionResponse` (may be empty).

        Raises:
            HTTPException(503): On unexpected Supabase errors when listing
                                configured exchanges.
        """
        # Discover which exchanges this user has credentials for.
        try:
            cred_response = (
                self._supabase.table("exchange_credentials")
                .select("exchange")
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "Database error listing exchange credentials for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail="Service unavailable") from exc

        configured_exchanges: list[str] = [
            row["exchange"] for row in (cred_response.data or [])
        ]

        if not configured_exchanges:
            return []

        results: list[OpenPositionResponse] = []

        for exchange_name in configured_exchanges:
            exchange_instance = None
            try:
                credentials = await self._credential_store.get_credentials(
                    user_id, exchange_name
                )
                exchange_instance = await self._trading_connector.create_exchange_for_monitoring(
                    exchange_name=exchange_name,
                    credentials=credentials,
                )
                raw_positions = await exchange_instance.fetch_positions()
            except MissingCredentialsError:
                logger.warning(
                    "No credentials found for user=%s exchange=%s — skipping",
                    user_id,
                    exchange_name,
                )
                continue
            except AuthenticationError as exc:
                logger.error(
                    "Auth error fetching positions for user=%s exchange=%s: %s",
                    user_id,
                    exchange_name,
                    exc,
                )
                continue
            except Exception as exc:
                logger.error(
                    "Error fetching positions for user=%s exchange=%s: %s",
                    user_id,
                    exchange_name,
                    exc,
                    exc_info=True,
                )
                continue
            finally:
                if exchange_instance is not None:
                    try:
                        await exchange_instance.close()
                    except Exception:
                        pass

            for pos in raw_positions:
                contracts = pos.get("contracts") or pos.get("size") or 0
                try:
                    contracts = float(contracts)
                except (TypeError, ValueError):
                    contracts = 0.0

                if contracts <= 0:
                    continue

                results.append(_ccxt_position_to_response(pos, exchange_name))

        return results

    # ------------------------------------------------------------------
    # Position history  (source: Supabase audit trail)
    # ------------------------------------------------------------------

    async def get_position_history(self, user_id: str) -> list[ClosedPositionResponse]:
        """Return all closed positions for *user_id* ordered by ``closed_at`` DESC.

        Reads from the Supabase audit trail — records positions that were
        closed via this application's webhook pipeline.

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
    # Trade log  (source: Supabase audit trail)
    # ------------------------------------------------------------------

    async def get_trade_log(self, user_id: str) -> list[TradeLogResponse]:
        """Return all trade log entries for *user_id* ordered by ``created_at`` DESC.

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


def _ccxt_position_to_response(
    pos: dict[str, Any],
    exchange_name: str,
) -> OpenPositionResponse:
    """Convert a raw CCXT position dict to an :class:`OpenPositionResponse`."""
    side_raw = str(pos.get("side") or "long").lower()
    side = "long" if side_raw == "long" else "short"

    entry_price = _safe_float(pos.get("entryPrice") or pos.get("entry_price"))
    quantity = _safe_float(pos.get("contracts") or pos.get("size"))
    mark_price = _safe_float(pos.get("markPrice") or pos.get("mark_price"))
    unrealized_pnl = _safe_float(pos.get("unrealizedPnl") or pos.get("unrealized_pnl"))
    liquidation_price = _safe_float(
        pos.get("liquidationPrice") or pos.get("liquidation_price")
    )
    leverage = _safe_float(pos.get("leverage"))

    # Calculate unrealized PnL percentage when possible
    unrealized_pnl_pct: float | None = None
    if (
        unrealized_pnl is not None
        and entry_price is not None
        and entry_price > 0
        and quantity is not None
        and quantity > 0
    ):
        cost_basis = entry_price * quantity
        unrealized_pnl_pct = round((unrealized_pnl / cost_basis) * 100, 4)

    return OpenPositionResponse(
        symbol=str(pos.get("symbol", "")),
        side=side,
        entry_price=entry_price or 0.0,
        quantity=quantity or 0.0,
        exchange=exchange_name,
        mark_price=mark_price,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        liquidation_price=liquidation_price,
        leverage=leverage,
    )


def _safe_float(value: Any) -> float | None:
    """Convert *value* to float, returning ``None`` on failure or zero."""
    if value is None:
        return None
    try:
        result = float(value)
        return result if result != 0.0 else None
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: Any) -> datetime:
    """Parse an ISO 8601 timestamp string to a UTC-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _to_closed_position_response(row: dict[str, Any]) -> ClosedPositionResponse:
    """Convert a Supabase positions row to a :class:`ClosedPositionResponse`."""
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
    """Convert a Supabase trade_logs row to a :class:`TradeLogResponse`."""
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
