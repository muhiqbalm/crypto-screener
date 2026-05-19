"""Unit tests for src/trading/executor.py — TradeExecutor class.

Covers:
- calculate_quantity (percent and fixed modes)
- execute_trade for open-long, open-short, close-long, close-short
- InsufficientBalanceError when balance is too low
- OrderExecutionError on CCXT failures and timeouts
- ValueError when no position is supplied for a close action
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.executor import (
    InsufficientBalanceError,
    OrderExecutionError,
    TradeExecutor,
)
from src.trading.models import WebhookPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_payload(**overrides) -> WebhookPayload:
    """Build a minimal valid WebhookPayload, applying any overrides."""
    defaults = {
        "action": "open",
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "size_type": "percent",
        "size_value": 10.0,
        "leverage": None,
        "exchange": "binance",
        "passphrase": "secret",
    }
    defaults.update(overrides)
    return WebhookPayload(**defaults)


def make_exchange(free_balance: float = 1000.0, last_price: float = 50000.0) -> AsyncMock:
    """Return a mock CCXT exchange with preset balance and ticker."""
    exchange = AsyncMock()
    exchange.fetch_balance.return_value = {"free": {"USDT": free_balance}}
    exchange.fetch_ticker.return_value = {"last": last_price}
    exchange.create_order.return_value = {
        "id": "order-123",
        "symbol": "BTC/USDT:USDT",
        "side": "buy",
        "amount": 0.002,
        "price": last_price,
        "filled": 0.002,
        "status": "closed",
    }
    return exchange


# ---------------------------------------------------------------------------
# calculate_quantity
# ---------------------------------------------------------------------------

class TestCalculateQuantity:
    executor = TradeExecutor()

    def test_percent_basic(self):
        """10% of 1000 USDT at 50000 USDT/BTC = 0.002 BTC."""
        qty = self.executor.calculate_quantity("percent", 10.0, 1000.0, 50000.0)
        assert qty == pytest.approx(0.002)

    def test_percent_full_balance(self):
        """100% of 500 USDT at 25000 = 0.02 BTC."""
        qty = self.executor.calculate_quantity("percent", 100.0, 500.0, 25000.0)
        assert qty == pytest.approx(0.02)

    def test_percent_small_fraction(self):
        """1% of 100000 at 40000 = 0.025 BTC."""
        qty = self.executor.calculate_quantity("percent", 1.0, 100000.0, 40000.0)
        assert qty == pytest.approx(0.025)

    def test_fixed_returns_size_value_directly(self):
        """Fixed mode ignores free_balance and current_price entirely."""
        qty = self.executor.calculate_quantity("fixed", 0.5, 99999.0, 1.0)
        assert qty == pytest.approx(0.5)

    def test_fixed_large_value(self):
        qty = self.executor.calculate_quantity("fixed", 10_000_000.0, 0.0, 0.0)
        assert qty == pytest.approx(10_000_000.0)


# ---------------------------------------------------------------------------
# execute_trade — open long
# ---------------------------------------------------------------------------

class TestExecuteTradeOpenLong:

    @pytest.mark.asyncio
    async def test_places_market_buy(self):
        """open + long → create_order called with side='buy'."""
        executor = TradeExecutor()
        exchange = make_exchange(free_balance=1000.0, last_price=50000.0)
        payload = make_payload(action="open", side="long", size_type="percent", size_value=10.0)

        result = await executor.execute_trade(exchange, payload)

        exchange.create_order.assert_called_once()
        call_kwargs = exchange.create_order.call_args
        assert call_kwargs.kwargs["side"] == "buy"
        assert call_kwargs.kwargs["type"] == "market"
        assert result["id"] == "order-123"

    @pytest.mark.asyncio
    async def test_percent_quantity_used(self):
        """Verify the quantity passed to create_order matches percent calculation."""
        executor = TradeExecutor()
        exchange = make_exchange(free_balance=1000.0, last_price=50000.0)
        # 10% of 1000 / 50000 = 0.002
        payload = make_payload(action="open", side="long", size_type="percent", size_value=10.0)

        await executor.execute_trade(exchange, payload)

        call_kwargs = exchange.create_order.call_args
        assert call_kwargs.kwargs["amount"] == pytest.approx(0.002)

    @pytest.mark.asyncio
    async def test_fixed_quantity_used(self):
        """Fixed size_type passes size_value directly as quantity."""
        executor = TradeExecutor()
        exchange = make_exchange(free_balance=100_000.0, last_price=50000.0)
        payload = make_payload(action="open", side="long", size_type="fixed", size_value=0.5)

        await executor.execute_trade(exchange, payload)

        call_kwargs = exchange.create_order.call_args
        assert call_kwargs.kwargs["amount"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# execute_trade — open short
# ---------------------------------------------------------------------------

class TestExecuteTradeOpenShort:

    @pytest.mark.asyncio
    async def test_places_market_sell(self):
        """open + short → create_order called with side='sell'."""
        executor = TradeExecutor()
        exchange = make_exchange(free_balance=5000.0, last_price=1000.0)
        exchange.create_order.return_value = {
            "id": "sell-001", "side": "sell", "amount": 0.5,
            "filled": 0.5, "price": 1000.0, "status": "closed"
        }
        payload = make_payload(action="open", side="short", size_type="percent", size_value=10.0)

        result = await executor.execute_trade(exchange, payload)

        call_kwargs = exchange.create_order.call_args
        assert call_kwargs.kwargs["side"] == "sell"
        assert call_kwargs.kwargs["type"] == "market"


# ---------------------------------------------------------------------------
# execute_trade — close
# ---------------------------------------------------------------------------

class TestExecuteTradeClose:

    @pytest.mark.asyncio
    async def test_close_long_places_sell(self):
        """Closing a long position → sell order for position quantity."""
        executor = TradeExecutor()
        exchange = AsyncMock()
        exchange.create_order.return_value = {
            "id": "close-001", "side": "sell", "amount": 1.0,
            "filled": 1.0, "price": 55000.0, "status": "closed"
        }
        position = {"side": "long", "quantity": 1.0}
        payload = make_payload(action="close", side="long")

        await executor.execute_trade(exchange, payload, position=position)

        call_kwargs = exchange.create_order.call_args
        assert call_kwargs.kwargs["side"] == "sell"
        assert call_kwargs.kwargs["amount"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_close_short_places_buy(self):
        """Closing a short position → buy order for position quantity."""
        executor = TradeExecutor()
        exchange = AsyncMock()
        exchange.create_order.return_value = {
            "id": "close-002", "side": "buy", "amount": 2.0,
            "filled": 2.0, "price": 45000.0, "status": "closed"
        }
        position = {"side": "short", "quantity": 2.0}
        payload = make_payload(action="close", side="short")

        await executor.execute_trade(exchange, payload, position=position)

        call_kwargs = exchange.create_order.call_args
        assert call_kwargs.kwargs["side"] == "buy"
        assert call_kwargs.kwargs["amount"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_close_without_position_raises_value_error(self):
        """Passing position=None for a close action must raise ValueError."""
        executor = TradeExecutor()
        exchange = AsyncMock()
        payload = make_payload(action="close")

        with pytest.raises(ValueError, match="position record is required"):
            await executor.execute_trade(exchange, payload, position=None)

    @pytest.mark.asyncio
    async def test_close_does_not_fetch_balance_or_ticker(self):
        """Close action skips balance/ticker fetching entirely."""
        executor = TradeExecutor()
        exchange = AsyncMock()
        exchange.create_order.return_value = {
            "id": "close-003", "side": "sell", "amount": 0.5,
            "filled": 0.5, "price": 60000.0, "status": "closed"
        }
        position = {"side": "long", "quantity": 0.5}
        payload = make_payload(action="close")

        await executor.execute_trade(exchange, payload, position=position)

        exchange.fetch_balance.assert_not_called()
        exchange.fetch_ticker.assert_not_called()


# ---------------------------------------------------------------------------
# InsufficientBalanceError
# ---------------------------------------------------------------------------

class TestInsufficientBalance:

    @pytest.mark.asyncio
    async def test_raises_when_cost_exceeds_balance(self):
        """Order cost > free balance → InsufficientBalanceError raised, no order placed."""
        executor = TradeExecutor()
        # free_balance=100, price=50000 → 10% → qty=0.0002 → cost=10 ≤ 100 … let's force it
        # Use fixed size_value that costs more than free balance
        exchange = make_exchange(free_balance=100.0, last_price=50000.0)
        # fixed qty=1 → cost = 1 * 50000 = 50000 > 100
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=1.0
        )

        with pytest.raises(InsufficientBalanceError):
            await executor.execute_trade(exchange, payload)

        exchange.create_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_raise_when_balance_exactly_covers_cost(self):
        """Edge case: free_balance exactly equals order cost → order placed."""
        executor = TradeExecutor()
        # qty=0.002, price=50000 → cost=100 = free_balance=100
        exchange = make_exchange(free_balance=100.0, last_price=50000.0)
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=0.002
        )

        result = await executor.execute_trade(exchange, payload)

        exchange.create_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_free_balance_raises_insufficient(self):
        """Zero free balance always triggers InsufficientBalanceError."""
        executor = TradeExecutor()
        exchange = make_exchange(free_balance=0.0, last_price=50000.0)
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=0.001
        )

        with pytest.raises(InsufficientBalanceError):
            await executor.execute_trade(exchange, payload)


# ---------------------------------------------------------------------------
# OrderExecutionError — exchange and timeout failures
# ---------------------------------------------------------------------------

class TestOrderExecutionError:

    @pytest.mark.asyncio
    async def test_raises_on_ccxt_exchange_error(self):
        """CCXT BaseError during create_order → OrderExecutionError."""
        import ccxt

        executor = TradeExecutor()
        exchange = make_exchange(free_balance=100_000.0, last_price=50000.0)
        exchange.create_order.side_effect = ccxt.BaseError("Exchange rejected order")
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=0.001
        )

        with pytest.raises(OrderExecutionError, match="Exchange error"):
            await executor.execute_trade(exchange, payload)

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        """asyncio.TimeoutError during create_order → OrderExecutionError."""
        executor = TradeExecutor()
        exchange = make_exchange(free_balance=100_000.0, last_price=50000.0)

        async def slow_order(**kwargs):
            await asyncio.sleep(100)

        exchange.create_order = slow_order
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=0.001
        )
        # Override timeout to 0 seconds to trigger immediately in tests
        executor.ORDER_TIMEOUT_SECONDS = 0

        with pytest.raises(OrderExecutionError, match="timed out"):
            await executor.execute_trade(exchange, payload)

    @pytest.mark.asyncio
    async def test_no_retry_on_exchange_error(self):
        """Exchange errors are NOT retried — create_order called exactly once."""
        import ccxt

        executor = TradeExecutor()
        exchange = make_exchange(free_balance=100_000.0, last_price=50000.0)
        exchange.create_order.side_effect = ccxt.BaseError("Fail once, not retried")
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=0.001
        )

        with pytest.raises(OrderExecutionError):
            await executor.execute_trade(exchange, payload)

        assert exchange.create_order.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_on_balance_fetch_error(self):
        """CCXT error during fetch_balance → OrderExecutionError."""
        import ccxt

        executor = TradeExecutor()
        exchange = AsyncMock()
        exchange.fetch_balance.side_effect = ccxt.AuthenticationError("API key invalid")
        payload = make_payload(
            action="open", side="long", size_type="fixed", size_value=0.001
        )

        with pytest.raises(OrderExecutionError, match="Failed to fetch balance"):
            await executor.execute_trade(exchange, payload)
