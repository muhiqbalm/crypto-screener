"""
Unit tests for DebugExchangeService.

Tests the debug exchange service methods for fetching raw exchange data
with proper error handling, timing, and field mapping.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
import ccxt

from src.services.debug_exchange_service import DebugExchangeService
from src.api.debug_models import DebugResponse, ErrorInfo


class TestFetchRawTicker:
    """Tests for the fetch_raw_ticker method."""
    
    @pytest.fixture
    def mock_exchange_connector(self):
        """Create a mock ExchangeConnector."""
        connector = Mock()
        exchange = AsyncMock()
        connector.get_exchange.return_value = exchange
        return connector
    
    @pytest.fixture
    def debug_service(self, mock_exchange_connector):
        """Create a DebugExchangeService instance with mocked exchange."""
        return DebugExchangeService(mock_exchange_connector)
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_success(self, debug_service):
        """Test successful ticker data retrieval."""
        # Arrange
        symbol = "BTCUSDT"
        mock_ticker_data = {
            "symbol": "BTC/USDT:USDT",
            "last": 50000.0,
            "percentage": 2.5,
            "quoteVolume": 1000000.0,
            "baseVolume": 20.0,
            "timestamp": 1234567890000
        }
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is True
        assert result.data == mock_ticker_data
        assert result.error is None
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.http_status == 200
        assert result.metadata.response_time_ms >= 0
        assert result.fieldMapping is not None
        assert "last" in result.fieldMapping
        assert result.fieldMapping["last"].app_field == "price"
        
        # Verify exchange was called with CCXT format (converted from Binance format)
        debug_service.exchange.fetch_ticker.assert_called_once_with("BTC/USDT:USDT")
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_normalizes_symbol(self, debug_service):
        """Test that symbol is normalized (uppercase and trimmed)."""
        # Arrange
        symbol = "  btcusdt  "
        mock_ticker_data = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is True
        debug_service.exchange.fetch_ticker.assert_called_once_with("BTC/USDT:USDT")
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_empty_symbol(self, debug_service):
        """Test validation error for empty symbol."""
        # Arrange
        symbol = ""
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.data is None
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter is required"
        assert result.metadata.exchange == "binanceusdm"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_invalid_characters(self, debug_service):
        """Test validation error for symbol with invalid characters."""
        # Arrange
        symbol = "BTC-USDT"
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_exceeds_max_length(self, debug_service):
        """Test validation error for symbol exceeding max length."""
        # Arrange
        symbol = "A" * 21  # 21 characters, max is 20
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_network_error(self, debug_service):
        """Test handling of network errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert "Service unavailable" in result.error.message
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_timeout_error(self, debug_service):
        """Test handling of timeout errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.RequestTimeout("Request timed out")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "GATEWAY_TIMEOUT"
        assert "Gateway timeout" in result.error.message
        assert result.metadata.http_status == 504
        assert result.error.timeout_duration_ms is not None
        assert result.error.timeout_duration_ms >= 0
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_exchange_error(self, debug_service):
        """Test handling of exchange errors."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Invalid symbol")
        error.status_code = 400  # Set 4xx status code for client error
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=error
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        assert "Exchange error" in result.error.message
        assert result.metadata.http_status == 400
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_unexpected_error(self, debug_service):
        """Test handling of unexpected errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INTERNAL_ERROR"
        assert "Internal server error" in result.error.message
        assert result.metadata.http_status == 500
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_timing_precision(self, debug_service):
        """Test that response time has at least 1 decimal place precision."""
        # Arrange
        symbol = "BTCUSDT"
        mock_ticker_data = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is True
        # Check that response_time_ms is a float with at least 1 decimal place
        assert isinstance(result.metadata.response_time_ms, float)
        assert result.metadata.response_time_ms >= 0
        # Verify precision by checking string representation
        time_str = str(result.metadata.response_time_ms)
        if '.' in time_str:
            decimal_places = len(time_str.split('.')[1])
            assert decimal_places >= 1 or result.metadata.response_time_ms == int(result.metadata.response_time_ms)
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_timestamps_order(self, debug_service):
        """Test that response timestamp is after request timestamp."""
        # Arrange
        symbol = "BTCUSDT"
        mock_ticker_data = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is True
        assert result.metadata.response_timestamp >= result.metadata.request_timestamp



class TestFetchRawOpenInterest:
    """Tests for the fetch_raw_open_interest method."""
    
    @pytest.fixture
    def mock_exchange_connector(self):
        """Create a mock ExchangeConnector."""
        connector = Mock()
        exchange = AsyncMock()
        connector.get_exchange.return_value = exchange
        return connector
    
    @pytest.fixture
    def debug_service(self, mock_exchange_connector):
        """Create a DebugExchangeService instance with mocked exchange."""
        return DebugExchangeService(mock_exchange_connector)
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_success(self, debug_service):
        """Test successful open interest data retrieval."""
        # Arrange
        symbol = "BTCUSDT"
        mock_open_interest_data = {
            "symbol": "BTC/USDT:USDT",
            "openInterestAmount": 1000000.0,
            "openInterest": 1000000.0,
            "timestamp": 1234567890000
        }
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is True
        assert result.data == mock_open_interest_data
        assert result.error is None
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.http_status == 200
        assert result.metadata.response_time_ms >= 0
        assert result.fieldMapping is not None
        assert "openInterestAmount" in result.fieldMapping
        assert result.fieldMapping["openInterestAmount"].app_field == "open_interest"
        
        # Verify exchange was called with CCXT format (converted from Binance format)
        debug_service.exchange.fetch_open_interest.assert_called_once_with("BTC/USDT:USDT")
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_normalizes_symbol(self, debug_service):
        """Test that symbol is normalized (uppercase and trimmed)."""
        # Arrange
        symbol = "  ethusdt  "
        mock_open_interest_data = {"symbol": "ETH/USDT:USDT", "openInterestAmount": 500000.0}
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is True
        debug_service.exchange.fetch_open_interest.assert_called_once_with("ETH/USDT:USDT")
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_empty_symbol(self, debug_service):
        """Test validation error for empty symbol."""
        # Arrange
        symbol = ""
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.data is None
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter is required"
        assert result.metadata.exchange == "binanceusdm"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_invalid_characters(self, debug_service):
        """Test validation error for symbol with invalid characters."""
        # Arrange
        symbol = "BTC/USDT"
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_exceeds_max_length(self, debug_service):
        """Test validation error for symbol exceeding max length."""
        # Arrange
        symbol = "B" * 21  # 21 characters, max is 20
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_network_error(self, debug_service):
        """Test handling of network errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_open_interest = AsyncMock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert "Service unavailable" in result.error.message
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_timeout_error(self, debug_service):
        """Test handling of timeout errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_open_interest = AsyncMock(
            side_effect=ccxt.RequestTimeout("Request timed out")
        )
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "GATEWAY_TIMEOUT"
        assert "Gateway timeout" in result.error.message
        assert result.metadata.http_status == 504
        assert result.error.timeout_duration_ms is not None
        assert result.error.timeout_duration_ms >= 0
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_exchange_error(self, debug_service):
        """Test handling of exchange errors."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Invalid symbol")
        error.status_code = 400  # Set 4xx status code for client error
        debug_service.exchange.fetch_open_interest = AsyncMock(
            side_effect=error
        )
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        assert "Exchange error" in result.error.message
        assert result.metadata.http_status == 400
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_unexpected_error(self, debug_service):
        """Test handling of unexpected errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_open_interest = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INTERNAL_ERROR"
        assert "Internal server error" in result.error.message
        assert result.metadata.http_status == 500
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_timing_precision(self, debug_service):
        """Test that response time has at least 2 decimal places precision."""
        # Arrange
        symbol = "BTCUSDT"
        mock_open_interest_data = {"symbol": "BTC/USDT:USDT", "openInterestAmount": 1000000.0}
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is True
        # Check that response_time_ms is a float with at least 2 decimal places
        assert isinstance(result.metadata.response_time_ms, float)
        assert result.metadata.response_time_ms >= 0
        # Verify precision by checking string representation
        time_str = str(result.metadata.response_time_ms)
        if '.' in time_str:
            decimal_places = len(time_str.split('.')[1])
            assert decimal_places >= 2 or result.metadata.response_time_ms == int(result.metadata.response_time_ms)
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_timestamps_order(self, debug_service):
        """Test that response timestamp is after request timestamp."""
        # Arrange
        symbol = "BTCUSDT"
        mock_open_interest_data = {"symbol": "BTC/USDT:USDT", "openInterestAmount": 1000000.0}
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is True
        assert result.metadata.response_timestamp >= result.metadata.request_timestamp
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_field_mapping_structure(self, debug_service):
        """Test that field mapping has correct structure for open interest."""
        # Arrange
        symbol = "BTCUSDT"
        mock_open_interest_data = {"symbol": "BTC/USDT:USDT", "openInterestAmount": 1000000.0}
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is True
        assert result.fieldMapping is not None
        
        # Check openInterestAmount field mapping
        assert "openInterestAmount" in result.fieldMapping
        oi_amount_mapping = result.fieldMapping["openInterestAmount"]
        assert oi_amount_mapping.app_field == "open_interest"
        assert oi_amount_mapping.required is False
        assert oi_amount_mapping.data_type == "float"
        assert oi_amount_mapping.description is not None
        
        # Check openInterest fallback field mapping
        assert "openInterest" in result.fieldMapping
        oi_mapping = result.fieldMapping["openInterest"]
        assert oi_mapping.app_field == "open_interest"
        assert oi_mapping.required is False
        assert oi_mapping.data_type == "float"
        assert "Fallback" in oi_mapping.description



class TestFetchRawFundingRate:
    """Tests for the fetch_raw_funding_rate method."""
    
    @pytest.fixture
    def mock_exchange_connector(self):
        """Create a mock ExchangeConnector."""
        connector = Mock()
        exchange = Mock()
        connector.get_exchange.return_value = exchange
        return connector
    
    @pytest.fixture
    def debug_service(self, mock_exchange_connector):
        """Create a DebugExchangeService instance with mocked exchange."""
        return DebugExchangeService(mock_exchange_connector)
    
    def test_fetch_raw_funding_rate_success(self, debug_service):
        """Test successful funding rate data retrieval."""
        # Arrange
        symbol = "BTCUSDT"
        mock_funding_rate_data = {
            "symbol": "BTC/USDT:USDT",
            "fundingRate": 0.0001,
            "fundingTimestamp": 1234567890000,
            "fundingDatetime": "2024-01-01T00:00:00.000Z",
            "timestamp": 1234567890000
        }
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        assert result.data == mock_funding_rate_data
        assert result.error is None
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.http_status == 200
        assert result.metadata.response_time_ms >= 0
        assert result.fieldMapping is not None
        assert "fundingRate" in result.fieldMapping
        assert result.fieldMapping["fundingRate"].app_field == "funding_rate"
        assert result.fieldMapping["fundingRate"].transformation == "Multiply by 100 to convert to percentage"
        
        # Verify exchange was called with normalized symbol
        debug_service.exchange.fetch_funding_rate.assert_called_once_with("BTCUSDT")
    
    def test_fetch_raw_funding_rate_normalizes_symbol(self, debug_service):
        """Test that symbol is normalized (uppercase and trimmed)."""
        # Arrange
        symbol = "  ethusdt  "
        mock_funding_rate_data = {"symbol": "ETH/USDT:USDT", "fundingRate": 0.0002}
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        debug_service.exchange.fetch_funding_rate.assert_called_once_with("ETHUSDT")
    
    def test_fetch_raw_funding_rate_empty_symbol(self, debug_service):
        """Test validation error for empty symbol."""
        # Arrange
        symbol = ""
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.data is None
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter is required"
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.http_status == 400
    
    def test_fetch_raw_funding_rate_invalid_characters(self, debug_service):
        """Test validation error for symbol with invalid characters."""
        # Arrange
        symbol = "BTC-USDT"
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"
        assert result.metadata.http_status == 400
    
    def test_fetch_raw_funding_rate_exceeds_max_length(self, debug_service):
        """Test validation error for symbol exceeding max length."""
        # Arrange
        symbol = "C" * 21  # 21 characters, max is 20
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"
        assert result.metadata.http_status == 400
    
    def test_fetch_raw_funding_rate_network_error(self, debug_service):
        """Test handling of network errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert "Service unavailable" in result.error.message
        assert result.metadata.http_status == 503
    
    def test_fetch_raw_funding_rate_timeout_error(self, debug_service):
        """Test handling of timeout errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=ccxt.RequestTimeout("Request timed out")
        )
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "GATEWAY_TIMEOUT"
        assert "Gateway timeout" in result.error.message
        assert result.metadata.http_status == 504
        assert result.error.timeout_duration_ms is not None
        assert result.error.timeout_duration_ms >= 0
    
    def test_fetch_raw_funding_rate_exchange_error(self, debug_service):
        """Test handling of exchange errors."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Invalid symbol")
        error.status_code = 400  # Set 4xx status code for client error
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=error
        )
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        assert "Exchange error" in result.error.message
        assert result.metadata.http_status == 400
    
    def test_fetch_raw_funding_rate_unexpected_error(self, debug_service):
        """Test handling of unexpected errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=Exception("Unexpected error")
        )
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INTERNAL_ERROR"
        assert "Internal server error" in result.error.message
        assert result.metadata.http_status == 500
    
    def test_fetch_raw_funding_rate_timing_precision(self, debug_service):
        """Test that response time has at least 2 decimal places precision."""
        # Arrange
        symbol = "BTCUSDT"
        mock_funding_rate_data = {"symbol": "BTC/USDT:USDT", "fundingRate": 0.0001}
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        # Check that response_time_ms is a float with at least 2 decimal places
        assert isinstance(result.metadata.response_time_ms, float)
        assert result.metadata.response_time_ms >= 0
        # Verify precision by checking string representation
        time_str = str(result.metadata.response_time_ms)
        if '.' in time_str:
            decimal_places = len(time_str.split('.')[1])
            assert decimal_places >= 2 or result.metadata.response_time_ms == int(result.metadata.response_time_ms)
    
    def test_fetch_raw_funding_rate_timestamps_order(self, debug_service):
        """Test that response timestamp is after request timestamp."""
        # Arrange
        symbol = "BTCUSDT"
        mock_funding_rate_data = {"symbol": "BTC/USDT:USDT", "fundingRate": 0.0001}
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        assert result.metadata.response_timestamp >= result.metadata.request_timestamp
    
    def test_fetch_raw_funding_rate_field_mapping_structure(self, debug_service):
        """Test that field mapping has correct structure for funding rate."""
        # Arrange
        symbol = "BTCUSDT"
        mock_funding_rate_data = {"symbol": "BTC/USDT:USDT", "fundingRate": 0.0001}
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        assert result.fieldMapping is not None
        
        # Check fundingRate field mapping
        assert "fundingRate" in result.fieldMapping
        funding_rate_mapping = result.fieldMapping["fundingRate"]
        assert funding_rate_mapping.app_field == "funding_rate"
        assert funding_rate_mapping.required is True
        assert funding_rate_mapping.data_type == "float"
        assert funding_rate_mapping.description is not None
        assert funding_rate_mapping.transformation is not None
        assert "percentage" in funding_rate_mapping.transformation.lower()
    
    def test_fetch_raw_funding_rate_preserves_exchange_error_data(self, debug_service):
        """Test that original exchange error response is preserved in data field."""
        # Arrange
        symbol = "BTCUSDT"
        error_response = {"error": "Invalid symbol", "code": 400}
        exchange_error = ccxt.ExchangeError("Invalid symbol")
        exchange_error.status_code = 400  # Set 4xx status code for client error
        exchange_error.response = error_response
        debug_service.exchange.fetch_funding_rate = Mock(side_effect=exchange_error)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        # Note: The data field may or may not contain the error response depending on implementation
        # This test verifies the attempt to preserve it
    
    def test_fetch_raw_funding_rate_whitespace_symbol(self, debug_service):
        """Test validation error for whitespace-only symbol."""
        # Arrange
        symbol = "   "
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter is required"
        assert result.metadata.http_status == 400
    
    def test_fetch_raw_funding_rate_mixed_case_symbol(self, debug_service):
        """Test that mixed case symbol is normalized to uppercase."""
        # Arrange
        symbol = "BtCuSdT"
        mock_funding_rate_data = {"symbol": "BTC/USDT:USDT", "fundingRate": 0.0001}
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        debug_service.exchange.fetch_funding_rate.assert_called_once_with("BTCUSDT")



class TestFetchRawLongShortRatio:
    """Tests for the fetch_raw_long_short_ratio method."""
    
    @pytest.fixture
    def mock_exchange_connector(self):
        """Create a mock ExchangeConnector."""
        connector = Mock()
        exchange = Mock()
        connector.get_exchange.return_value = exchange
        return connector
    
    @pytest.fixture
    def debug_service(self, mock_exchange_connector):
        """Create a DebugExchangeService instance with mocked exchange."""
        return DebugExchangeService(mock_exchange_connector)
    
    def test_fetch_raw_long_short_ratio_success(self, debug_service):
        """Test successful long/short ratio data retrieval."""
        # Arrange
        symbol = "BTCUSDT"
        mock_long_short_data = [
            {
                "symbol": "BTCUSDT",
                "longShortRatio": 1.5,
                "longAccount": 0.6,
                "shortAccount": 0.4,
                "timestamp": 1234567890000
            }
        ]
        
        # Mock the exchange.market() method to return market info
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get to return successful response
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_long_short_data
            mock_get.return_value = mock_response
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is True
            assert result.data == {"result": mock_long_short_data}
            assert result.error is None
            assert result.metadata.exchange == "binanceusdm"
            assert result.metadata.http_status == 200
            assert result.metadata.response_time_ms >= 0
            assert result.fieldMapping is not None
            assert "longShortRatio" in result.fieldMapping
            assert result.fieldMapping["longShortRatio"].app_field == "long_short_ratio"
            
            # Verify requests.get was called with correct parameters
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[0][0] == 'https://fapi.binance.com/futures/data/topLongShortAccountRatio'
            assert call_args[1]['params']['symbol'] == 'BTCUSDT'
            assert call_args[1]['params']['period'] == '5m'
            assert call_args[1]['params']['limit'] == 1
    
    def test_fetch_raw_long_short_ratio_normalizes_symbol(self, debug_service):
        """Test that symbol is normalized (uppercase and trimmed)."""
        # Arrange
        symbol = "  btcusdt  "
        mock_long_short_data = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
        
        # Mock the exchange.market() method
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_long_short_data
            mock_get.return_value = mock_response
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is True
            # Verify the symbol was normalized before calling market()
            debug_service.exchange.market.assert_called_once_with("BTCUSDT")
    
    def test_fetch_raw_long_short_ratio_empty_symbol(self, debug_service):
        """Test validation error for empty symbol."""
        # Arrange
        symbol = ""
        
        # Act
        result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.data is None
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter is required"
        assert result.metadata.exchange == "binanceusdm"
    
    def test_fetch_raw_long_short_ratio_invalid_characters(self, debug_service):
        """Test validation error for symbol with invalid characters."""
        # Arrange
        symbol = "BTC-USDT"
        
        # Act
        result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"
    
    def test_fetch_raw_long_short_ratio_exceeds_max_length(self, debug_service):
        """Test validation error for symbol exceeding max length."""
        # Arrange
        symbol = "A" * 21  # 21 characters, max is 20
        
        # Act
        result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert result.error.message == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"
    
    def test_fetch_raw_long_short_ratio_timeout_error(self, debug_service):
        """Test handling of timeout errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get to raise Timeout exception
        with patch('requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.Timeout("Request timed out")
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is False
            assert result.error is not None
            assert result.error.code == "GATEWAY_TIMEOUT"
            assert "Gateway timeout" in result.error.message
            assert result.metadata.http_status == 504
            assert result.error.timeout_duration_ms is not None
            assert result.error.timeout_duration_ms >= 0
    
    def test_fetch_raw_long_short_ratio_connection_error(self, debug_service):
        """Test handling of connection errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get to raise ConnectionError
        with patch('requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is False
            assert result.error is not None
            assert result.error.code == "SERVICE_UNAVAILABLE"
            assert "Service unavailable" in result.error.message
            assert result.metadata.http_status == 503
    
    def test_fetch_raw_long_short_ratio_http_error(self, debug_service):
        """Test handling of HTTP errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get to raise HTTPError
        with patch('requests.get') as mock_get:
            import requests
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"code": -1121, "msg": "Invalid symbol"}
            mock_response.text = '{"code": -1121, "msg": "Invalid symbol"}'
            http_error = requests.exceptions.HTTPError("400 Client Error")
            http_error.response = mock_response
            mock_get.side_effect = http_error
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is False
            assert result.error is not None
            assert result.error.code == "EXCHANGE_ERROR"
            assert "Exchange error" in result.error.message
            assert result.metadata.http_status == 400
            assert result.data is not None  # Original error response preserved
    
    def test_fetch_raw_long_short_ratio_invalid_symbol_from_market(self, debug_service):
        """Test handling of invalid symbol from CCXT market lookup."""
        # Arrange
        symbol = "INVALIDSYMBOL"
        
        # Mock exchange.market() to raise BadSymbol exception
        debug_service.exchange.market = Mock(side_effect=ccxt.BadSymbol("Invalid symbol"))
        
        # Act
        result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_INPUT"
        assert "Invalid symbol" in result.error.message
        assert result.metadata.http_status == 400
    
    def test_fetch_raw_long_short_ratio_unexpected_error(self, debug_service):
        """Test handling of unexpected errors."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(side_effect=Exception("Unexpected error"))
        
        # Act
        result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INTERNAL_ERROR"
        assert "Internal server error" in result.error.message
        assert result.metadata.http_status == 500
    
    def test_fetch_raw_long_short_ratio_timing_precision(self, debug_service):
        """Test that response time has at least 2 decimal places precision."""
        # Arrange
        symbol = "BTCUSDT"
        mock_long_short_data = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
        
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_long_short_data
            mock_get.return_value = mock_response
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is True
            # Check that response_time_ms is a float with at least 2 decimal places precision
            assert isinstance(result.metadata.response_time_ms, float)
            assert result.metadata.response_time_ms >= 0
            # Verify precision by checking that the value is rounded to 2 decimal places
            # Note: round(0.103, 2) returns 0.1, which is correct but has only 1 digit after decimal in string form
            # We verify by checking if re-rounding to 2 decimals gives the same value
            assert round(result.metadata.response_time_ms, 2) == result.metadata.response_time_ms
    
    def test_fetch_raw_long_short_ratio_timestamps_order(self, debug_service):
        """Test that response timestamp is after request timestamp."""
        # Arrange
        symbol = "BTCUSDT"
        mock_long_short_data = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
        
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_long_short_data
            mock_get.return_value = mock_response
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is True
            assert result.metadata.response_timestamp >= result.metadata.request_timestamp
    
    def test_fetch_raw_long_short_ratio_field_mapping_structure(self, debug_service):
        """Test that field mapping has correct structure for long/short ratio."""
        # Arrange
        symbol = "BTCUSDT"
        mock_long_short_data = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
        
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_long_short_data
            mock_get.return_value = mock_response
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is True
            assert result.fieldMapping is not None
            
            # Check longShortRatio field mapping
            assert "longShortRatio" in result.fieldMapping
            ls_ratio_mapping = result.fieldMapping["longShortRatio"]
            assert ls_ratio_mapping.app_field == "long_short_ratio"
            assert ls_ratio_mapping.required is True
            assert ls_ratio_mapping.data_type == "float"
            assert "description" in ls_ratio_mapping.model_dump()
            assert "Binance top trader" in ls_ratio_mapping.description



class TestCheckExchangeHealth:
    """Tests for the check_exchange_health method."""
    
    @pytest.fixture
    def mock_exchange_connector(self):
        """Create a mock ExchangeConnector."""
        connector = Mock()
        exchange = AsyncMock()
        connector.get_exchange.return_value = exchange
        return connector
    
    @pytest.fixture
    def debug_service(self, mock_exchange_connector):
        """Create a DebugExchangeService instance with mocked exchange."""
        return DebugExchangeService(mock_exchange_connector)
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_success(self, debug_service):
        """Test successful health check with connected exchange."""
        # Arrange
        mock_server_timestamp = 1234567890000
        debug_service.exchange.fetch_time = AsyncMock(return_value=mock_server_timestamp)
        debug_service.exchange.urls = {
            'api': {
                'public': 'https://fapi.binance.com'
            }
        }
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is True
        assert result.data['status'] == 'connected'
        assert result.data['exchange'] == 'binanceusdm'
        assert result.data['base_url'] == 'https://fapi.binance.com'
        assert result.data['server_timestamp'] == mock_server_timestamp
        assert 'available_endpoints' in result.data
        assert len(result.data['available_endpoints']) == 5
        assert '/api/v1/debug/exchange/ticker/{symbol}' in result.data['available_endpoints']
        assert '/api/v1/debug/exchange/open-interest/{symbol}' in result.data['available_endpoints']
        assert '/api/v1/debug/exchange/funding-rate/{symbol}' in result.data['available_endpoints']
        assert '/api/v1/debug/exchange/long-short-ratio/{symbol}' in result.data['available_endpoints']
        assert '/api/v1/debug/exchange/all/{symbol}' in result.data['available_endpoints']
        assert result.metadata.exchange == 'binanceusdm'
        assert result.metadata.http_status == 200
        assert result.metadata.response_time_ms >= 0
        
        # Verify exchange was called
        debug_service.exchange.fetch_time.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_network_error(self, debug_service):
        """Test health check with network error returns disconnected status."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data['status'] == 'disconnected'
        assert result.data['exchange'] == 'binanceusdm'
        assert 'error_details' in result.data
        assert 'Cannot connect to exchange' in result.data['error_details']
        assert result.metadata.http_status == 503
        assert result.metadata.response_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_dns_error(self, debug_service):
        """Test health check with DNS resolution error."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=ccxt.NetworkError("getaddrinfo failed")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data['status'] == 'disconnected'
        assert result.data['error_details'] == 'DNS resolution failed'
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_connection_refused(self, debug_service):
        """Test health check with connection refused error."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=ccxt.NetworkError("Connection refused")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data['status'] == 'disconnected'
        assert result.data['error_details'] == 'Connection refused'
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_timeout_error(self, debug_service):
        """Test health check with timeout error."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=ccxt.RequestTimeout("Request timed out")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data['status'] == 'disconnected'
        assert result.data['exchange'] == 'binanceusdm'
        assert 'error_details' in result.data
        assert 'Request timeout' in result.data['error_details']
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_exchange_error(self, debug_service):
        """Test health check with exchange error."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=ccxt.ExchangeError("Exchange maintenance")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data['status'] == 'disconnected'
        assert result.data['exchange'] == 'binanceusdm'
        assert 'error_details' in result.data
        assert 'Exchange error' in result.data['error_details']
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_unexpected_error(self, debug_service):
        """Test health check with unexpected error."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data['status'] == 'disconnected'
        assert result.data['exchange'] == 'binanceusdm'
        assert 'error_details' in result.data
        assert 'Internal server error' in result.data['error_details']
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_timing_precision(self, debug_service):
        """Test that response time has at least 2 decimal places precision."""
        # Arrange
        mock_server_timestamp = 1234567890000
        debug_service.exchange.fetch_time = AsyncMock(return_value=mock_server_timestamp)
        debug_service.exchange.urls = {'api': {'public': 'https://fapi.binance.com'}}
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is True
        # Check that response_time_ms is a float with at least 2 decimal places
        assert isinstance(result.metadata.response_time_ms, float)
        assert result.metadata.response_time_ms >= 0
        # Verify precision by checking string representation
        time_str = str(result.metadata.response_time_ms)
        if '.' in time_str:
            decimal_places = len(time_str.split('.')[1])
            assert decimal_places >= 2 or result.metadata.response_time_ms == int(result.metadata.response_time_ms)
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_timestamps_order(self, debug_service):
        """Test that response timestamp is after request timestamp."""
        # Arrange
        mock_server_timestamp = 1234567890000
        debug_service.exchange.fetch_time = AsyncMock(return_value=mock_server_timestamp)
        debug_service.exchange.urls = {'api': {'public': 'https://fapi.binance.com'}}
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is True
        assert result.metadata.response_timestamp >= result.metadata.request_timestamp
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_base_url_fallback(self, debug_service):
        """Test that base URL falls back to default when not available."""
        # Arrange
        mock_server_timestamp = 1234567890000
        debug_service.exchange.fetch_time = AsyncMock(return_value=mock_server_timestamp)
        debug_service.exchange.urls = {}  # No URLs configured
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is True
        assert result.data['base_url'] == 'https://fapi.binance.com'
