#!/usr/bin/env python3
"""
Unit tests for fetch_all_data() method with error handling
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import pandas as pd
import numpy as np
from src.data.fetcher import MarketDataFetcher


class TestFetchAllData(unittest.TestCase):
    """Test cases for MarketDataFetcher.fetch_all_data() method"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create a mock exchange
        self.mock_exchange = Mock()
        
        # Define test symbols
        self.symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                       'AAVE/USDT:USDT', 'SOL/USDT:USDT']
        
        # Create fetcher instance
        self.fetcher = MarketDataFetcher(self.mock_exchange, self.symbols)
    
    def test_fetch_all_data_success(self):
        """Test fetch_all_data() with all successful fetches"""
        # Mock successful responses for all methods
        with patch.object(self.fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(self.fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(self.fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            # Configure mocks to return valid data
            mock_ticker.return_value = {'price': 100.0, 'change_24h': 5.0}
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            # Call fetch_all_data
            df = self.fetcher.fetch_all_data()
            
            # Verify DataFrame structure
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 5)
            self.assertListEqual(list(df.columns), 
                               ['symbol', 'price', 'change_24h', 'funding_rate', 'long_short_ratio'])
            
            # Verify all symbols are present
            self.assertListEqual(list(df['symbol']), self.symbols)
            
            # Verify no NaN values (all successful)
            self.assertEqual(df['price'].notna().sum(), 5)
            self.assertEqual(df['change_24h'].notna().sum(), 5)
            self.assertEqual(df['funding_rate'].notna().sum(), 5)
            self.assertEqual(df['long_short_ratio'].notna().sum(), 5)
    
    def test_fetch_all_data_partial_failure(self):
        """Test fetch_all_data() with some symbols failing"""
        # Mock responses where some symbols fail
        with patch.object(self.fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(self.fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(self.fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            # Configure mocks to fail for specific symbols
            def ticker_side_effect(symbol):
                if symbol == 'TAO/USDT:USDT':
                    raise Exception("Symbol not found")
                return {'price': 100.0, 'change_24h': 5.0}
            
            mock_ticker.side_effect = ticker_side_effect
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            # Call fetch_all_data
            df = self.fetcher.fetch_all_data()
            
            # Verify DataFrame structure
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 5)
            
            # Verify failed symbol has NaN values for ticker data
            tao_row = df[df['symbol'] == 'TAO/USDT:USDT'].iloc[0]
            self.assertTrue(pd.isna(tao_row['price']))
            self.assertTrue(pd.isna(tao_row['change_24h']))
            # But funding rate and long/short ratio should still be fetched
            self.assertEqual(tao_row['funding_rate'], 0.01)
            self.assertEqual(tao_row['long_short_ratio'], 1.2)
            
            # Verify successful symbols have valid data
            zec_row = df[df['symbol'] == 'ZEC/USDT:USDT'].iloc[0]
            self.assertEqual(zec_row['price'], 100.0)
            self.assertEqual(zec_row['change_24h'], 5.0)
    
    def test_fetch_all_data_all_failures(self):
        """Test fetch_all_data() when all symbols fail"""
        # Mock all methods to raise exceptions
        with patch.object(self.fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(self.fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(self.fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            # Configure all mocks to fail
            mock_ticker.side_effect = Exception("Network error")
            mock_funding.side_effect = Exception("Network error")
            mock_ls.side_effect = Exception("Network error")
            
            # Call fetch_all_data
            df = self.fetcher.fetch_all_data()
            
            # Verify DataFrame structure is maintained
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 5)
            
            # Verify all values are NaN
            self.assertEqual(df['price'].notna().sum(), 0)
            self.assertEqual(df['change_24h'].notna().sum(), 0)
            self.assertEqual(df['funding_rate'].notna().sum(), 0)
            self.assertEqual(df['long_short_ratio'].notna().sum(), 0)
            
            # Verify symbols are still present
            self.assertListEqual(list(df['symbol']), self.symbols)
    
    def test_fetch_all_data_null_values_from_api(self):
        """Test fetch_all_data() when API returns None for some fields"""
        # Mock responses with None values
        with patch.object(self.fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(self.fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(self.fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            # Configure mocks to return None for some fields
            mock_ticker.return_value = {'price': 100.0, 'change_24h': None}
            mock_funding.return_value = None
            mock_ls.return_value = 1.2
            
            # Call fetch_all_data
            df = self.fetcher.fetch_all_data()
            
            # Verify DataFrame structure
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 5)
            
            # Verify None values are converted to NaN
            self.assertTrue(df['change_24h'].isna().all())
            self.assertTrue(df['funding_rate'].isna().all())
            
            # Verify valid values are preserved
            self.assertTrue(df['price'].notna().all())
            self.assertTrue(df['long_short_ratio'].notna().all())
    
    def test_fetch_all_data_dataframe_columns(self):
        """Test that fetch_all_data() returns DataFrame with correct columns"""
        # Mock successful responses
        with patch.object(self.fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(self.fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(self.fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            mock_ticker.return_value = {'price': 100.0, 'change_24h': 5.0}
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            # Call fetch_all_data
            df = self.fetcher.fetch_all_data()
            
            # Verify exact column names and order
            expected_columns = ['symbol', 'price', 'change_24h', 'funding_rate', 'long_short_ratio']
            self.assertListEqual(list(df.columns), expected_columns)
    
    def test_fetch_all_data_symbol_order_preserved(self):
        """Test that fetch_all_data() preserves symbol order"""
        # Mock successful responses
        with patch.object(self.fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(self.fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(self.fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            mock_ticker.return_value = {'price': 100.0, 'change_24h': 5.0}
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            # Call fetch_all_data
            df = self.fetcher.fetch_all_data()
            
            # Verify symbol order matches input order
            self.assertListEqual(list(df['symbol']), self.symbols)


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
