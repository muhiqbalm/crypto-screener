#!/usr/bin/env python3
"""
Integration test for fetch_open_interest() method.

This test verifies that the fetch_open_interest method integrates correctly
with the MarketDataFetcher class and handles real-world scenarios.
"""

import pytest
from unittest.mock import Mock, patch
from src.data.fetcher import MarketDataFetcher


def test_fetch_open_interest_integration():
    """Test fetch_open_interest integrates correctly with MarketDataFetcher"""
    # Create mock exchange
    mock_exchange = Mock()
    
    # Mock fetch_open_interest to return realistic data
    mock_exchange.fetch_open_interest.return_value = {
        'openInterestAmount': 18500000000.50,
        'symbol': 'BTC/USDT:USDT',
        'timestamp': 1234567890
    }
    
    # Create fetcher instance
    fetcher = MarketDataFetcher(mock_exchange, ['BTC/USDT:USDT'])
    
    # Fetch open interest
    result = fetcher.fetch_open_interest('BTC/USDT:USDT')
    
    # Verify result
    assert result == 18500000000.50
    assert isinstance(result, float)
    
    # Verify exchange method was called correctly
    mock_exchange.fetch_open_interest.assert_called_once()
    call_args = mock_exchange.fetch_open_interest.call_args
    assert call_args[0][0] == 'BTC/USDT:USDT'
    assert 'params' in call_args[1]
    assert call_args[1]['params']['timeout'] == 5000


def test_fetch_open_interest_with_multiple_symbols():
    """Test fetch_open_interest works correctly with multiple symbols"""
    mock_exchange = Mock()
    
    # Mock different open interest values for different symbols
    def mock_fetch_oi(symbol, params=None):
        oi_values = {
            'BTC/USDT:USDT': {'openInterestAmount': 18000000000.0},
            'ETH/USDT:USDT': {'openInterestAmount': 12000000000.0},
            'SOL/USDT:USDT': {'openInterestAmount': 5000000000.0}
        }
        return oi_values.get(symbol, {'openInterestAmount': None})
    
    mock_exchange.fetch_open_interest.side_effect = mock_fetch_oi
    
    # Create fetcher with multiple symbols
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']
    fetcher = MarketDataFetcher(mock_exchange, symbols)
    
    # Fetch open interest for each symbol
    btc_oi = fetcher.fetch_open_interest('BTC/USDT:USDT')
    eth_oi = fetcher.fetch_open_interest('ETH/USDT:USDT')
    sol_oi = fetcher.fetch_open_interest('SOL/USDT:USDT')
    
    # Verify results
    assert btc_oi == 18000000000.0
    assert eth_oi == 12000000000.0
    assert sol_oi == 5000000000.0
    
    # Verify exchange method was called 3 times
    assert mock_exchange.fetch_open_interest.call_count == 3


def test_fetch_open_interest_graceful_degradation():
    """Test fetch_open_interest handles failures gracefully without crashing"""
    mock_exchange = Mock()
    
    # Mock exchange to raise exception for first symbol, succeed for second
    call_count = [0]
    
    def mock_fetch_oi(symbol, params=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Network error")
        return {'openInterestAmount': 15000000000.0}
    
    mock_exchange.fetch_open_interest.side_effect = mock_fetch_oi
    
    # Create fetcher
    fetcher = MarketDataFetcher(mock_exchange, ['BTC/USDT:USDT', 'ETH/USDT:USDT'])
    
    # First call should return None due to exception
    result1 = fetcher.fetch_open_interest('BTC/USDT:USDT')
    assert result1 is None
    
    # Second call should succeed
    result2 = fetcher.fetch_open_interest('ETH/USDT:USDT')
    assert result2 == 15000000000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
