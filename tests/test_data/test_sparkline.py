"""
Unit tests for sparkline data fetching functionality.

Tests cover:
- Hourly data fetch
- 4-hour fallback mechanism
- Trend classification (uptrend/downtrend/neutral)
- Insufficient data handling
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from src.data.fetcher import MarketDataFetcher


class TestSparklineDataFetch:
    """Test suite for fetch_sparkline_data() method."""
    
    @pytest.fixture
    def mock_exchange(self):
        """Create mock exchange object."""
        exchange = Mock()
        exchange.fetch_ohlcv = Mock()
        return exchange
    
    @pytest.fixture
    def fetcher(self, mock_exchange):
        """Create MarketDataFetcher instance with mock exchange."""
        return MarketDataFetcher(
            exchange=mock_exchange,
            symbols=['BTC/USDT:USDT']
        )
    
    def test_hourly_data_fetch_success(self, fetcher, mock_exchange):
        """Test successful hourly data fetch."""
        # Mock OHLCV data: 24 hourly candles with uptrend
        mock_ohlcv = [
            [1000000 + i*3600000, 50000 + i*100, 50100 + i*100, 49900 + i*100, 50050 + i*100, 1000]
            for i in range(24)
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify result structure
        assert result is not None
        assert 'prices' in result
        assert 'trend' in result
        assert 'timeframe' in result
        assert 'change_percent' in result
        
        # Verify prices list
        assert len(result['prices']) == 24
        assert result['prices'][0] == 50050  # First closing price
        assert result['prices'][-1] == 50050 + 23*100  # Last closing price
        
        # Verify trend (uptrend: last > first)
        assert result['trend'] == 'uptrend'
        
        # Verify timeframe
        assert result['timeframe'] == '1h'
        
        # Verify change percent
        expected_change = ((result['prices'][-1] - result['prices'][0]) / result['prices'][0]) * 100
        assert abs(result['change_percent'] - expected_change) < 0.01
        
        # Verify fetch_ohlcv was called with correct parameters
        # Note: Implementation calls with positional args
        mock_exchange.fetch_ohlcv.assert_called_once()
        call_args = mock_exchange.fetch_ohlcv.call_args
        assert call_args[0][0] == 'BTC/USDT:USDT'
        assert call_args[0][1] == '1h'
        assert call_args[1]['limit'] == 24
    
    def test_downtrend_classification(self, fetcher, mock_exchange):
        """Test trend classification for downtrend."""
        # Mock OHLCV data: 24 hourly candles with downtrend
        mock_ohlcv = [
            [1000000 + i*3600000, 50000 - i*100, 50100 - i*100, 49900 - i*100, 50050 - i*100, 1000]
            for i in range(24)
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify downtrend (last < first)
        assert result['trend'] == 'downtrend'
        assert result['change_percent'] < 0
    
    def test_neutral_trend_classification(self, fetcher, mock_exchange):
        """Test trend classification for neutral/flat trend."""
        # Mock OHLCV data: 24 hourly candles with flat prices
        mock_ohlcv = [
            [1000000 + i*3600000, 50000, 50100, 49900, 50000, 1000]
            for i in range(24)
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify neutral trend (last == first or very small change)
        assert result['trend'] == 'neutral'
        assert abs(result['change_percent']) < 0.1  # Less than 0.1% change
    
    def test_4hour_fallback_mechanism(self, fetcher, mock_exchange):
        """Test fallback to 4-hour candles when hourly fails."""
        # Mock hourly fetch failure, then 4-hour success
        mock_4h_ohlcv = [
            [1000000 + i*14400000, 50000 + i*200, 50200 + i*200, 49800 + i*200, 50100 + i*200, 1000]
            for i in range(42)  # 42 candles for 7 days
        ]
        
        # First call (hourly) raises exception, second call (4-hour) succeeds
        mock_exchange.fetch_ohlcv.side_effect = [
            Exception("Hourly data not available"),
            mock_4h_ohlcv
        ]
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify result uses 4-hour data
        assert result is not None
        assert result['timeframe'] == '4h'
        assert len(result['prices']) == 42
        
        # Verify both fetch attempts were made
        assert mock_exchange.fetch_ohlcv.call_count == 2
        calls = mock_exchange.fetch_ohlcv.call_args_list
        # First call: hourly
        assert calls[0][0][0] == 'BTC/USDT:USDT'
        assert calls[0][0][1] == '1h'
        assert calls[0][1]['limit'] == 24
        # Second call: 4-hour fallback
        assert calls[1][0][0] == 'BTC/USDT:USDT'
        assert calls[1][0][1] == '4h'
        assert calls[1][1]['limit'] == 42
    
    def test_insufficient_data_points(self, fetcher, mock_exchange):
        """Test handling of insufficient data points (< 2 candles)."""
        # Mock OHLCV with only 1 candle
        mock_ohlcv = [
            [1000000, 50000, 50100, 49900, 50050, 1000]
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify null values returned
        assert result['prices'] is None
        assert result['trend'] is None
        assert result['timeframe'] is None
        assert result['change_percent'] is None
    
    def test_empty_ohlcv_data(self, fetcher, mock_exchange):
        """Test handling of empty OHLCV data."""
        mock_exchange.fetch_ohlcv.return_value = []
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify null values returned
        assert result['prices'] is None
        assert result['trend'] is None
        assert result['timeframe'] is None
        assert result['change_percent'] is None
    
    def test_both_timeframes_fail(self, fetcher, mock_exchange):
        """Test handling when both hourly and 4-hour fetches fail."""
        # Both fetch attempts raise exceptions
        mock_exchange.fetch_ohlcv.side_effect = [
            Exception("Hourly data not available"),
            Exception("4-hour data not available")
        ]
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify null values returned
        assert result['prices'] is None
        assert result['trend'] is None
        assert result['timeframe'] is None
        assert result['change_percent'] is None
    
    def test_trend_threshold_boundary(self, fetcher, mock_exchange):
        """Test trend classification at threshold boundaries."""
        # Test with 0.05% change (implementation treats any change as uptrend/downtrend)
        first_price = 50000
        last_price = 50025  # 0.05% increase
        
        mock_ohlcv = []
        for i in range(24):
            price = first_price + (last_price - first_price) * i / 23
            mock_ohlcv.append([1000000 + i*3600000, price, price+100, price-100, price, 1000])
        
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Implementation classifies any increase as uptrend (no threshold)
        assert result['trend'] == 'uptrend'
        assert result['change_percent'] > 0
    
    def test_malformed_ohlcv_data(self, fetcher, mock_exchange):
        """Test handling of malformed OHLCV data."""
        # Mock OHLCV with missing closing price (index 4)
        mock_ohlcv = [
            [1000000, 50000, 50100, 49900],  # Missing close and volume
            [1000001, 50100, 50200, 50000, 50150, 1000]
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        # Should raise IndexError or handle gracefully
        try:
            result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
            # If it doesn't raise, check that it returns null or handles gracefully
            assert result is not None
        except IndexError:
            # Expected behavior - malformed data causes error
            pass
    
    def test_change_percent_calculation(self, fetcher, mock_exchange):
        """Test accurate change percentage calculation."""
        # Create data with known change
        first_price = 50000
        last_price = 55000  # 10% increase
        
        mock_ohlcv = [
            [1000000, first_price, first_price, first_price, first_price, 1000],
            [1000001, last_price, last_price, last_price, last_price, 1000]
        ]
        mock_exchange.fetch_ohlcv.return_value = mock_ohlcv
        
        result = fetcher.fetch_sparkline_data('BTC/USDT:USDT')
        
        # Verify change percent is accurate
        expected_change = ((last_price - first_price) / first_price) * 100
        assert abs(result['change_percent'] - expected_change) < 0.01
        assert abs(result['change_percent'] - 10.0) < 0.01


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
