#!/usr/bin/env python3
"""
Test script to verify comprehensive error handling in crypto_screener.py

This script tests the error handling for:
1. Exchange connection errors (NetworkError, ExchangeError)
2. Visualization rendering failures
3. File saving errors
4. Missing required libraries validation
"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np

# Import the classes we want to test
from crypto_screener import (
    ExchangeConnector,
    DashboardBuilder,
    MultiFactorPanel,
    FundingRatePanel,
    LongShortRatioPanel
)


class TestErrorHandling(unittest.TestCase):
    """Test comprehensive error handling in crypto screener system"""
    
    def test_exchange_connection_network_error(self):
        """Test that NetworkError is caught and logged with descriptive message"""
        import ccxt
        
        with patch('ccxt.binanceusdm') as mock_binance:
            # Mock the exchange to raise NetworkError
            mock_exchange = Mock()
            mock_exchange.load_markets.side_effect = ccxt.NetworkError("Connection timeout")
            mock_binance.return_value = mock_exchange
            
            connector = ExchangeConnector(exchange_id='binanceusdm')
            
            # Should raise ConnectionError with descriptive message
            with self.assertRaises(ConnectionError) as context:
                connector.connect()
            
            # Verify error message contains exchange name and details
            self.assertIn('binanceusdm', str(context.exception).lower())
            self.assertIn('network', str(context.exception).lower())
    
    def test_exchange_connection_exchange_error(self):
        """Test that ExchangeError is caught and logged with descriptive message"""
        import ccxt
        
        with patch('ccxt.binanceusdm') as mock_binance:
            # Mock the exchange to raise ExchangeError
            mock_exchange = Mock()
            mock_exchange.load_markets.side_effect = ccxt.ExchangeError("API key invalid")
            mock_binance.return_value = mock_exchange
            
            connector = ExchangeConnector(exchange_id='binanceusdm')
            
            # Should raise ConnectionError with descriptive message
            with self.assertRaises(ConnectionError) as context:
                connector.connect()
            
            # Verify error message contains exchange name and details
            self.assertIn('binanceusdm', str(context.exception).lower())
    
    def test_dashboard_empty_dataframe_error(self):
        """Test that empty DataFrame raises KeyError with descriptive message"""
        # Create empty DataFrame
        empty_df = pd.DataFrame()
        
        # Should raise KeyError for missing columns (empty DataFrame has no columns)
        with self.assertRaises(KeyError) as context:
            builder = DashboardBuilder(df=empty_df)
        
        # Verify error message mentions missing columns
        self.assertIn('missing', str(context.exception).lower())
    
    def test_dashboard_missing_columns_error(self):
        """Test that missing required columns raises KeyError with descriptive message"""
        # Create DataFrame with missing columns
        incomplete_df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'price': [50000.0]
            # Missing: multi_factor_score, tier, funding_rate, long_short_ratio
        })
        
        # Should raise KeyError during initialization
        with self.assertRaises(KeyError) as context:
            builder = DashboardBuilder(df=incomplete_df)
    
    def test_save_dashboard_without_create(self):
        """Test that save_dashboard raises RuntimeError if create_dashboard not called"""
        # Create valid DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df=df)
        
        # Try to save without creating dashboard first
        with self.assertRaises(RuntimeError) as context:
            builder.save_dashboard('test.png')
        
        # Verify error message mentions create_dashboard
        self.assertIn('create_dashboard', str(context.exception).lower())
    
    def test_save_dashboard_empty_filepath(self):
        """Test that empty filepath raises ValueError"""
        # Create valid DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df=df)
        
        # Mock the figure to avoid actually creating it
        builder.figure = Mock()
        
        # Try to save with empty filepath
        with self.assertRaises(ValueError) as context:
            builder.save_dashboard('')
        
        # Verify error message mentions filepath
        self.assertIn('filepath', str(context.exception).lower())
    
    def test_visualization_panel_missing_columns(self):
        """Test that panel rendering raises KeyError for missing columns"""
        import matplotlib.pyplot as plt
        
        # Create DataFrame missing required columns
        incomplete_df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT']
            # Missing: multi_factor_score, tier
        })
        
        fig, ax = plt.subplots()
        panel = MultiFactorPanel()
        
        # Should raise KeyError for missing columns
        with self.assertRaises(KeyError) as context:
            panel.render(ax, incomplete_df)
        
        plt.close(fig)


class TestDependencyValidation(unittest.TestCase):
    """Test that required libraries are validated before main logic"""
    
    def test_required_imports_exist(self):
        """Test that all required libraries can be imported"""
        try:
            import ccxt
            import pandas
            import numpy
            import matplotlib
            import seaborn
        except ImportError as e:
            self.fail(f"Required library missing: {e}")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
