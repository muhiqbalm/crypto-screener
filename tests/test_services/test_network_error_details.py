"""
Tests for network error details extraction in debug exchange service.

This module tests that connectivity errors (HTTP 503) include specific details
about the type of error (DNS resolution failed, connection refused, etc.).
"""

import pytest
import ccxt
import requests
from unittest.mock import Mock, AsyncMock
from src.services.debug_exchange_service import DebugExchangeService, _extract_network_error_details
from src.exchange.connector import ExchangeConnector


class TestNetworkErrorDetails:
    """Test suite for network error details extraction."""
    
    @pytest.fixture
    def debug_service(self):
        """Create a DebugExchangeService instance for testing."""
        connector = Mock(spec=ExchangeConnector)
        connector.get_exchange.return_value = Mock()
        return DebugExchangeService(connector)
    
    def test_extract_dns_error_details(self):
        """Test that DNS resolution errors are correctly identified."""
        error = ccxt.NetworkError("getaddrinfo failed")
        details = _extract_network_error_details(error)
        assert details == "DNS resolution failed"
    
    def test_extract_connection_refused_details(self):
        """Test that connection refused errors are correctly identified."""
        error = ccxt.NetworkError("Connection refused")
        details = _extract_network_error_details(error)
        assert details == "Connection refused"
    
    def test_extract_network_unreachable_details(self):
        """Test that network unreachable errors are correctly identified."""
        error = ccxt.NetworkError("Network unreachable")
        details = _extract_network_error_details(error)
        assert details == "Network unreachable"
    
    def test_extract_timeout_details(self):
        """Test that timeout errors are correctly identified."""
        error = ccxt.NetworkError("Connection timed out")
        details = _extract_network_error_details(error)
        assert details == "Connection timeout"
    
    def test_extract_generic_network_error_details(self):
        """Test that generic network errors default to 'Cannot connect to exchange'."""
        error = ccxt.NetworkError("Some unknown network error")
        details = _extract_network_error_details(error)
        assert details == "Cannot connect to exchange"
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_includes_dns_error_details(self, debug_service):
        """Test that fetch_raw_ticker includes DNS error details in response."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = Mock(
            side_effect=ccxt.NetworkError("getaddrinfo failed")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert result.error.details == "DNS resolution failed"
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_fetch_raw_ticker_includes_connection_refused_details(self, debug_service):
        """Test that fetch_raw_ticker includes connection refused details in response."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_ticker = Mock(
            side_effect=ccxt.NetworkError("Connection refused")
        )
        
        # Act
        result = await debug_service.fetch_raw_ticker(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert result.error.details == "Connection refused"
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_fetch_raw_open_interest_includes_error_details(self, debug_service):
        """Test that fetch_raw_open_interest includes error details in response."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_open_interest = Mock(
            side_effect=ccxt.NetworkError("getaddrinfo failed")
        )
        
        # Act
        result = await debug_service.fetch_raw_open_interest(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert result.error.details == "DNS resolution failed"
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_fetch_raw_funding_rate_includes_error_details(self, debug_service):
        """Test that fetch_raw_funding_rate includes error details in response."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=ccxt.NetworkError("Connection refused")
        )
        
        # Act
        result = await debug_service.fetch_raw_funding_rate(symbol)
        
        # Assert
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "SERVICE_UNAVAILABLE"
        assert result.error.details == "Connection refused"
        assert result.metadata.http_status == 503
    
    @pytest.mark.asyncio
    async def test_fetch_raw_long_short_ratio_includes_error_details(self, debug_service):
        """Test that fetch_raw_long_short_ratio includes error details in response."""
        # Arrange
        symbol = "BTCUSDT"
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get to raise ConnectionError
        from unittest.mock import patch
        with patch('requests.get', side_effect=requests.exceptions.ConnectionError("Connection refused")):
            # Act
            result = await debug_service.fetch_raw_long_short_ratio(symbol)
            
            # Assert
            assert result.success is False
            assert result.error is not None
            assert result.error.code == "SERVICE_UNAVAILABLE"
            assert result.error.details == "Connection refused"
            assert result.metadata.http_status == 503
