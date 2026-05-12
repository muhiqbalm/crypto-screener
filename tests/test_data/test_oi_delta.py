"""
Unit tests for Open Interest Delta calculation functionality.

Tests cover:
- OI delta calculation with known values
- Interpretation matrix (all 4 combinations + neutral)
- Zero OI handling (division by zero)
- API error handling
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from src.data.fetcher import MarketDataFetcher


class TestOIDeltaCalculation:
    """Test suite for calculate_oi_delta() method."""
    
    @pytest.fixture
    def mock_exchange(self):
        """Create mock exchange object."""
        exchange = Mock()
        exchange.fetch = Mock()
        return exchange
    
    @pytest.fixture
    def fetcher(self, mock_exchange):
        """Create MarketDataFetcher instance with mock exchange."""
        return MarketDataFetcher(
            exchange=mock_exchange,
            symbols=['BTC/USDT:USDT']
        )
    
    def test_oi_delta_calculation_positive(self, fetcher, mock_exchange):
        """Test OI delta calculation with increasing OI."""
        # Mock current OI
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},  # Current OI
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]  # Historical OI (24h ago)
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Verify result structure
        assert result is not None
        assert 'current_oi' in result
        assert 'oi_24h_ago' in result
        assert 'oi_delta_percent' in result
        assert 'interpretation' in result
        
        # Verify OI values
        assert result['current_oi'] == 120000
        assert result['oi_24h_ago'] == 100000
        
        # Verify delta calculation: ((120000 - 100000) / 100000) * 100 = 20%
        expected_delta = 20.0
        assert abs(result['oi_delta_percent'] - expected_delta) < 0.01
    
    def test_oi_delta_calculation_negative(self, fetcher, mock_exchange):
        """Test OI delta calculation with decreasing OI."""
        # Mock current OI lower than historical
        mock_exchange.fetch.side_effect = [
            {'openInterest': 80000, 'symbol': 'BTCUSDT'},  # Current OI
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]  # Historical OI (24h ago)
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Verify delta calculation: ((80000 - 100000) / 100000) * 100 = -20%
        expected_delta = -20.0
        assert abs(result['oi_delta_percent'] - expected_delta) < 0.01
    
    def test_interpretation_bullish_accumulation(self, fetcher, mock_exchange):
        """Test interpretation: OI increasing + price increasing = bullish accumulation."""
        # Mock OI increase
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        # Mock price increase (via ticker)
        with patch.object(fetcher, 'fetch_ticker_data', return_value={'price': 55000, 'change_24h': 10.0}):
            result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # OI up + Price up = Bullish accumulation
        assert result['interpretation'] == 'bullish_accumulation'
    
    def test_interpretation_bearish_distribution(self, fetcher, mock_exchange):
        """Test interpretation: OI increasing + price decreasing = bearish distribution."""
        # Mock OI increase
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        # Mock price decrease (via ticker)
        with patch.object(fetcher, 'fetch_ticker_data', return_value={'price': 45000, 'change_24h': -10.0}):
            result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # OI up + Price down = Bearish distribution
        assert result['interpretation'] == 'bearish_distribution'
    
    def test_interpretation_long_liquidation(self, fetcher, mock_exchange):
        """Test interpretation: OI decreasing + price decreasing = long liquidation."""
        # Mock OI decrease
        mock_exchange.fetch.side_effect = [
            {'openInterest': 80000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        # Mock price decrease (via ticker)
        with patch.object(fetcher, 'fetch_ticker_data', return_value={'price': 45000, 'change_24h': -10.0}):
            result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # OI down + Price down = Long liquidation
        assert result['interpretation'] == 'long_liquidation'
    
    def test_interpretation_short_covering(self, fetcher, mock_exchange):
        """Test interpretation: OI decreasing + price increasing = short covering."""
        # Mock OI decrease
        mock_exchange.fetch.side_effect = [
            {'openInterest': 80000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        # Mock price increase (via ticker)
        with patch.object(fetcher, 'fetch_ticker_data', return_value={'price': 55000, 'change_24h': 10.0}):
            result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # OI down + Price up = Short covering
        assert result['interpretation'] == 'short_covering'
    
    def test_interpretation_neutral(self, fetcher, mock_exchange):
        """Test interpretation: minimal OI change = neutral."""
        # Mock minimal OI change (< 1%)
        mock_exchange.fetch.side_effect = [
            {'openInterest': 100500, 'symbol': 'BTCUSDT'},  # 0.5% increase
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        # Mock minimal price change
        with patch.object(fetcher, 'fetch_ticker_data', return_value={'price': 50000, 'change_24h': 0.3}):
            result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Small changes = Neutral
        assert result['interpretation'] == 'neutral'
    
    def test_zero_oi_24h_ago_handling(self, fetcher, mock_exchange):
        """Test handling of zero OI 24h ago (division by zero)."""
        # Mock zero historical OI
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 0, 'timestamp': 1000000}]  # Zero OI 24h ago
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should return null values to avoid division by zero
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] == 'neutral'
    
    def test_current_oi_api_error(self, fetcher, mock_exchange):
        """Test handling of current OI API error."""
        # Mock API error for current OI
        mock_exchange.fetch.side_effect = Exception("API error: rate limit exceeded")
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should return null values
        assert result['current_oi'] is None
        assert result['oi_24h_ago'] is None
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] == 'neutral'
    
    def test_historical_oi_api_error(self, fetcher, mock_exchange):
        """Test handling of historical OI API error."""
        # Mock current OI success, historical OI failure
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            Exception("API error: historical data not available")
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should return null values
        assert result['current_oi'] == 120000  # Current OI was fetched
        assert result['oi_24h_ago'] is None
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] == 'neutral'
    
    def test_empty_historical_oi_response(self, fetcher, mock_exchange):
        """Test handling of empty historical OI response."""
        # Mock empty historical data
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            []  # Empty historical data
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should return null values
        assert result['oi_24h_ago'] is None
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] == 'neutral'
    
    def test_malformed_current_oi_response(self, fetcher, mock_exchange):
        """Test handling of malformed current OI response."""
        # Mock response missing 'openInterest' field
        mock_exchange.fetch.side_effect = [
            {'symbol': 'BTCUSDT'},  # Missing openInterest field
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should handle gracefully
        assert result['current_oi'] is None
        assert result['oi_delta_percent'] is None
    
    def test_malformed_historical_oi_response(self, fetcher, mock_exchange):
        """Test handling of malformed historical OI response."""
        # Mock response missing 'sumOpenInterest' field
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            [{'timestamp': 1000000}]  # Missing sumOpenInterest field
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should handle gracefully
        assert result['oi_24h_ago'] is None
        assert result['oi_delta_percent'] is None
    
    def test_negative_oi_values(self, fetcher, mock_exchange):
        """Test handling of negative OI values (data error)."""
        # Mock negative OI (should not happen in real data)
        mock_exchange.fetch.side_effect = [
            {'openInterest': -120000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Should handle gracefully (implementation may vary)
        # At minimum, should not crash
        assert result is not None
    
    def test_very_large_oi_delta(self, fetcher, mock_exchange):
        """Test handling of very large OI delta (> 100%)."""
        # Mock OI doubling
        mock_exchange.fetch.side_effect = [
            {'openInterest': 200000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Verify delta calculation: ((200000 - 100000) / 100000) * 100 = 100%
        expected_delta = 100.0
        assert abs(result['oi_delta_percent'] - expected_delta) < 0.01
    
    def test_symbol_format_conversion(self, fetcher, mock_exchange):
        """Test symbol format conversion for API calls."""
        # Mock successful fetch
        mock_exchange.fetch.side_effect = [
            {'openInterest': 120000, 'symbol': 'BTCUSDT'},
            [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
        ]
        
        result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        
        # Verify API was called with correct symbol format
        # First call should be for current OI
        first_call = mock_exchange.fetch.call_args_list[0]
        assert 'BTCUSDT' in str(first_call) or 'BTC/USDT' in str(first_call)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
