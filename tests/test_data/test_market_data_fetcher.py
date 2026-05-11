#!/usr/bin/env python3
"""
Basic tests for MarketDataFetcher class
"""

import sys
import pytest
from unittest.mock import Mock, MagicMock
from crypto_screener import MarketDataFetcher


def test_market_data_fetcher_initialization():
    """Test that MarketDataFetcher initializes correctly"""
    mock_exchange = Mock()
    symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT']
    
    fetcher = MarketDataFetcher(mock_exchange, symbols)
    
    assert fetcher.exchange == mock_exchange
    assert fetcher.symbols == symbols
    assert len(fetcher.symbols) == 2


def test_fetch_ticker_data():
    """Test fetching ticker data extracts price and 24h change correctly"""
    mock_exchange = Mock()
    
    # Mock the fetch_ticker response
    mock_exchange.fetch_ticker.return_value = {
        'last': 45.67,
        'percentage': 2.34,
        'symbol': 'ZEC/USDT:USDT'
    }
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    result = fetcher.fetch_ticker_data('ZEC/USDT:USDT')
    
    assert result['price'] == 45.67
    assert result['change_24h'] == 2.34
    mock_exchange.fetch_ticker.assert_called_once_with('ZEC/USDT:USDT')


def test_fetch_ticker_data_missing_fields():
    """Test fetching ticker data handles missing fields gracefully"""
    mock_exchange = Mock()
    
    # Mock response with missing fields
    mock_exchange.fetch_ticker.return_value = {
        'symbol': 'ZEC/USDT:USDT'
    }
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    result = fetcher.fetch_ticker_data('ZEC/USDT:USDT')
    
    assert result['price'] is None
    assert result['change_24h'] is None


def test_fetch_funding_rate():
    """Test fetching funding rate extracts and converts to percentage correctly"""
    mock_exchange = Mock()
    
    # Mock the fetch_funding_rate response
    # Funding rate is typically a small decimal (e.g., 0.0001 = 0.01%)
    mock_exchange.fetch_funding_rate.return_value = {
        'fundingRate': 0.0001,
        'symbol': 'ZEC/USDT:USDT'
    }
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    result = fetcher.fetch_funding_rate('ZEC/USDT:USDT')
    
    # Should convert to percentage (0.0001 * 100 = 0.01%)
    assert result == 0.01
    mock_exchange.fetch_funding_rate.assert_called_once_with('ZEC/USDT:USDT')


def test_fetch_funding_rate_missing():
    """Test fetching funding rate handles missing data gracefully"""
    mock_exchange = Mock()
    
    # Mock response with missing fundingRate field
    mock_exchange.fetch_funding_rate.return_value = {
        'symbol': 'ZEC/USDT:USDT'
    }
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    result = fetcher.fetch_funding_rate('ZEC/USDT:USDT')
    
    assert result is None


def test_fetch_long_short_ratio():
    """Test fetching long/short ratio returns simulated value"""
    mock_exchange = Mock()
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    result = fetcher.fetch_long_short_ratio('ZEC/USDT:USDT')
    
    # Should return a simulated value between 0.5 and 2.0
    assert result is not None
    assert 0.5 <= result <= 2.0
    assert isinstance(result, float)


def test_fetch_ticker_data_exception():
    """Test that fetch_ticker_data raises exception on error"""
    mock_exchange = Mock()
    mock_exchange.fetch_ticker.side_effect = Exception("Network error")
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    
    with pytest.raises(Exception, match="Network error"):
        fetcher.fetch_ticker_data('ZEC/USDT:USDT')


def test_fetch_funding_rate_exception():
    """Test that fetch_funding_rate raises exception on error"""
    mock_exchange = Mock()
    mock_exchange.fetch_funding_rate.side_effect = Exception("API error")
    
    fetcher = MarketDataFetcher(mock_exchange, ['ZEC/USDT:USDT'])
    
    with pytest.raises(Exception, match="API error"):
        fetcher.fetch_funding_rate('ZEC/USDT:USDT')


if __name__ == "__main__":
    print("Running MarketDataFetcher tests...")
    
    print("\n1. Testing initialization...")
    test_market_data_fetcher_initialization()
    print("✓ Initialization test passed")
    
    print("\n2. Testing fetch_ticker_data...")
    test_fetch_ticker_data()
    print("✓ Fetch ticker data test passed")
    
    print("\n3. Testing fetch_ticker_data with missing fields...")
    test_fetch_ticker_data_missing_fields()
    print("✓ Fetch ticker data with missing fields test passed")
    
    print("\n4. Testing fetch_funding_rate...")
    test_fetch_funding_rate()
    print("✓ Fetch funding rate test passed")
    
    print("\n5. Testing fetch_funding_rate with missing data...")
    test_fetch_funding_rate_missing()
    print("✓ Fetch funding rate with missing data test passed")
    
    print("\n6. Testing fetch_long_short_ratio...")
    test_fetch_long_short_ratio()
    print("✓ Fetch long/short ratio test passed")
    
    print("\n7. Testing fetch_ticker_data exception handling...")
    test_fetch_ticker_data_exception()
    print("✓ Fetch ticker data exception test passed")
    
    print("\n8. Testing fetch_funding_rate exception handling...")
    test_fetch_funding_rate_exception()
    print("✓ Fetch funding rate exception test passed")
    
    print("\n✓ All tests passed!")
