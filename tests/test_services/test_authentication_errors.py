"""
Unit tests for authentication error handling in DebugExchangeService.

Tests that all methods properly handle authentication errors (HTTP 401)
when authentication is enabled and credentials are invalid or missing.
"""

import pytest
from unittest.mock import AsyncMock, Mock
from datetime import datetime
import ccxt
import requests

from src.services.debug_exchange_service import DebugExchangeService
from src.api.debug_models import DebugResponse, HealthCheckResponse


class TestAuthenticationErrorHandling:
    """Tests for authentication error handling across all debug service methods."""
    
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
    async def test_fetch_raw_ticker_authentication_error(self, debug_service):
        """Test that fetch_raw_ticker handles authentication errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.AuthenticationError("API key invalid")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "UNAUTHORIZED"
        assert result.error.message == "Authentication required"
        assert result.metadata.http_status == 401
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.response_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_authentication_error(self, debug_service):
        """Test that fetch_raw_open_interest handles authentication errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_open_interest = AsyncMock(
            side_effect=ccxt.AuthenticationError("Authentication failed")
        )
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "UNAUTHORIZED"
        assert result.error.message == "Authentication required"
        assert result.metadata.http_status == 401
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.response_time_ms >= 0
    
    def test_fetch_raw_funding_rate_authentication_error(self, debug_service):
        """Test that fetch_raw_funding_rate handles authentication errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=ccxt.AuthenticationError("Invalid API credentials")
        )
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "UNAUTHORIZED"
        assert result.error.message == "Authentication required"
        assert result.metadata.http_status == 401
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.response_time_ms >= 0
    
    def test_fetch_raw_long_short_ratio_authentication_error_from_ccxt(self, debug_service):
        """Test that fetch_raw_long_short_ratio handles CCXT authentication errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        # Mock the market lookup to raise AuthenticationError
        debug_service.exchange.market = Mock(
            side_effect=ccxt.AuthenticationError("API key required")
        )
        
        # Act
        result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "UNAUTHORIZED"
        assert result.error.message == "Authentication required"
        assert result.metadata.http_status == 401
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.response_time_ms >= 0
    
    @pytest.mark.parametrize("http_status_code", [401])
    def test_fetch_raw_long_short_ratio_authentication_error_from_http(self, debug_service, http_status_code):
        """Test that fetch_raw_long_short_ratio handles HTTP 401 errors correctly."""
        # Arrange
        symbol = "BTCUSDT"
        
        # Mock the market lookup to succeed
        debug_service.exchange.market = Mock(return_value={'id': 'BTCUSDT'})
        
        # Mock requests.get to raise HTTPError with 401 status
        mock_response = Mock()
        mock_response.status_code = http_status_code
        mock_response.json.return_value = {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}
        
        http_error = requests.exceptions.HTTPError("401 Client Error: Unauthorized")
        http_error.response = mock_response
        
        from unittest.mock import patch
        with patch('requests.get', side_effect=http_error):
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "UNAUTHORIZED"
        assert result.error.message == "Authentication required"
        assert result.metadata.http_status == 401
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.response_time_ms >= 0
        # Verify that original error data is preserved
        assert result.data is not None
        assert "code" in result.data or "msg" in result.data
    
    @pytest.mark.asyncio
    async def test_check_exchange_health_authentication_error(self, debug_service):
        """Test that check_exchange_health handles authentication errors correctly."""
        # Arrange
        debug_service.exchange.fetch_time = AsyncMock(
            side_effect=ccxt.AuthenticationError("Authentication required for this endpoint")
        )
        
        # Act
        result = await debug_service.check_exchange_health()
        
        # Assert
        assert result.success is False
        assert result.data is not None
        assert result.data["status"] == "disconnected"
        assert result.data["exchange"] == "binanceusdm"
        assert result.data["error_details"] == "Authentication required"
        assert result.metadata.http_status == 401
        assert result.metadata.exchange == "binanceusdm"
        assert result.metadata.response_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_authentication_error_takes_precedence_over_network_error(self, debug_service):
        """Test that AuthenticationError is caught before NetworkError (since it's a subclass)."""
        # Arrange
        symbol = "BTCUSDT"
        # AuthenticationError is a subclass of ExchangeError, which is a subclass of BaseError
        # We need to ensure it's caught before more general exceptions
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.AuthenticationError("Invalid credentials")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        # Should be caught as UNAUTHORIZED, not as a more general error
        assert result.error.code == "UNAUTHORIZED"
        assert result.metadata.http_status == 401
    
    @pytest.mark.asyncio
    async def test_authentication_error_logging(self, debug_service, caplog):
        """Test that authentication errors are properly logged."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.AuthenticationError("API key missing")
        )
        
        # Act
        with caplog.at_level("ERROR"):
            result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.error.code == "UNAUTHORIZED"
        # Check that error was logged
        assert any("Authentication error" in record.message for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_authentication_error_response_structure(self, debug_service):
        """Test that authentication error responses have the correct structure."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.AuthenticationError("Invalid API key")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        # Verify response structure matches DebugResponse model
        assert isinstance(result, DebugResponse)
        assert hasattr(result, 'success')
        assert hasattr(result, 'error')
        assert hasattr(result, 'metadata')
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "UNAUTHORIZED"
        assert result.error.message == "Authentication required"
        assert result.metadata.http_status == 401
        # Verify timestamps are present and valid
        assert result.metadata.request_timestamp is not None
        assert result.metadata.response_timestamp is not None
        assert result.metadata.response_timestamp >= result.metadata.request_timestamp
