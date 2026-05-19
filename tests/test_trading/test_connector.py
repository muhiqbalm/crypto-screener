"""Unit tests for src/trading/connector.py.

Tests the TradingConnector class, covering:
- Supported exchanges (binance, okx)
- Unsupported exchange rejection
- Testnet (sandbox) configuration
- Leverage setting (success and failure paths)
- Auth failure handling
- Complete separation from the screener ExchangeConnector
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import ccxt.async_support as ccxt_async

from src.trading.connector import AuthenticationError, LeverageSetError, TradingConnector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_credentials(
    api_key: str = "test_key",
    secret: str = "test_secret",
    passphrase: str | None = None,
) -> dict:
    creds = {"api_key": api_key, "secret": secret}
    if passphrase is not None:
        creds["passphrase"] = passphrase
    return creds


# ---------------------------------------------------------------------------
# Module separation tests
# ---------------------------------------------------------------------------

class TestModuleSeparation:
    """Req 4.3: TradingConnector must not share class hierarchy or instances
    with the screener ExchangeConnector."""

    def test_not_subclass_of_screener_connector(self):
        from src.exchange.connector import ExchangeConnector
        assert not issubclass(TradingConnector, ExchangeConnector)

    def test_connector_module_path_is_trading(self):
        assert TradingConnector.__module__ == "src.trading.connector"

    def test_screener_connector_module_path_is_exchange(self):
        from src.exchange.connector import ExchangeConnector
        assert ExchangeConnector.__module__ == "src.exchange.connector"


# ---------------------------------------------------------------------------
# Supported exchanges
# ---------------------------------------------------------------------------

class TestSupportedExchanges:
    """Req 4.1: Only binance and okx are supported."""

    def test_supported_exchanges_contains_binance_and_okx(self):
        assert "binance" in TradingConnector.SUPPORTED_EXCHANGES
        assert "okx" in TradingConnector.SUPPORTED_EXCHANGES

    @pytest.mark.asyncio
    async def test_unsupported_exchange_raises_value_error(self):
        connector = TradingConnector()
        with pytest.raises(ValueError, match="not supported"):
            await connector.create_exchange(
                "bybit", _make_credentials(), "BTC/USDT:USDT"
            )

    @pytest.mark.asyncio
    async def test_unsupported_exchange_error_lists_supported(self):
        connector = TradingConnector()
        with pytest.raises(ValueError) as exc_info:
            await connector.create_exchange(
                "kraken", _make_credentials(), "BTC/USDT:USDT"
            )
        assert "binance" in str(exc_info.value)
        assert "okx" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Testnet / sandbox configuration (Req 4.2)
# ---------------------------------------------------------------------------

class TestTestnetConfiguration:
    """Req 4.2: All exchange instances must use testnet (sandbox: True)."""

    @pytest.mark.asyncio
    async def test_binance_instance_has_sandbox_true(self):
        connector = TradingConnector()

        captured_config = {}

        original_binance = ccxt_async.binance

        class CaptureBinance(original_binance):
            def __init__(self, config=None):
                captured_config.update(config or {})
                # Don't call super().__init__ to avoid real network setup
                self.id = "binance"
                self.markets = {}
                self.options = config.get("options", {})

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": CaptureBinance}):
            await connector.create_exchange("binance", _make_credentials(), "BTC/USDT:USDT")

        assert captured_config.get("sandbox") is True

    @pytest.mark.asyncio
    async def test_okx_instance_has_sandbox_true(self):
        connector = TradingConnector()

        captured_config = {}

        original_okx = ccxt_async.okx

        class CaptureOkx(original_okx):
            def __init__(self, config=None):
                captured_config.update(config or {})
                self.id = "okx"
                self.markets = {}
                self.options = config.get("options", {})

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"okx": CaptureOkx}):
            await connector.create_exchange("okx", _make_credentials(), "BTC/USDT:USDT")

        assert captured_config.get("sandbox") is True


# ---------------------------------------------------------------------------
# Credential mapping
# ---------------------------------------------------------------------------

class TestCredentialMapping:
    """Verify that credentials dict is correctly mapped to CCXT config keys."""

    @pytest.mark.asyncio
    async def test_api_key_and_secret_are_passed(self):
        connector = TradingConnector()
        captured_config = {}

        class CaptureExchange:
            def __init__(self, config=None):
                captured_config.update(config or {})
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": CaptureExchange}):
            await connector.create_exchange(
                "binance",
                _make_credentials(api_key="MY_KEY", secret="MY_SECRET"),
                "ETH/USDT:USDT",
            )

        assert captured_config["apiKey"] == "MY_KEY"
        assert captured_config["secret"] == "MY_SECRET"

    @pytest.mark.asyncio
    async def test_okx_passphrase_mapped_to_password(self):
        connector = TradingConnector()
        captured_config = {}

        class CaptureExchange:
            def __init__(self, config=None):
                captured_config.update(config or {})
                self.id = "okx"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"okx": CaptureExchange}):
            await connector.create_exchange(
                "okx",
                _make_credentials(passphrase="MY_PASS"),
                "BTC/USDT:USDT",
            )

        assert captured_config.get("password") == "MY_PASS"

    @pytest.mark.asyncio
    async def test_binance_no_password_key_set(self):
        """Binance does not require a passphrase; password should not be set."""
        connector = TradingConnector()
        captured_config = {}

        class CaptureExchange:
            def __init__(self, config=None):
                captured_config.update(config or {})
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": CaptureExchange}):
            await connector.create_exchange(
                "binance", _make_credentials(), "BTC/USDT:USDT"
            )

        assert "password" not in captured_config


# ---------------------------------------------------------------------------
# Authentication failure (Req 4.5)
# ---------------------------------------------------------------------------

class TestAuthenticationFailure:
    """Req 4.5: Auth failures raise AuthenticationError."""

    @pytest.mark.asyncio
    async def test_ccxt_auth_error_raises_authentication_error(self):
        connector = TradingConnector()

        class FailAuthExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                raise ccxt_async.AuthenticationError("bad key")

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": FailAuthExchange}):
            with pytest.raises(AuthenticationError, match="authentication failed"):
                await connector.create_exchange(
                    "binance", _make_credentials(), "BTC/USDT:USDT"
                )

    @pytest.mark.asyncio
    async def test_network_error_raises_authentication_error(self):
        connector = TradingConnector()

        class NetworkFailExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                raise ccxt_async.NetworkError("connection refused")

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": NetworkFailExchange}):
            with pytest.raises(AuthenticationError):
                await connector.create_exchange(
                    "binance", _make_credentials(), "BTC/USDT:USDT"
                )

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_authentication_error(self):
        connector = TradingConnector()

        class UnexpectedFailExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                raise RuntimeError("unexpected failure")

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": UnexpectedFailExchange}):
            with pytest.raises(AuthenticationError):
                await connector.create_exchange(
                    "binance", _make_credentials(), "BTC/USDT:USDT"
                )


# ---------------------------------------------------------------------------
# Leverage setting (Req 4.4)
# ---------------------------------------------------------------------------

class TestLeverageSetting:
    """Req 4.4: When leverage is provided, set_leverage is called before returning."""

    @pytest.mark.asyncio
    async def test_leverage_set_when_provided(self):
        connector = TradingConnector()
        set_leverage_calls = []

        class LeverageExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def set_leverage(self, leverage, symbol, params=None):
                set_leverage_calls.append((leverage, symbol))

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": LeverageExchange}):
            await connector.create_exchange(
                "binance", _make_credentials(), "BTC/USDT:USDT", leverage=10
            )

        assert len(set_leverage_calls) == 1
        assert set_leverage_calls[0] == (10, "BTC/USDT:USDT")

    @pytest.mark.asyncio
    async def test_no_leverage_call_when_leverage_is_none(self):
        connector = TradingConnector()
        set_leverage_calls = []

        class NoLevExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def set_leverage(self, leverage, symbol, params=None):
                set_leverage_calls.append((leverage, symbol))

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": NoLevExchange}):
            await connector.create_exchange(
                "binance", _make_credentials(), "BTC/USDT:USDT", leverage=None
            )

        assert len(set_leverage_calls) == 0


# ---------------------------------------------------------------------------
# Leverage failure (Req 4.6)
# ---------------------------------------------------------------------------

class TestLeverageFailure:
    """Req 4.6: Leverage set failures raise LeverageSetError; order is NOT placed."""

    @pytest.mark.asyncio
    async def test_exchange_error_on_set_leverage_raises_leverage_set_error(self):
        connector = TradingConnector()

        class LevFailExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def set_leverage(self, leverage, symbol, params=None):
                raise ccxt_async.ExchangeError("leverage not supported")

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": LevFailExchange}):
            with pytest.raises(LeverageSetError, match="Failed to set leverage"):
                await connector.create_exchange(
                    "binance", _make_credentials(), "BTC/USDT:USDT", leverage=50
                )

    @pytest.mark.asyncio
    async def test_unexpected_error_on_set_leverage_raises_leverage_set_error(self):
        connector = TradingConnector()

        class LevUnexpectedExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def set_leverage(self, leverage, symbol, params=None):
                raise ValueError("unexpected")

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": LevUnexpectedExchange}):
            with pytest.raises(LeverageSetError):
                await connector.create_exchange(
                    "binance", _make_credentials(), "BTC/USDT:USDT", leverage=5
                )

    @pytest.mark.asyncio
    async def test_leverage_failure_error_includes_symbol_and_leverage(self):
        connector = TradingConnector()

        class LevFailExchange:
            def __init__(self, config=None):
                self.id = "okx"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def set_leverage(self, leverage, symbol, params=None):
                raise ccxt_async.ExchangeError("bad request")

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"okx": LevFailExchange}):
            with pytest.raises(LeverageSetError) as exc_info:
                await connector.create_exchange(
                    "okx", _make_credentials(), "ETH/USDT:USDT", leverage=20
                )

        error_msg = str(exc_info.value)
        assert "20" in error_msg
        assert "ETH/USDT:USDT" in error_msg


# ---------------------------------------------------------------------------
# Successful creation
# ---------------------------------------------------------------------------

class TestSuccessfulCreation:
    """Happy-path: exchange instance is returned on success."""

    @pytest.mark.asyncio
    async def test_returns_exchange_instance(self):
        connector = TradingConnector()

        class OkExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": OkExchange}):
            result = await connector.create_exchange(
                "binance", _make_credentials(), "BTC/USDT:USDT"
            )

        assert isinstance(result, OkExchange)

    @pytest.mark.asyncio
    async def test_exchange_name_case_insensitive(self):
        """Exchange name should be lowercased for lookup."""
        connector = TradingConnector()

        class OkExchange:
            def __init__(self, config=None):
                self.id = "binance"
                self.markets = {}

            async def load_markets(self):
                return {}

            async def close(self):
                pass

        with patch.dict(TradingConnector.SUPPORTED_EXCHANGES, {"binance": OkExchange}):
            result = await connector.create_exchange(
                "BINANCE", _make_credentials(), "BTC/USDT:USDT"
            )

        assert isinstance(result, OkExchange)
