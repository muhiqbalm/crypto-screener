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
    """Raised when the user's free margin balance is too low to place the order.

    Requirement 5.6: If the user's free margin balance is less than the cost
    of the calculated order quantity at current market price, the Executor
    SHALL reject the trade with this error.
    """


class OrderExecutionError(Exception):
    """Raised when the exchange returns an error during order placement.

    Requirement 5.7: Exchange order failures are wrapped in this error to
    distinguish them from balance or validation failures.
    """


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
    ) -> dict:
        """Execute a market order on the exchange based on the webhook payload.

        For "open" + "long":  market buy  (Requirement 5.1)
        For "open" + "short": market sell (Requirement 5.2)
        For "close":          opposite market order for full position quantity (Requirement 5.3)

        Balance is checked before order placement (Requirement 5.6).
        Order submission is wrapped in a 5-second timeout (Requirement 5.8).
        No retry on exchange failure (Requirement 5.7).

        Args:
            exchange: An authenticated CCXT exchange instance
            payload: The validated webhook payload
            position: Open position record (required when action == "close")

        Returns:
            The raw CCXT order response dict from the exchange

        Raises:
            InsufficientBalanceError: When free margin is too low for the order
            OrderExecutionError: When the exchange returns an error during placement
            ValueError: When position is None for a "close" action
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
    ) -> tuple[float, float]:
        """Fetch the user's free margin balance and the current market price.

        For OKX futures, fetches from the unified trading account which holds
        futures margin. Uses ``defaultType: future`` already set in the
        exchange config.

        Returns:
            Tuple of (free_balance_in_quote, current_price)

        Raises:
            OrderExecutionError: On CCXT errors during balance/price fetch
        """
        try:
            quote_currency = symbol.split("/")[1].split(":")[0]

            # For OKX, fetch balance with 'trading' account type to get
            # the unified account balance that covers futures margin
            exchange_id = exchange.id.lower()
            if exchange_id == "okx":
                balance = await exchange.fetch_balance({"type": "trading"})
            else:
                balance = await exchange.fetch_balance()

            free_balance: float = float(
                balance.get("free", {}).get(quote_currency, 0.0) or 0.0
            )

            ticker = await exchange.fetch_ticker(symbol)
            current_price: float = float(ticker["last"])

            return free_balance, current_price

        except (ccxt_async.BaseError, KeyError, TypeError, ValueError) as exc:
            raise OrderExecutionError(
                f"Failed to fetch balance or price for {symbol}: {exc}"
            ) from exc

    async def _execute_open(
        self, exchange: ccxt_async.Exchange, payload: WebhookPayload
    ) -> dict:
        """Handle 'open' action: calculate quantity, check balance, place order.

        Requirements: 5.1, 5.2, 5.4, 5.5, 5.6, 5.8
        """
        symbol = payload.symbol

        free_balance, current_price = await self._fetch_free_balance(exchange, symbol)

        quantity = self.calculate_quantity(
            payload.size_type,
            payload.size_value,
            free_balance,
            current_price,
            leverage=payload.leverage or 1,
        )

        # Round quantity to exchange-required precision
        quantity = self._round_to_precision(exchange, symbol, quantity)

        # Validate against exchange minimum amount
        self._validate_min_amount(exchange, symbol, quantity)

        # Requirement 5.6: check margin requirement (notional / leverage ≤ free_balance)
        leverage = payload.leverage or 1
        margin_required = (quantity * current_price) / leverage
        if margin_required > free_balance:
            raise InsufficientBalanceError(
                f"Insufficient margin: required {margin_required:.4f} USDT "
                f"but free balance is {free_balance:.4f} USDT for {symbol}"
            )

        # Requirement 5.1 / 5.2: buy for long, sell for short
        order_side = "buy" if payload.side == "long" else "sell"

        return await self._place_order_with_timeout(
            exchange, symbol, order_side, quantity
        )

    async def _execute_close(
        self,
        exchange: ccxt_async.Exchange,
        symbol: str,
        position: dict | None,
    ) -> dict:
        """Handle 'close' action: place opposite market order for full position size.

        Requirements: 5.3, 5.8
        """
        if position is None:
            raise ValueError(
                "A position record is required to close a trade, but none was provided."
            )

        # Opposite side: close long → sell, close short → buy
        position_side: str = position.get("side") or position.get("info", {}).get("posSide", "long")
        close_side = "sell" if str(position_side).lower() == "long" else "buy"

        # Use contracts from exchange position data
        quantity: float = float(
            position.get("contracts") or position.get("size") or position.get("quantity") or 0.0
        )

        # Round to exchange precision
        quantity = self._round_to_precision(exchange, symbol, quantity)

        # Validate against exchange minimum amount
        self._validate_min_amount(exchange, symbol, quantity)

        return await self._place_order_with_timeout(
            exchange, symbol, close_side, quantity
        )

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
    ) -> dict:
        """Submit a market order with a 5-second hard timeout.

        Requirement 5.8: The Executor SHALL submit the order within 5 seconds.
        Requirement 5.7: No retry on exchange failure.

        Raises:
            OrderExecutionError: On CCXT error or timeout
        """
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
                symbol,
                side,
                quantity,
                order.get("id"),
            )
            return order

        except asyncio.TimeoutError as exc:
            raise OrderExecutionError(
                f"Order submission timed out after {self.ORDER_TIMEOUT_SECONDS}s "
                f"for {symbol} {side} {quantity}"
            ) from exc
        except ccxt_async.BaseError as exc:
            raise OrderExecutionError(
                f"Exchange error placing {side} order for {symbol}: {exc}"
            ) from exc
