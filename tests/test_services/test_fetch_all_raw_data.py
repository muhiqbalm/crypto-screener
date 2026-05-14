"""
Unit tests for DebugExchangeService.fetch_all_raw_data method.

Tests the aggregated data fetching with concurrent execution.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
import ccxt

from src.services.debug_exchange_service import DebugExchangeService
from src.api.debug_models import DebugResponse, ErrorInfo, AggregatedDebugResponse, DataTypeResult


class TestFetchAllRawData:
    """Tests for the fetch_all_raw_data method."""
    
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
    async def test_fetch_all_raw_data_success(self, debug_service):
        """Test successful retrieval of all data types."""
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
        
        mock_long_short_ratio_data = {
            "result": [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
        }
        
        # Mock the individual fetch methods
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        
        # Mock the market lookup for long/short ratio
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
        
        # Check that all four data types are present
        assert "ticker" in result.data
        assert "openInterest" in result.data
        assert "fundingRate" in result.data
        assert "longShortRatio" in result.data
        
        # Check that all data types succeeded
        assert result.data["ticker"].success is True
        assert result.data["openInterest"].success is True
        assert result.data["fundingRate"].success is True
        assert result.data["longShortRatio"].success is True
        
        # Check that data is present
        assert result.data["ticker"].data == mock_ticker_data
        assert result.data["openInterest"].data == mock_open_interest_data
        assert result.data["fundingRate"].data == mock_funding_rate_data
        assert result.data["longShortRatio"].data == mock_long_short_ratio_data
        
        # Check metadata
        assert "request_timestamp" in result.metadata
        assert "response_timestamp" in result.metadata
        assert "total_response_time_ms" in result.metadata
        assert "individual_timings" in result.metadata
        
        # Check individual timings
        assert "ticker_ms" in result.metadata["individual_timings"]
        assert "open_interest_ms" in result.metadata["individual_timings"]
        assert "funding_rate_ms" in result.metadata["individual_timings"]
        assert "long_short_ratio_ms" in result.metadata["individual_timings"]
        
        # Check field mappings
        assert "ticker" in result.fieldMapping
        assert "openInterest" in result.fieldMapping
        assert "fundingRate" in result.fieldMapping
        assert "longShortRatio" in result.fieldMapping
    
    @pytest.mark.asyncio
    async def test_fetch_all_raw_data_invalid_symbol(self, debug_service):
        """Test validation error for invalid symbol."""
        # Arrange
        symbol = ""
        
        # Act
        result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        assert result.success is False
        
        # All data types should have the same validation error
        assert result.data["ticker"].success is False
        assert result.data["openInterest"].success is False
        assert result.data["fundingRate"].success is False
        assert result.data["longShortRatio"].success is False
        
        assert result.data["ticker"].error.code == "INVALID_INPUT"
        assert result.data["openInterest"].error.code == "INVALID_INPUT"
        assert result.data["fundingRate"].error.code == "INVALID_INPUT"
        assert result.data["longShortRatio"].error.code == "INVALID_INPUT"
    
    @pytest.mark.asyncio
    async def test_fetch_all_raw_data_partial_failure(self, debug_service):
        """Test graceful handling when one data type fails."""
        # Arrange
        symbol = "BTCUSDT"
        
        mock_ticker_data = {
            "symbol": "BTC/USDT:USDT",
            "last": 50000.0
        }
        
        mock_open_interest_data = {
            "symbol": "BTC/USDT:USDT",
            "openInterestAmount": 1000000.0
        }
        
        # Mock successful ticker and open interest
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        
        # Mock failed funding rate (network error)
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        
        # Mock failed long/short ratio (timeout)
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_get.side_effect = Exception("Timeout")
            
            # Act
            result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        # Overall success should be True because some data types succeeded
        assert result.success is True
        
        # Check successful data types
        assert result.data["ticker"].success is True
        assert result.data["ticker"].data == mock_ticker_data
        
        assert result.data["openInterest"].success is True
        assert result.data["openInterest"].data == mock_open_interest_data
        
        # Check failed data types
        assert result.data["fundingRate"].success is False
        assert result.data["fundingRate"].error is not None
        
        assert result.data["longShortRatio"].success is False
        assert result.data["longShortRatio"].error is not None
    
    @pytest.mark.asyncio
    async def test_fetch_all_raw_data_all_failures(self, debug_service):
        """Test when all data types fail."""
        # Arrange
        symbol = "BTCUSDT"
        
        # Mock all methods to fail
        debug_service.exchange.fetch_ticker = AsyncMock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        debug_service.exchange.fetch_open_interest = AsyncMock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        debug_service.exchange.fetch_funding_rate = Mock(
            side_effect=ccxt.NetworkError("Connection failed")
        )
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_get.side_effect = Exception("Connection failed")
            
            # Act
            result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        # Overall success should be False because all data types failed
        assert result.success is False
        
        # All data types should have errors
        assert result.data["ticker"].success is False
        assert result.data["openInterest"].success is False
        assert result.data["fundingRate"].success is False
        assert result.data["longShortRatio"].success is False
    
    @pytest.mark.asyncio
    async def test_fetch_all_raw_data_concurrent_execution(self, debug_service):
        """Test that requests are executed concurrently, not sequentially."""
        # Arrange
        symbol = "BTCUSDT"
        
        # Create mock data
        mock_ticker_data = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        mock_open_interest_data = {"symbol": "BTC/USDT:USDT", "openInterestAmount": 1000000.0}
        mock_funding_rate_data = {"symbol": "BTC/USDT:USDT", "fundingRate": 0.0001}
        
        # Mock the methods
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
            mock_get.return_value = mock_response
            
            # Act
            result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        # Total response time should be less than sum of individual timings
        # (with some overhead for concurrent execution)
        individual_timings = result.metadata["individual_timings"]
        total_individual = sum([
            individual_timings["ticker_ms"],
            individual_timings["open_interest_ms"],
            individual_timings["funding_rate_ms"],
            individual_timings["long_short_ratio_ms"]
        ])
        
        total_response_time = result.metadata["total_response_time_ms"]
        
        # If executed sequentially, total would be >= sum of individual
        # If executed concurrently, total should be approximately max of individual
        # We allow some overhead (100ms) for concurrent execution
        max_individual = max([
            individual_timings["ticker_ms"],
            individual_timings["open_interest_ms"],
            individual_timings["funding_rate_ms"],
            individual_timings["long_short_ratio_ms"]
        ])
        
        # Total should be closer to max than to sum (indicating concurrency)
        # Allow 100ms overhead for concurrent execution
        assert total_response_time <= max_individual + 100
    
    @pytest.mark.asyncio
    async def test_fetch_all_raw_data_symbol_normalization(self, debug_service):
        """Test that symbol is normalized before all requests."""
        # Arrange
        symbol = "  btcusdt  "
        
        mock_ticker_data = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        mock_open_interest_data = {"symbol": "BTC/USDT:USDT", "openInterestAmount": 1000000.0}
        mock_funding_rate_data = {"symbol": "BTC/USDT:USDT", "fundingRate": 0.0001}
        
        debug_service.exchange.fetch_ticker = AsyncMock(return_value=mock_ticker_data)
        debug_service.exchange.fetch_open_interest = AsyncMock(return_value=mock_open_interest_data)
        debug_service.exchange.fetch_funding_rate = Mock(return_value=mock_funding_rate_data)
        debug_service.exchange.market = Mock(return_value={"id": "BTCUSDT"})
        
        with patch('src.services.debug_exchange_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"symbol": "BTCUSDT", "longShortRatio": 1.5}]
            mock_get.return_value = mock_response
            
            # Act
            result = await debug_service.fetch_all_raw_data(symbol)
        
        # Assert
        assert result.success is True
        
        # Verify all methods were called with normalized symbol
        # Note: fetch_ticker and fetch_open_interest convert to CCXT format (BTC/USDT:USDT)
        # after normalization, while fetch_funding_rate and market use the normalized symbol directly
        debug_service.exchange.fetch_ticker.assert_called_once_with("BTC/USDT:USDT")
        debug_service.exchange.fetch_open_interest.assert_called_once_with("BTC/USDT:USDT")
        debug_service.exchange.fetch_funding_rate.assert_called_once_with("BTCUSDT")
        debug_service.exchange.market.assert_called_once_with("BTCUSDT")
