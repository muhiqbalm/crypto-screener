#!/usr/bin/env python3
"""
Integration test for fetch_all_data() method demonstrating error handling
and graceful degradation with the required symbol list.
"""

import unittest
from unittest.mock import Mock, patch
import pandas as pd
import numpy as np
from crypto_screener import MarketDataFetcher


class TestFetchAllDataIntegration(unittest.TestCase):
    """Integration tests for fetch_all_data() with realistic scenarios"""
    
    def test_required_symbol_list(self):
        """Test fetch_all_data() with the exact required symbol list"""
        # Required symbols from task specification
        required_symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                           'AAVE/USDT:USDT', 'SOL/USDT:USDT']
        
        mock_exchange = Mock()
        fetcher = MarketDataFetcher(mock_exchange, required_symbols)
        
        # Mock successful responses
        with patch.object(fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            mock_ticker.return_value = {'price': 100.0, 'change_24h': 5.0}
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            df = fetcher.fetch_all_data()
            
            # Verify all required symbols are present
            self.assertEqual(len(df), 5)
            self.assertListEqual(list(df['symbol']), required_symbols)
    
    def test_mixed_success_and_failure_scenario(self):
        """Test realistic scenario where some symbols succeed and others fail"""
        symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                  'AAVE/USDT:USDT', 'SOL/USDT:USDT']
        
        mock_exchange = Mock()
        fetcher = MarketDataFetcher(mock_exchange, symbols)
        
        # Simulate mixed success/failure scenario
        with patch.object(fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            # ZEC: Success
            # TAO: Ticker fails
            # TON: Funding rate fails
            # AAVE: Long/short ratio fails
            # SOL: Success
            
            def ticker_side_effect(symbol):
                if symbol == 'TAO/USDT:USDT':
                    raise Exception("Symbol not found")
                return {'price': 100.0, 'change_24h': 5.0}
            
            def funding_side_effect(symbol):
                if symbol == 'TON/USDT:USDT':
                    raise Exception("Funding rate unavailable")
                return 0.01
            
            def ls_side_effect(symbol):
                if symbol == 'AAVE/USDT:USDT':
                    raise Exception("Long/short ratio unavailable")
                return 1.2
            
            mock_ticker.side_effect = ticker_side_effect
            mock_funding.side_effect = funding_side_effect
            mock_ls.side_effect = ls_side_effect
            
            df = fetcher.fetch_all_data()
            
            # Verify DataFrame structure is maintained
            self.assertEqual(len(df), 5)
            self.assertListEqual(list(df.columns), 
                               ['symbol', 'price', 'change_24h', 'funding_rate', 'long_short_ratio'])
            
            # Verify ZEC (all success)
            zec = df[df['symbol'] == 'ZEC/USDT:USDT'].iloc[0]
            self.assertEqual(zec['price'], 100.0)
            self.assertEqual(zec['change_24h'], 5.0)
            self.assertEqual(zec['funding_rate'], 0.01)
            self.assertEqual(zec['long_short_ratio'], 1.2)
            
            # Verify TAO (ticker failed, but other fields were still attempted)
            tao = df[df['symbol'] == 'TAO/USDT:USDT'].iloc[0]
            self.assertTrue(pd.isna(tao['price']))
            self.assertTrue(pd.isna(tao['change_24h']))
            # Funding rate and long/short ratio should still be fetched
            self.assertEqual(tao['funding_rate'], 0.01)
            self.assertEqual(tao['long_short_ratio'], 1.2)
            
            # Verify TON (funding rate failed, but has price)
            ton = df[df['symbol'] == 'TON/USDT:USDT'].iloc[0]
            self.assertEqual(ton['price'], 100.0)
            self.assertEqual(ton['change_24h'], 5.0)
            self.assertTrue(pd.isna(ton['funding_rate']))
            self.assertEqual(ton['long_short_ratio'], 1.2)
            
            # Verify AAVE (long/short ratio failed, but has price and funding)
            aave = df[df['symbol'] == 'AAVE/USDT:USDT'].iloc[0]
            self.assertEqual(aave['price'], 100.0)
            self.assertEqual(aave['change_24h'], 5.0)
            self.assertEqual(aave['funding_rate'], 0.01)
            self.assertTrue(pd.isna(aave['long_short_ratio']))
            
            # Verify SOL (all success)
            sol = df[df['symbol'] == 'SOL/USDT:USDT'].iloc[0]
            self.assertEqual(sol['price'], 100.0)
            self.assertEqual(sol['change_24h'], 5.0)
            self.assertEqual(sol['funding_rate'], 0.01)
            self.assertEqual(sol['long_short_ratio'], 1.2)
    
    def test_dataframe_requirements(self):
        """Test that DataFrame meets all requirements from task specification"""
        symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                  'AAVE/USDT:USDT', 'SOL/USDT:USDT']
        
        mock_exchange = Mock()
        fetcher = MarketDataFetcher(mock_exchange, symbols)
        
        with patch.object(fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            mock_ticker.return_value = {'price': 100.0, 'change_24h': 5.0}
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            df = fetcher.fetch_all_data()
            
            # Requirement: Return pandas DataFrame
            self.assertIsInstance(df, pd.DataFrame)
            
            # Requirement: Columns must be: symbol, price, change_24h, funding_rate, long_short_ratio
            expected_columns = ['symbol', 'price', 'change_24h', 'funding_rate', 'long_short_ratio']
            self.assertListEqual(list(df.columns), expected_columns)
            
            # Requirement: Loop through symbol list
            self.assertEqual(len(df), len(symbols))
            self.assertListEqual(list(df['symbol']), symbols)
            
            # Verify data types
            # Symbol should be string-like (object, string, or str dtype)
            self.assertIn(str(df['symbol'].dtype), ['object', 'string', 'str'])
            # Numeric columns should be float
            self.assertIn(str(df['price'].dtype), ['float64', 'float32', 'float'])
            self.assertIn(str(df['change_24h'].dtype), ['float64', 'float32', 'float'])
            self.assertIn(str(df['funding_rate'].dtype), ['float64', 'float32', 'float'])
            self.assertIn(str(df['long_short_ratio'].dtype), ['float64', 'float32', 'float'])
    
    def test_error_handling_continues_processing(self):
        """Test that errors for one symbol don't stop processing of others"""
        symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                  'AAVE/USDT:USDT', 'SOL/USDT:USDT']
        
        mock_exchange = Mock()
        fetcher = MarketDataFetcher(mock_exchange, symbols)
        
        # Make the middle symbol (TON) fail
        with patch.object(fetcher, 'fetch_ticker_data') as mock_ticker, \
             patch.object(fetcher, 'fetch_funding_rate') as mock_funding, \
             patch.object(fetcher, 'fetch_long_short_ratio') as mock_ls:
            
            def ticker_side_effect(symbol):
                if symbol == 'TON/USDT:USDT':
                    raise Exception("Network timeout")
                return {'price': 100.0, 'change_24h': 5.0}
            
            mock_ticker.side_effect = ticker_side_effect
            mock_funding.return_value = 0.01
            mock_ls.return_value = 1.2
            
            df = fetcher.fetch_all_data()
            
            # Verify all 5 symbols are in the result (processing continued)
            self.assertEqual(len(df), 5)
            
            # Verify symbols before TON succeeded
            zec = df[df['symbol'] == 'ZEC/USDT:USDT'].iloc[0]
            self.assertFalse(pd.isna(zec['price']))
            
            tao = df[df['symbol'] == 'TAO/USDT:USDT'].iloc[0]
            self.assertFalse(pd.isna(tao['price']))
            
            # Verify TON failed
            ton = df[df['symbol'] == 'TON/USDT:USDT'].iloc[0]
            self.assertTrue(pd.isna(ton['price']))
            
            # Verify symbols after TON succeeded (processing continued)
            aave = df[df['symbol'] == 'AAVE/USDT:USDT'].iloc[0]
            self.assertFalse(pd.isna(aave['price']))
            
            sol = df[df['symbol'] == 'SOL/USDT:USDT'].iloc[0]
            self.assertFalse(pd.isna(sol['price']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
