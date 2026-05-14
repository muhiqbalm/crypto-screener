"""
Unit tests for task 3.6: Verify aggregated endpoint handles both symbol formats.

Tests that fetch_all_raw_data() correctly handles both CCXT unified format
(BTC/USDT:USDT) and Binance native format (BTCUSDT) by delegating format
conversion to individual fetch methods.

**Validates: Requirements 2.5**
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime

from src.services.debug_exchange_service import DebugExchangeService
from src.api.debug_models import AggregatedDebugResponse


class TestAggregatedEndpointFormatHandling:
    """Tests for aggregated endpoint with both symbol formats."""
    
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
    async def test_aggregated_endpoint_with_binance_format(self, debug_service):
        """
        Test that aggregated endpoint works with Binance native format (BTCUSDT).
        
        The individual fetch methods should convert BTCUSDT to BTC/USDT:USDT
        for ticker and open interest endpoints.
        """
        # Arrange
        symbol = "BTCUSDT"
        
        mock_ticker_data = {
            "symbol": "BTC/USDT:USDT",
            "last": 50000.0,
            "percentage": 2.5,
            "quoteVolume": 1000000.0
        }
        
        mock_open_interest_data = {
            "symbol": "BTC/USDT:USDT",
            "openInterestAmount": 1000000.0
        }
        
        mock_funding_rate_data = {
            "symbol": "BTC/USDT:USDT",
            "fundingRate": 0.0001
        }
        
        # Mock the exchange methods
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get for long/short ratio
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
            mock_get.return_value = mock_response
            
            # Act
            result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        assert isinstance(result, AggregatedDebugResponse)
        assert result.success is True
        
        # Verify all data types succeeded
        assert result.data["ticker"].success is True
        assert result.data["openInterest"].success is True
        assert result.data["fundingRate"].success is True
        assert result.data["longShortRatio"].success is True
        
        # Verify ticker and open interest were called with CCXT format (BTC/USDT:USDT)
        # after conversion from Binance format (BTCUSDT)
        debug_service.exchange.fetch_ticker.assert_called_once_with("BTC/USDT:USDT")
        debug_service.exchange.fetch_open_interest.assert_called_once_with("BTC/USDT:USDT")
        
        # Verify funding rate and long/short ratio were called with original format
        # (they handle format internally or use market lookup)
        debug_service.exchange.fetch_funding_rate.assert_called_once_with("BTCUSDT")
        debug_service.exchange.market.assert_called_once_with("BTCUSDT")
    
    @pytest.mark.asyncio
    async def test_aggregated_endpoint_with_ccxt_format(self, debug_service):
        """
        Test that aggregated endpoint works with CCXT unified format (BTC/USDT:USDT).
        
        The individual fetch methods should accept CCXT format directly without
        conversion for ticker and open interest endpoints.
        """
        # Arrange
        symbol = "BTC/USDT:USDT"
        
        mock_ticker_data = {
            "symbol": "BTC/USDT:USDT",
            "last": 50000.0,
            "percentage": 2.5,
            "quoteVolume": 1000000.0
        }
        
        mock_open_interest_data = {
            "symbol": "BTC/USDT:USDT",
            "openInterestAmount": 1000000.0
        }
        
        mock_funding_rate_data = {
            "symbol": "BTC/USDT:USDT",
            "fundingRate": 0.0001
        }
        
        # Mock the exchange methods
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        # Mock requests.get for long/short ratio
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
            mock_get.return_value = mock_response
            
            # Act
            result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        assert isinstance(result, AggregatedDebugResponse)
        assert result.success is True
        
        # Verify all data types succeeded
        assert result.data["ticker"].success is True
        assert result.data["openInterest"].success is True
        assert result.data["fundingRate"].success is True
        assert result.data["longShortRatio"].success is True
        
        # Verify ticker and open interest were called with CCXT format (unchanged)
        debug_service.exchange.fetch_ticker.assert_called_once_with("BTC/USDT:USDT")
        debug_service.exchange.fetch_open_interest.assert_called_once_with("BTC/USDT:USDT")
        
        # Verify funding rate was called with CCXT format (CCXT handles it internally)
        debug_service.exchange.fetch_funding_rate.assert_called_once_with("BTC/USDT:USDT")
        
        # Verify long/short ratio was called with CCXT format
        debug_service.exchange.market.assert_called_once_with("BTC/USDT:USDT")
    
    @pytest.mark.asyncio
    async def test_aggregated_endpoint_response_structure_unchanged(self, debug_service):
        """
        Test that response structure remains unchanged regardless of input format.
        
        This verifies the preservation requirement that response structure and
        timing behavior should remain unchanged.
        """
        # Arrange
        binance_symbol = "ETHUSDT"
        ccxt_symbol = "ETH/USDT:USDT"
        
        mock_ticker_data = {
            "symbol": "ETH/USDT:USDT",
            "last": 3000.0,
            "percentage": 1.5,
            "quoteVolume": 500000.0
        }
        
        mock_open_interest_data = {
            "symbol": "ETH/USDT:USDT",
            "openInterestAmount": 500000.0
        }
        
        mock_funding_rate_data = {
            "symbol": "ETH/USDT:USDT",
            "fundingRate": 0.0002
        }
        
        # Mock the exchange methods
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        debug_service.exchange.market = Mock(return_value={"id": "ETHUSDT"})
        
        # Mock requests.get for long/short ratio
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"symbol": "ETHUSDT", "longShortRatio": 1.2}]
            mock_get.return_value = mock_response
            
            # Act - Test with Binance format
            result_binance = await debug_service.fetch_all_raw_data(binance_symbol)
            
            # Reset mocks
            debug_service.exchange.fetch_ticker.reset_mock()
            debug_service.exchange.fetch_open_interest.reset_mock()
            debug_service.exchange.fetch_funding_rate.reset_mock()
            debug_service.exchange.market.reset_mock()
            mock_get.reset_mock()
            
            # Act - Test with CCXT format
            result_ccxt = await debug_service.fetch_all_raw_data(ccxt_symbol)
        
        # Assert - Both results should have the same structure
        assert isinstance(result_binance, AggregatedDebugResponse)
        assert isinstance(result_ccxt, AggregatedDebugResponse)
        
        # Check that both have the same top-level keys
        assert set(result_binance.data.keys()) == set(result_ccxt.data.keys())
        assert set(result_binance.metadata.keys()) == set(result_ccxt.metadata.keys())
        assert set(result_binance.fieldMapping.keys()) == set(result_ccxt.fieldMapping.keys())
        
        # Check that metadata structure is identical
        assert "request_timestamp" in result_binance.metadata
        assert "response_timestamp" in result_binance.metadata
        assert "total_response_time_ms" in result_binance.metadata
        assert "individual_timings" in result_binance.metadata
        
        assert "request_timestamp" in result_ccxt.metadata
        assert "response_timestamp" in result_ccxt.metadata
        assert "total_response_time_ms" in result_ccxt.metadata
        assert "individual_timings" in result_ccxt.metadata
        
        # Check that individual timings have the same keys
        assert set(result_binance.metadata["individual_timings"].keys()) == \
               set(result_ccxt.metadata["individual_timings"].keys())
    
    @pytest.mark.asyncio
    async def test_aggregated_endpoint_with_invalid_symbol_both_formats(self, debug_service):
        """
        Test that invalid symbols are rejected consistently regardless of format.
        
        This verifies the preservation requirement that invalid symbols should
        continue to be rejected with appropriate error messages.
        """
        # Arrange
        invalid_symbols = [
            "",  # Empty string
            "   ",  # Whitespace only
            "BTC@USDT",  # Invalid special character
            "BTC//USDT:USDT",  # Malformed CCXT format
            "BTC:USDT/USDT",  # Malformed CCXT format (wrong order)
        ]
        
        # Act & Assert
        for invalid_symbol in invalid_symbols:
            result = await debug_service.fetch_all_raw_data(invalid_symbol)
            
            # All should fail validation
            assert result.success is False
            
            # All data types should have validation errors
            assert result.data["ticker"].success is False
            assert result.data["openInterest"].success is False
            assert result.data["fundingRate"].success is False
            assert result.data["longShortRatio"].success is False
            
            assert result.data["ticker"].error.code == "INVALID_INPUT"
            assert result.data["openInterest"].error.code == "INVALID_INPUT"
            assert result.data["fundingRate"].error.code == "INVALID_INPUT"
            assert result.data["longShortRatio"].error.code == "INVALID_INPUT"
