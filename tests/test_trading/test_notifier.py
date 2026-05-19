"""Unit tests for src/trading/notifier.py — TelegramNotifier class.

Covers:
- Message formatting (symbol, side, quantity, price, exchange always present)
- PnL calculation for long and short close orders
- skip (log warning) when chat_id is None or empty string
- skip (log warning) when bot_token is empty
- Successful Telegram API call (2xx response)
- Non-2xx Telegram response logged silently (no exception raised)
- Timeout logged silently (no exception raised)
- HTTP error logged silently (no exception raised)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.trading.notifier import TelegramNotifier, _calculate_pnl, _format_notification_message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_trade_result(**overrides) -> dict:
    """Return a minimal valid trade_result dict."""
    defaults = {
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "filled_quantity": 0.5,
        "fill_price": 50000.0,
        "exchange": "binance",
        "action": "open",
    }
    defaults.update(overrides)
    return defaults


def make_position(**overrides) -> dict:
    """Return a minimal valid position dict."""
    defaults = {
        "side": "long",
        "entry_price": 48000.0,
        "quantity": 0.5,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# _calculate_pnl
# ---------------------------------------------------------------------------


class TestCalculatePnl:
    def test_long_profit(self):
        """Long: (exit - entry) * qty → positive when exit > entry."""
        position = {"side": "long", "entry_price": 40000.0, "quantity": 1.0}
        pnl = _calculate_pnl(position, exit_price=45000.0)
        assert pnl == pytest.approx(5000.0)

    def test_long_loss(self):
        """Long: (exit - entry) * qty → negative when exit < entry."""
        position = {"side": "long", "entry_price": 50000.0, "quantity": 2.0}
        pnl = _calculate_pnl(position, exit_price=45000.0)
        assert pnl == pytest.approx(-10000.0)

    def test_short_profit(self):
        """Short: (entry - exit) * qty → positive when exit < entry."""
        position = {"side": "short", "entry_price": 50000.0, "quantity": 1.0}
        pnl = _calculate_pnl(position, exit_price=45000.0)
        assert pnl == pytest.approx(5000.0)

    def test_short_loss(self):
        """Short: (entry - exit) * qty → negative when exit > entry."""
        position = {"side": "short", "entry_price": 40000.0, "quantity": 0.5}
        pnl = _calculate_pnl(position, exit_price=45000.0)
        assert pnl == pytest.approx(-2500.0)

    def test_breakeven_long(self):
        """Long breakeven: exit == entry → PnL == 0."""
        position = {"side": "long", "entry_price": 50000.0, "quantity": 1.0}
        pnl = _calculate_pnl(position, exit_price=50000.0)
        assert pnl == pytest.approx(0.0)

    def test_string_values_coerced(self):
        """entry_price / quantity stored as strings in DB — coercion must work."""
        position = {"side": "long", "entry_price": "40000.0", "quantity": "2.0"}
        pnl = _calculate_pnl(position, exit_price=42000.0)
        assert pnl == pytest.approx(4000.0)


# ---------------------------------------------------------------------------
# _format_notification_message
# ---------------------------------------------------------------------------


class TestFormatNotificationMessage:
    def test_open_order_contains_required_fields(self):
        """Open trade message must contain symbol, side, quantity, price, exchange."""
        trade_result = make_trade_result(action="open")
        msg = _format_notification_message(trade_result)
        assert "BTC/USDT:USDT" in msg
        assert "long" in msg.lower() or "LONG" in msg
        assert "0.5" in msg
        assert "50000.0" in msg
        assert "binance" in msg.lower() or "BINANCE" in msg

    def test_open_order_has_no_pnl(self):
        """Open trade message must NOT contain PnL."""
        trade_result = make_trade_result(action="open")
        msg = _format_notification_message(trade_result)
        assert "PnL" not in msg

    def test_close_order_includes_pnl(self):
        """Close trade message must include realized PnL."""
        trade_result = make_trade_result(action="close", fill_price=52000.0)
        position = make_position(side="long", entry_price=48000.0, quantity=0.5)
        msg = _format_notification_message(trade_result, position=position)
        # PnL = (52000 - 48000) * 0.5 = 2000
        assert "PnL" in msg
        assert "2000" in msg

    def test_close_order_without_position_has_no_pnl(self):
        """If position is None for a close, no PnL line appears."""
        trade_result = make_trade_result(action="close")
        msg = _format_notification_message(trade_result, position=None)
        assert "PnL" not in msg

    def test_short_trade_appears_in_message(self):
        """Short side should appear in the message."""
        trade_result = make_trade_result(side="short", action="open")
        msg = _format_notification_message(trade_result)
        assert "short" in msg.lower() or "SHORT" in msg

    def test_okx_exchange_appears_in_message(self):
        """OKX exchange name should appear in message."""
        trade_result = make_trade_result(exchange="okx")
        msg = _format_notification_message(trade_result)
        assert "okx" in msg.lower() or "OKX" in msg


# ---------------------------------------------------------------------------
# TelegramNotifier.send_trade_notification — skip conditions
# ---------------------------------------------------------------------------


class TestSendTradeNotificationSkip:
    @pytest.mark.asyncio
    async def test_skips_when_chat_id_is_none(self, caplog):
        """No chat_id → skip with warning, no HTTP call."""
        notifier = TelegramNotifier(bot_token="test-token")
        trade_result = make_trade_result()
        with patch("httpx.AsyncClient") as mock_client_cls:
            await notifier.send_trade_notification(None, trade_result)
        mock_client_cls.assert_not_called()
        assert "no chat_id configured" in caplog.text

    @pytest.mark.asyncio
    async def test_skips_when_chat_id_is_empty_string(self, caplog):
        """Empty chat_id → skip with warning, no HTTP call."""
        notifier = TelegramNotifier(bot_token="test-token")
        trade_result = make_trade_result()
        with patch("httpx.AsyncClient") as mock_client_cls:
            await notifier.send_trade_notification("", trade_result)
        mock_client_cls.assert_not_called()
        assert "no chat_id configured" in caplog.text

    @pytest.mark.asyncio
    async def test_skips_when_bot_token_is_empty(self, caplog):
        """Empty bot_token → skip with warning, no HTTP call."""
        notifier = TelegramNotifier(bot_token="")
        trade_result = make_trade_result()
        with patch("httpx.AsyncClient") as mock_client_cls:
            await notifier.send_trade_notification("12345", trade_result)
        mock_client_cls.assert_not_called()
        assert "bot_token is not configured" in caplog.text


# ---------------------------------------------------------------------------
# TelegramNotifier.send_trade_notification — HTTP interactions
# ---------------------------------------------------------------------------


class TestSendTradeNotificationHttp:
    @pytest.mark.asyncio
    async def test_successful_send_calls_telegram_api(self):
        """Happy path: valid chat_id and token → POST to Telegram API."""
        notifier = TelegramNotifier(bot_token="valid-token")
        trade_result = make_trade_result()

        mock_response = MagicMock()
        mock_response.is_success = True

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.trading.notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.send_trade_notification("12345", trade_result)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "sendMessage" in call_args.args[0]
        payload = call_args.kwargs["json"]
        assert payload["chat_id"] == "12345"
        assert "BTC/USDT:USDT" in payload["text"]

    @pytest.mark.asyncio
    async def test_non_2xx_response_logged_silently(self, caplog):
        """Non-2xx Telegram response → error logged, no exception raised."""
        notifier = TelegramNotifier(bot_token="valid-token")
        trade_result = make_trade_result()

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.trading.notifier.httpx.AsyncClient", return_value=mock_client):
            # Must NOT raise
            await notifier.send_trade_notification("12345", trade_result)

        assert "non-2xx" in caplog.text or "400" in caplog.text

    @pytest.mark.asyncio
    async def test_timeout_logged_silently(self, caplog):
        """TimeoutException → error logged, no exception raised."""
        notifier = TelegramNotifier(bot_token="valid-token")
        trade_result = make_trade_result()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("src.trading.notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.send_trade_notification("12345", trade_result)

        assert "timed out" in caplog.text

    @pytest.mark.asyncio
    async def test_http_error_logged_silently(self, caplog):
        """httpx.HTTPError → error logged, no exception raised."""
        notifier = TelegramNotifier(bot_token="valid-token")
        trade_result = make_trade_result()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPError("Connection refused")
        )

        with patch("src.trading.notifier.httpx.AsyncClient", return_value=mock_client):
            await notifier.send_trade_notification("12345", trade_result)

        assert "failed" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_timeout_setting_passed_to_client(self):
        """AsyncClient is created with the 10-second timeout constant."""
        notifier = TelegramNotifier(bot_token="valid-token")
        trade_result = make_trade_result()

        mock_response = MagicMock()
        mock_response.is_success = True

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.trading.notifier.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await notifier.send_trade_notification("12345", trade_result)

        # Verify AsyncClient was constructed with the timeout value
        mock_cls.assert_called_once_with(timeout=TelegramNotifier.TIMEOUT_SECONDS)
        assert TelegramNotifier.TIMEOUT_SECONDS == 10
