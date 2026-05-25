"""Trade executor module for TradingView webhook trading.

Handles quantity calculation and market order submission to exchanges
via CCXT async support.
"""

import asyncio
import logging

import ccxt.async_support as ccxt_async

from .models import WebhookPayload

logger = logging.getLogger(__name__)


class InsufficientBalanceError(Exception):
    """Raised when the user's free margin balance is too low to place the order."""

    def __init__(self, message: str, balance_info: dict | None = None):
        super().__init__(message)
        self.balance_info = balance_info


class OrderExecutionError(Exception):
    """Raised when the exchange returns an error during order placement."""

    def __init__(self, message: str, balance_info: dict | None = None):
        super().__init__(message)
        self.balance_info = balance_info


class TradeExecutor:
    """Executes market orders on exchanges via CCXT.

    Responsible for:
    - Calculating order quantities from percent-of-balance or fixed values
    - Checking free margin before placing orders
    - Submitting market orders within the configured timeout
    - Raising typed errors for balance and exchange failures

    Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
    """

    # Timeout in seconds for order submission (Requirement 5.8)
    ORDER_TIMEOUT_SECONDS: int = 5

    def calculate_quantity(
        self,
        size_type: str,
        size_value: float,
        free_balance: float,
        current_price: float,
        leverage: int = 1,
    ) -> float:
        """Calculate order quantity in base currency units.

        For "percent" size_type:
            Uses free_balance as margin, applies leverage to get notional,
            then divides by price to get quantity.
            quantity = (free_balance * size_value/100 * leverage) / current_price

        For "fixed" size_type:
            quantity = size_value  (already in base currency units)

        Args:
            size_type:     "percent" or "fixed"
            size_value:    Percentage (0–100] or fixed quantity
            free_balance:  User's free margin balance in quote currency
            current_price: Current market price in quote currency
            leverage:      Leverage multiplier (default 1)

        Returns:
            Order quantity in base currency units
        """
        if size_type == "percent":
            margin_used = free_balance * size_value / 100
            notional = margin_used * max(leverage, 1)
            return notional / current_price
        else:
            return size_value

    async def execute_trade(
        self,
        exchange: ccxt_async.Exchange,
        payload: WebhookPayload,
        position: dict | None = None,
    ) -> tuple[dict, dict]:
        """Execute a market order on the exchange based on the webhook payload.

        Returns:
            Tuple of (ccxt_order_dict, balance_info_dict) where balance_info contains:
              - free: free balance in quote currency
              - currency: quote currency symbol
              - min_order_amount: minimum order amount in base currency
              - min_order_notional: minimum notional value in quote currency (optional)
              - current_price: current market price
        """
        symbol = payload.symbol

        if payload.action == "close":
            return await self._execute_close(exchange, symbol, position)
        else:
            return await self._execute_open(exchange, payload)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_free_balance(
        self, exchange: ccxt_async.Exchange, symbol: str
    ) -> tuple[float, float, str]:
        """Fetch free margin balance, current price, and quote currency.

        Returns:
            Tuple of (free_balance, current_price, quote_currency)
        """
        try:
            quote_currency = symbol.split("/")[1].split(":")[0]

            exchange_id = exchange.id.lower()
            # Single fetch_balance() call: connector configures
            # defaultType="future", so this returns the futures/unified wallet
            # for both OKX and Binance. Sending {"type": "trading"} on OKX
            # Unified accounts can return an empty legacy wallet — see
            # monitoring_service.get_balance for the same fix.
            balance = await exchange.fetch_balance()

            logger.debug(
                "Raw balance response for %s: free=%s total=%s",
                exchange_id,
                balance.get("free", {}),
                balance.get("total", {}),
            )

            free_balance: float = float(
                balance.get("free", {}).get(quote_currency, 0.0) or 0.0
            )

            logger.info(
                "Free %s balance on %s: %s", quote_currency, exchange_id, free_balance
            )

            ticker = await exchange.fetch_ticker(symbol)
            current_price: float = float(ticker["last"])

            return free_balance, current_price, quote_currency

        except (ccxt_async.BaseError, KeyError, TypeError, ValueError) as exc:
            raise OrderExecutionError(
                f"Failed to fetch balance or price for {symbol}: {exc}"
            ) from exc

    def _get_balance_info(
        self,
        exchange: ccxt_async.Exchange,
        symbol: str,
        free_balance: float,
        current_price: float,
        quote_currency: str,
    ) -> dict:
        """Build balance_info dict to include in response."""
        min_amount = 0.0
        min_notional = None

        try:
            market = exchange.market(symbol)
            limits = market.get("limits") or {}
            min_amount = float((limits.get("amount") or {}).get("min") or 0.0)
            min_notional_raw = (limits.get("cost") or {}).get("min")
            if min_notional_raw:
                min_notional = float(min_notional_raw)
        except Exception:
            pass

        return {
            "free": free_balance,
            "currency": quote_currency,
            "min_order_amount": min_amount,
            "min_order_notional": min_notional,
            "current_price": current_price,
        }

    async def _execute_open(
        self, exchange: ccxt_async.Exchange, payload: WebhookPayload
    ) -> tuple[dict, dict]:
        """Handle 'open' action: calculate quantity, check balance, place order."""
        symbol = payload.symbol

        free_balance, current_price, quote_currency = await self._fetch_free_balance(exchange, symbol)
        balance_info = self._get_balance_info(exchange, symbol, free_balance, current_price, quote_currency)

        quantity = self.calculate_quantity(
            payload.size_type,
            payload.size_value,
            free_balance,
            current_price,
            leverage=payload.leverage or 1,
        )

        quantity = self._round_to_precision(exchange, symbol, quantity)

        # Enrich balance_info with order size details now that quantity is known
        leverage = payload.leverage or 1
        balance_info["order_quantity"] = quantity
        balance_info["order_notional"] = round(quantity * current_price, 6)
        balance_info["margin_required"] = round((quantity * current_price) / leverage, 6)

        try:
            self._validate_min_amount(exchange, symbol, quantity)
        except InsufficientBalanceError as exc:
            raise InsufficientBalanceError(str(exc), balance_info=balance_info) from exc

        margin_required = balance_info["margin_required"]
        if margin_required > free_balance:
            raise InsufficientBalanceError(
                f"Insufficient margin: required {margin_required:.4f} {quote_currency} "
                f"but free balance is {free_balance:.4f} {quote_currency} for {symbol}",
                balance_info=balance_info,
            )

        order_side = "buy" if payload.side == "long" else "sell"

        if exchange.id.lower() == "okx":
            try:
                await exchange.set_margin_mode("cross", symbol)
                logger.debug("Margin mode set to cross for %s", symbol)
            except Exception as e:
                logger.debug("set_margin_mode skipped for %s: %s", symbol, e)

        order = await self._place_order_with_timeout(
            exchange, symbol, order_side, quantity, balance_info=balance_info
        )
        return order, balance_info

    async def _execute_close(
        self,
        exchange: ccxt_async.Exchange,
        symbol: str,
        position: dict | None,
    ) -> tuple[dict, dict]:
        """Handle 'close' action: place opposite market order for full position size."""
        if position is None:
            raise ValueError(
                "A position record is required to close a trade, but none was provided."
            )

        position_side: str = position.get("side") or position.get("info", {}).get("posSide", "long")
        close_side = "sell" if str(position_side).lower() == "long" else "buy"

        quantity: float = float(
            position.get("contracts") or position.get("size") or position.get("quantity") or 0.0
        )

        quantity = self._round_to_precision(exchange, symbol, quantity)

        # Build balance info for close
        try:
            quote_currency = symbol.split("/")[1].split(":")[0]
            # See _fetch_free_balance — single fetch_balance() avoids the
            # OKX Unified/legacy mismatch.
            bal = await exchange.fetch_balance()
            free_balance = float(bal.get("free", {}).get(quote_currency, 0.0) or 0.0)
            ticker = await exchange.fetch_ticker(symbol)
            current_price = float(ticker["last"])
            quote_currency_used = quote_currency
        except Exception:
            free_balance, current_price, quote_currency_used = 0.0, 0.0, "USDT"

        balance_info = self._get_balance_info(
            exchange, symbol, free_balance, current_price, quote_currency_used
        )

        # Enrich with order size details
        balance_info["order_quantity"] = quantity
        balance_info["order_notional"] = round(quantity * current_price, 6) if current_price else None
        balance_info["margin_required"] = None  # close orders release margin

        try:
            self._validate_min_amount(exchange, symbol, quantity)
        except InsufficientBalanceError as exc:
            raise InsufficientBalanceError(str(exc), balance_info=balance_info) from exc

        order = await self._place_order_with_timeout(
            exchange, symbol, close_side, quantity, balance_info=balance_info
        )
        return order, balance_info

    @staticmethod
    def _round_to_precision(
        exchange: ccxt_async.Exchange,
        symbol: str,
        quantity: float,
    ) -> float:
        """Round quantity to the exchange's required amount precision.

        Uses CCXT's ``amount_to_precision`` when the market is loaded,
        falling back to 8 decimal places.
        """
        try:
            rounded = exchange.amount_to_precision(symbol, quantity)
            return float(rounded)
        except Exception:
            return round(quantity, 8)

    @staticmethod
    def _validate_min_amount(
        exchange: ccxt_async.Exchange,
        symbol: str,
        quantity: float,
    ) -> None:
        """Raise InsufficientBalanceError when quantity is below the exchange minimum.

        Reads the minimum amount from the loaded market data so the error
        message is actionable before the order is even submitted.
        """
        try:
            market = exchange.market(symbol)
            min_amount: float = float(
                (market.get("limits") or {}).get("amount", {}).get("min") or 0.0
            )
        except Exception:
            return  # Can't determine minimum — let the exchange reject it

        if min_amount > 0 and quantity < min_amount:
            raise InsufficientBalanceError(
                f"Order quantity {quantity} is below the minimum allowed "
                f"amount {min_amount} for {symbol}. "
                f"Increase size_value or use a higher balance."
            )

    async def _place_order_with_timeout(
        self,
        exchange: ccxt_async.Exchange,
        symbol: str,
        side: str,
        quantity: float,
        balance_info: dict | None = None,
    ) -> dict:
        """Submit a market order with a 5-second hard timeout."""
        try:
            order = await asyncio.wait_for(
                exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=quantity,
                ),
                timeout=self.ORDER_TIMEOUT_SECONDS,
            )
            logger.info(
                "Order placed: symbol=%s side=%s quantity=%s order_id=%s",
                symbol, side, quantity, order.get("id"),
            )
            return order

        except asyncio.TimeoutError as exc:
            raise OrderExecutionError(
                f"Order submission timed out after {self.ORDER_TIMEOUT_SECONDS}s "
                f"for {symbol} {side} {quantity}",
                balance_info=balance_info,
            ) from exc
        except ccxt_async.BaseError as exc:
            raise OrderExecutionError(
                f"Exchange error placing {side} order for {symbol}: {exc}",
                balance_info=balance_info,
            ) from exc
