#!/usr/bin/env python3
"""
Unit tests for MarketDataFetcher.fetch_open_interest() method.

Tests cover:
- Successful open interest fetching with openInterestAmount field
- Successful open interest fetching with openInterest field (fallback)
- Handling missing open interest data
- Handling invalid values (negative, out of range, non-numeric)
- Timeout handling
- Exception handling
"""

import pytest
from unittest.mock import Mock, patch
from src.data.fetcher import MarketDataFetcher


class TestFetchOpenInterest:
    """Test cases for fetch_open_interest() method"""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_exchange = Mock()
        self.fetcher = MarketDataFetcher(self.mock_exchange, ['BTC/USDT:USDT'])
    
    def test_fetch_open_interest_with_openInterestAmount(self):
        """Test fetching open interest with openInterestAmount field"""
        # Mock response with openInterestAmount field
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': 18000000000.0,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result == 18000000000.0
        self.mock_exchange.fetch_open_interest.assert_called_once()
    
    def test_fetch_open_interest_with_openInterest_fallback(self):
        """Test fetching open interest falls back to openInterest field"""
        # Mock response with openInterest field but no openInterestAmount
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterest': 15000000000.0,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result == 15000000000.0
    
    def test_fetch_open_interest_missing_data(self):
        """Test fetching open interest handles missing data gracefully"""
        # Mock response with no open interest fields
        self.mock_exchange.fetch_open_interest.return_value = {
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result is None
    
    def test_fetch_open_interest_negative_value(self):
        """Test fetching open interest rejects negative values"""
        # Mock response with negative open interest
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': -1000.0,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result is None
    
    def test_fetch_open_interest_exceeds_max_value(self):
        """Test fetching open interest rejects values exceeding max"""
        # Mock response with value exceeding 999999999999.99
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': 1000000000000.0,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result is None
    
    def test_fetch_open_interest_non_numeric_value(self):
        """Test fetching open interest handles non-numeric values"""
        # Mock response with non-numeric open interest
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': 'invalid',
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result is None
    
    def test_fetch_open_interest_zero_value(self):
        """Test fetching open interest accepts zero value"""
        # Mock response with zero open interest
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': 0.0,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result == 0.0
    
    def test_fetch_open_interest_max_valid_value(self):
        """Test fetching open interest accepts max valid value"""
        # Mock response with max valid open interest
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': 999999999999.99,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result == 999999999999.99
    
    def test_fetch_open_interest_exception_handling(self):
        """Test fetching open interest handles exceptions gracefully"""
        # Mock exception during fetch
        self.mock_exchange.fetch_open_interest.side_effect = Exception("Network timeout")
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result is None
    
    def test_fetch_open_interest_timeout(self):
        """Test fetching open interest handles timeout gracefully"""
        # Mock timeout exception
        self.mock_exchange.fetch_open_interest.side_effect = TimeoutError("Request timeout")
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result is None
    
    def test_fetch_open_interest_decimal_value(self):
        """Test fetching open interest handles decimal values correctly"""
        # Mock response with decimal open interest
        self.mock_exchange.fetch_open_interest.return_value = {
            'openInterestAmount': 12345678.56,
            'symbol': 'BTC/USDT:USDT'
        }
        
        result = self.fetcher.fetch_open_interest('BTC/USDT:USDT')
        
        assert result == 12345678.56


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
