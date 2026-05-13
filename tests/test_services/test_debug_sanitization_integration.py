"""
Integration tests for response sanitization in DebugExchangeService.

Tests that sensitive fields are properly filtered from actual debug API responses.
"""

import pytest
from unittest.mock import AsyncMock, Mock
from src.services.debug_exchange_service import DebugExchangeService


class TestDebugSanitizationIntegration:
    """Integration tests for sanitization in debug responses."""
    
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
    async def test_ticker_response_sanitizes_api_key(self, debug_service):
        """Test that API key in ticker response is sanitized."""
        # Arrange - mock ticker data with sensitive field
        symbol = "BTCUSDT"
        mock_ticker_data = {
            "symbol": "BTC/USDT:USDT",
            "last": 50000.0,
            "percentage": 2.5,
            "quoteVolume": 1000000.0,
            "apiKey": "secret-api-key-12345",  # Sensitive field
            "info": {
                "secret": "secret-value",  # Nested sensitive field
                "price": 50000.0
            }
        }
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is True
        assert result.data["symbol"] == "BTC/USDT:USDT"
        assert result.data["last"] == 50000.0
        assert result.data["percentage"] == 2.5
        assert result.data["quoteVolume"] == 1000000.0
        
        # Sensitive fields should be redacted
        assert result.data["apiKey"] == "[REDACTED]"
        assert result.data["info"]["secret"] == "[REDACTED]"
        assert result.data["info"]["price"] == 50000.0  # Non-sensitive field preserved
    
    @pytest.mark.asyncio
    async def test_open_interest_response_sanitizes_token(self, debug_service):
        """Test that token in open interest response is sanitized."""
        # Arrange
        symbol = "BTCUSDT"
        mock_oi_data = {
            "symbol": "BTC/USDT:USDT",
            "openInterestAmount": 1000000.0,
            "token": "bearer-token-xyz",  # Sensitive field
            "accessToken": "access-token-abc"  # Sensitive field
        }
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_oi_data)
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is True
        assert result.data["symbol"] == "BTC/USDT:USDT"
        assert result.data["openInterestAmount"] == 1000000.0
        
        # Sensitive fields should be redacted
        assert result.data["token"] == "[REDACTED]"
        assert result.data["accessToken"] == "[REDACTED]"
    
    def test_funding_rate_response_sanitizes_password(self, debug_service):
        """Test that password in funding rate response is sanitized."""
        # Arrange
        symbol = "BTCUSDT"
        mock_fr_data = {
            "symbol": "BTC/USDT:USDT",
            "fundingRate": 0.0001,
            "password": "my-password-123",  # Sensitive field
            "credentials": {
                "privateKey": "private-key-value"  # Sensitive field
            }
        }
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_fr_data)
        
        # Act
        result = debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is True
        assert result.data["symbol"] == "BTC/USDT:USDT"
        assert result.data["fundingRate"] == 0.0001
        
        # Sensitive fields should be redacted
        assert result.data["password"] == "[REDACTED]"
        assert result.data["credentials"]["privateKey"] == "[REDACTED]"
    
    def test_long_short_ratio_response_sanitizes_nested_secrets(self, debug_service):
        """Test that nested secrets in long/short ratio response are sanitized."""
        # Arrange
        symbol = "BTCUSDT"
        
        # Mock the market lookup
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock the requests.get call
        import requests
        from unittest.mock import patch
        
        mock_response_data = [
            {
                "symbol": "BTCUSDT",
                "longShortRatio": 1.5,
                "apiSecret": "secret-123",  # Sensitive field
                "auth": {
                    "apiKey": "key-456",  # Sensitive field
                    "username": "trader"
                }
            }
        ]
        
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            # Act
            result = debug_service.fetch_raw_long_short_ratio(symbol)
        
        # Assert
        assert result.success is True
        assert "result" in result.data
        assert len(result.data["result"]) == 1
        assert result.data["result"][0]["symbol"] == "BTCUSDT"
        assert result.data["result"][0]["longShortRatio"] == 1.5
        
        # Sensitive fields should be redacted
        assert result.data["result"][0]["apiSecret"] == "[REDACTED]"
        assert result.data["result"][0]["auth"]["apiKey"] == "[REDACTED]"
        assert result.data["result"][0]["auth"]["username"] == "trader"  # Non-sensitive preserved
    
    @pytest.mark.asyncio
    async def test_error_response_sanitizes_sensitive_data(self, debug_service):
        """Test that sensitive data in error responses is sanitized."""
        # Arrange
        symbol = "BTCUSDT"
        
        # Create a mock exception with response containing sensitive data
        import ccxt
        mock_error = ccxt.ExchangeError("Exchange error")
        mock_error.status_code = 400  # Set status code to get EXCHANGE_ERROR instead of EXCHANGE_SERVER_ERROR
        mock_error.response = {
            "error": "Invalid request",
            "apiKey": "leaked-api-key",  # Sensitive field
            "details": {
                "secret": "leaked-secret"  # Sensitive field
            }
        }
        
        debug_service.exchange.fetch_ticker = AsyncMock(side_effect=mock_error)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "EXCHANGE_ERROR"
        
        # Error data should be preserved but sanitized
        assert result.data is not None
        assert result.data["error"] == "Invalid request"
        assert result.data["apiKey"] == "[REDACTED]"
        assert result.data["details"]["secret"] == "[REDACTED]"
    
    @pytest.mark.asyncio
    async def test_multiple_sensitive_fields_all_redacted(self, debug_service):
        """Test that multiple different sensitive fields are all redacted."""
        # Arrange
        symbol = "BTCUSDT"
        mock_ticker_data = {
            "symbol": "BTC/USDT:USDT",
            "last": 50000.0,
            "apiKey": "key-1",
            "api_key": "key-2",
            "secret": "secret-1",
            "apiSecret": "secret-2",
            "password": "pass-1",
            "token": "token-1",
            "accessToken": "token-2",
            "privateKey": "private-1",
            "credential": "cred-1"
        }
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is True
        assert result.data["symbol"] == "BTC/USDT:USDT"
        assert result.data["last"] == 50000.0
        
        # All sensitive fields should be redacted
        assert result.data["apiKey"] == "[REDACTED]"
        assert result.data["api_key"] == "[REDACTED]"
        assert result.data["secret"] == "[REDACTED]"
        assert result.data["apiSecret"] == "[REDACTED]"
        assert result.data["password"] == "[REDACTED]"
        assert result.data["token"] == "[REDACTED]"
        assert result.data["accessToken"] == "[REDACTED]"
        assert result.data["privateKey"] == "[REDACTED]"
        assert result.data["credential"] == "[REDACTED]"
