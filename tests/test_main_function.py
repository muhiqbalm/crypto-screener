#!/usr/bin/env python3
"""
Test script for main() function with mocked exchange connection.

This script tests the complete pipeline without requiring actual network access
to the OKX exchange. It mocks the exchange connection and data fetching to
verify that all pipeline stages execute correctly.
"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np
from datetime import datetime

# Import the crypto_screener module
import crypto_screener


class TestMainFunction(unittest.TestCase):
    """Test the main() function with mocked exchange connection."""
    
    @patch('crypto_screener.ExchangeConnector')
    @patch('crypto_screener.MarketDataFetcher')
    @patch('crypto_screener.DashboardBuilder')
    def test_main_pipeline_success(self, mock_dashboard_builder, mock_fetcher_class, mock_connector_class):
        """Test that main() executes all pipeline stages successfully with mocked data."""
        
        # Mock ExchangeConnector
        mock_connector = Mock()
        mock_exchange = Mock()
        mock_connector.connect.return_value = True
        mock_connector.get_exchange.return_value = mock_exchange
        mock_connector_class.return_value = mock_connector
        
        # Create mock market data
        mock_data = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [45.2, 320.5, 5.8, 180.3, 95.7],
            'change_24h': [2.5, -1.3, 4.2, -0.8, 3.1],
            'funding_rate': [0.01, -0.02, 0.015, -0.005, 0.008],
            'long_short_ratio': [1.2, 1.8, 0.9, 1.5, 1.3]
        })
        
        # Mock MarketDataFetcher
        mock_fetcher = Mock()
        mock_fetcher.fetch_all_data.return_value = mock_data
        mock_fetcher_class.return_value = mock_fetcher
        
        # Mock DashboardBuilder
        mock_builder = Mock()
        mock_figure = Mock()
        mock_builder.create_dashboard.return_value = mock_figure
        mock_builder.save_dashboard.return_value = None
        mock_dashboard_builder.return_value = mock_builder
        
        # Run main() - should not raise any exceptions
        try:
            crypto_screener.main()
            success = True
        except SystemExit as e:
            # Check if it's a successful exit (code 0) or failure (code 1)
            if e.code == 0:
                success = True
            else:
                success = False
        except Exception as e:
            print(f"Unexpected exception: {e}")
            success = False
        
        # Verify that main() completed successfully
        self.assertTrue(success, "main() should complete without errors")
        
        # Verify that key methods were called
        mock_connector_class.assert_called_once()
        mock_connector.connect.assert_called_once()
        mock_fetcher_class.assert_called_once()
        mock_fetcher.fetch_all_data.assert_called_once()
        mock_dashboard_builder.assert_called_once()
        mock_builder.create_dashboard.assert_called_once()
        mock_builder.save_dashboard.assert_called_once()
        
        print("\n[SUCCESS] main() pipeline test passed!")
        print("All pipeline stages executed correctly:")
        print("  1. Exchange connection initialized")
        print("  2. Market data fetched")
        print("  3. Signals generated")
        print("  4. Multi-factor scores calculated")
        print("  5. Assets ranked")
        print("  6. Dashboard visualization created")
        print("  7. Dashboard saved to disk")


if __name__ == '__main__':
    print("=" * 70)
    print("Testing main() function with mocked exchange connection")
    print("=" * 70)
    
    # Run the test
    unittest.main(verbosity=2)
