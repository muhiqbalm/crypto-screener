"""
Tests for exchange server error handling (HTTP 5xx).

This module tests that the debug exchange service correctly handles
HTTP 5xx server errors from the exchange, distinguishing them from
4xx client errors.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import ccxt
from src.services.debug_exchange_service import DebugExchangeService
from src.exchange.connector import ExchangeConnector


@pytest.fixture
def mock_exchange():
    """Create a mock exchange instance."""
    exchange = Mock()
    exchange.fetch_ticker = Mock()
    exchange.fetch_open_interest = Mock()
    exchange.fetch_funding_rate = Mock()
    exchange.fetch_time = AsyncMock()
    exchange.market = Mock()
    return exchange


@pytest.fixture
def debug_service(mock_exchange):
    """Create a DebugExchangeService instance with mocked exchange."""
    connector = Mock(spec=ExchangeConnector)
    connector.get_exchange.return_value = mock_exchange
    service = DebugExchangeService(connector)
    return service


class TestExchangeServerErrorHandling:
    """Test suite for exchange server error (5xx) handling."""
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_server_error_5xx(self, debug_service):
        """Test that 5xx errors return EXCHANGE_SERVER_ERROR code."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Internal server error")
        error.status_code = 500
        error.response = {"error": "Internal server error", "code": 500}
        debug_service.exchange.fetch_ticker = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_SERVER_ERROR"
        assert "Exchange server error" in result.error.message
        assert result.metadata.http_status == 500
        assert result.data == {"error": "Internal server error", "code": 500}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_client_error_4xx(self, debug_service):
        """Test that 4xx errors return EXCHANGE_ERROR code."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Invalid symbol")
        error.status_code = 400
        error.response = {"error": "Invalid symbol", "code": 400}
        debug_service.exchange.fetch_ticker = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        assert "Exchange error" in result.error.message
        assert result.metadata.http_status == 400
        assert result.data == {"error": "Invalid symbol", "code": 400}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_server_error_503(self, debug_service):
        """Test that 503 Service Unavailable returns EXCHANGE_SERVER_ERROR code."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Service unavailable")
        error.status_code = 503
        error.response = {"error": "Service unavailable", "code": 503}
        debug_service.exchange.fetch_ticker = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_SERVER_ERROR"
        assert "Exchange server error" in result.error.message
        assert result.metadata.http_status == 503
        assert result.data == {"error": "Service unavailable", "code": 503}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_server_error_5xx(self, debug_service):
        """Test that open interest endpoint handles 5xx errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Internal server error")
        error.status_code = 502
        error.response = {"error": "Bad gateway", "code": 502}
        debug_service.exchange.fetch_open_interest = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_SERVER_ERROR"
        assert "Exchange server error" in result.error.message
        assert result.metadata.http_status == 502
        assert result.data == {"error": "Bad gateway", "code": 502}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_client_error_4xx(self, debug_service):
        """Test that open interest endpoint handles 4xx errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Rate limit exceeded")
        error.status_code = 429
        error.response = {"error": "Rate limit exceeded", "code": 429}
        debug_service.exchange.fetch_open_interest = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        assert "Exchange error" in result.error.message
        assert result.metadata.http_status == 429
        assert result.data == {"error": "Rate limit exceeded", "code": 429}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_funding_rate_server_error_5xx(self, debug_service):
        """Test that funding rate endpoint handles 5xx errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Gateway timeout")
        error.status_code = 504
        error.response = {"error": "Gateway timeout", "code": 504}
        debug_service.exchange.fetch_funding_rate = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_SERVER_ERROR"
        assert "Exchange server error" in result.error.message
        assert result.metadata.http_status == 504
        assert result.data == {"error": "Gateway timeout", "code": 504}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_funding_rate_client_error_4xx(self, debug_service):
        """Test that funding rate endpoint handles 4xx errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Invalid symbol")
        error.status_code = 404
        error.response = {"error": "Symbol not found", "code": 404}
        debug_service.exchange.fetch_funding_rate = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        assert "Exchange error" in result.error.message
        assert result.metadata.http_status == 404
        assert result.data == {"error": "Symbol not found", "code": 404}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_long_short_ratio_server_error_5xx(self, debug_service):
        """Test that long/short ratio endpoint handles 5xx errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            import requests
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.json.return_value = {"error": "Internal server error", "code": 500}
            mock_response.text = '{"error": "Internal server error", "code": 500}'
            
            http_error = requests.exceptions.HTTPError("500 Server Error")
            http_error.response = mock_response
            mock_get.side_effect = http_error
            
            # Act
            result = await debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is False
            assert result.error is not None
            assert result.error.code == "EXCHANGE_SERVER_ERROR"
            assert "Exchange server error" in result.error.message
            assert result.metadata.http_status == 500
            assert result.data == {"error": "Internal server error", "code": 500}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_long_short_ratio_client_error_4xx(self, debug_service):
        """Test that long/short ratio endpoint handles 4xx errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            import requests
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"error": "Invalid symbol", "code": 400}
            mock_response.text = '{"error": "Invalid symbol", "code": 400}'
            
            http_error = requests.exceptions.HTTPError("400 Bad Request")
            http_error.response = mock_response
            mock_get.side_effect = http_error
            
            # Act
            result = await debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is False
            assert result.error is not None
            assert result.error.code == "EXCHANGE_ERROR"
            assert "Exchange error" in result.error.message
            assert result.metadata.http_status == 400
            assert result.data == {"error": "Invalid symbol", "code": 400}
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_server_error_without_status_code(self, debug_service):
        """Test that errors without status_code attribute default to 502 and use EXCHANGE_ERROR."""
        # Arrange
        symbol = "BTCUSDT"
        error = ccxt.ExchangeError("Unknown error")
        # Don't set status_code attribute
        debug_service.exchange.fetch_ticker = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        # Default status is 502, which is >= 500, so should be EXCHANGE_SERVER_ERROR
        assert result.error.code == "EXCHANGE_SERVER_ERROR"
        assert result.metadata.http_status == 502
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_preserves_original_error_response(self, debug_service):
        """Test that original exchange error response is preserved in data field."""
        # Arrange
        symbol = "BTCUSDT"
        original_error_data = {
            "error": "Internal server error",
            "code": 500,
            "message": "Database connection failed",
            "timestamp": 1234567890
        }
        error = ccxt.ExchangeError("Internal server error")
        error.status_code = 500
        error.response = original_error_data
        debug_service.exchange.fetch_ticker = Mock(side_effect=error)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.data == original_error_data
        assert result.error.code == "EXCHANGE_SERVER_ERROR"
