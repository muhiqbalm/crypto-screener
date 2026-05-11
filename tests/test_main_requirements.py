#!/usr/bin/env python3
"""
Unit tests to verify main() function meets task 8.1 requirements.

Task 8.1 Requirements:
- Define symbol list: ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT']
- Initialize ExchangeConnector and establish connection
- Create MarketDataFetcher and fetch all data
- Create SignalGenerator and generate signals
- Create ICWeightCalculator and MultiFactorScorer
- Calculate multi-factor scores and classify tiers
- Create RankingEngine and rank assets
- Create DashboardBuilder and generate visualization
- Save dashboard to disk with timestamp in filename
- Wrap each stage in try-except blocks with appropriate error handling
"""

import unittest
from unittest.mock import Mock, patch, call
import pandas as pd
import re
from datetime import datetime

import crypto_screener


class TestMainRequirements(unittest.TestCase):
    """Test that main() function meets all task 8.1 requirements."""
    
    @patch('crypto_screener.ExchangeConnector')
    @patch('crypto_screener.MarketDataFetcher')
    @patch('crypto_screener.SignalGenerator')
    @patch('crypto_screener.ICWeightCalculator')
    @patch('crypto_screener.MultiFactorScorer')
    @patch('crypto_screener.RankingEngine')
    @patch('crypto_screener.DashboardBuilder')
    def test_all_components_initialized(self, mock_dashboard, mock_ranking, mock_scorer, 
                                       mock_ic_calc, mock_signal_gen, mock_fetcher, mock_connector):
        """Verify that all required components are initialized in main()."""
        
        # Setup mocks
        mock_conn_instance = Mock()
        mock_exchange = Mock()
        mock_conn_instance.connect.return_value = True
        mock_conn_instance.get_exchange.return_value = mock_exchange
        mock_connector.return_value = mock_conn_instance
        
        mock_data = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [45.2, 320.5, 5.8, 180.3, 95.7],
            'change_24h': [2.5, -1.3, 4.2, -0.8, 3.1],
            'funding_rate': [0.01, -0.02, 0.015, -0.005, 0.008],
            'long_short_ratio': [1.2, 1.8, 0.9, 1.5, 1.3]
        })
        
        mock_fetcher_instance = Mock()
        mock_fetcher_instance.fetch_all_data.return_value = mock_data
        mock_fetcher.return_value = mock_fetcher_instance
        
        mock_signal_instance = Mock()
        mock_signal_instance.calculate_reversal_signal.return_value = pd.Series([1, 2, 3, 4, 5])
        mock_signal_instance.calculate_momentum_signal.return_value = pd.Series([1, 2, 3, 4, 5])
        mock_signal_instance.normalize_signal.return_value = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
        mock_signal_gen.return_value = mock_signal_instance
        
        mock_ic_instance = Mock()
        mock_ic_calc.return_value = mock_ic_instance
        
        mock_scorer_instance = Mock()
        mock_scorer_instance.calculate_score.return_value = pd.Series([0.5, 0.4, 0.3, 0.2, 0.1])
        mock_scorer_instance.classify_tiers.return_value = pd.Series(['A', 'A', 'A', 'B', 'B'])
        mock_scorer.return_value = mock_scorer_instance
        
        mock_ranking_instance = Mock()
        ranked_data = mock_data.copy()
        ranked_data['multi_factor_score'] = [0.5, 0.4, 0.3, 0.2, 0.1]
        ranked_data['tier'] = ['A', 'A', 'A', 'B', 'B']
        ranked_data['rank'] = [1, 2, 3, 4, 5]
        mock_ranking_instance.rank_assets.return_value = ranked_data
        mock_ranking.return_value = mock_ranking_instance
        
        mock_dashboard_instance = Mock()
        mock_dashboard_instance.create_dashboard.return_value = Mock()
        mock_dashboard.return_value = mock_dashboard_instance
        
        # Run main()
        try:
            crypto_screener.main()
        except SystemExit:
            pass
        
        # Verify all components were initialized
        mock_connector.assert_called_once_with(exchange_id='okx')
        mock_fetcher.assert_called_once()
        mock_signal_gen.assert_called_once()
        mock_ic_calc.assert_called_once()
        mock_scorer.assert_called_once()
        mock_ranking.assert_called_once()
        mock_dashboard.assert_called_once()
        
        print("\n[PASS] All required components initialized")
    
    @patch('crypto_screener.ExchangeConnector')
    @patch('crypto_screener.MarketDataFetcher')
    @patch('crypto_screener.DashboardBuilder')
    def test_correct_symbol_list(self, mock_dashboard, mock_fetcher, mock_connector):
        """Verify that the correct symbol list is used."""
        
        # Setup mocks
        mock_conn_instance = Mock()
        mock_exchange = Mock()
        mock_conn_instance.connect.return_value = True
        mock_conn_instance.get_exchange.return_value = mock_exchange
        mock_connector.return_value = mock_conn_instance
        
        mock_data = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [45.2, 320.5, 5.8, 180.3, 95.7],
            'change_24h': [2.5, -1.3, 4.2, -0.8, 3.1],
            'funding_rate': [0.01, -0.02, 0.015, -0.005, 0.008],
            'long_short_ratio': [1.2, 1.8, 0.9, 1.5, 1.3]
        })
        
        mock_fetcher_instance = Mock()
        mock_fetcher_instance.fetch_all_data.return_value = mock_data
        mock_fetcher.return_value = mock_fetcher_instance
        
        mock_dashboard_instance = Mock()
        mock_dashboard_instance.create_dashboard.return_value = Mock()
        mock_dashboard.return_value = mock_dashboard_instance
        
        # Run main()
        try:
            crypto_screener.main()
        except SystemExit:
            pass
        
        # Verify MarketDataFetcher was called with correct symbols
        call_args = mock_fetcher.call_args
        symbols = call_args[1]['symbols']
        
        expected_symbols = [
            'ZEC/USDT:USDT',
            'TAO/USDT:USDT',
            'TON/USDT:USDT',
            'AAVE/USDT:USDT',
            'SOL/USDT:USDT'
        ]
        
        self.assertEqual(symbols, expected_symbols, "Symbol list should match requirements")
        print("\n[PASS] Correct symbol list used")
    
    @patch('crypto_screener.ExchangeConnector')
    @patch('crypto_screener.MarketDataFetcher')
    @patch('crypto_screener.DashboardBuilder')
    def test_timestamp_in_filename(self, mock_dashboard, mock_fetcher, mock_connector):
        """Verify that dashboard filename includes timestamp."""
        
        # Setup mocks
        mock_conn_instance = Mock()
        mock_exchange = Mock()
        mock_conn_instance.connect.return_value = True
        mock_conn_instance.get_exchange.return_value = mock_exchange
        mock_connector.return_value = mock_conn_instance
        
        mock_data = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [45.2, 320.5, 5.8, 180.3, 95.7],
            'change_24h': [2.5, -1.3, 4.2, -0.8, 3.1],
            'funding_rate': [0.01, -0.02, 0.015, -0.005, 0.008],
            'long_short_ratio': [1.2, 1.8, 0.9, 1.5, 1.3]
        })
        
        mock_fetcher_instance = Mock()
        mock_fetcher_instance.fetch_all_data.return_value = mock_data
        mock_fetcher.return_value = mock_fetcher_instance
        
        mock_dashboard_instance = Mock()
        mock_dashboard_instance.create_dashboard.return_value = Mock()
        mock_dashboard.return_value = mock_dashboard_instance
        
        # Run main()
        try:
            crypto_screener.main()
        except SystemExit:
            pass
        
        # Verify save_dashboard was called with timestamped filename
        call_args = mock_dashboard_instance.save_dashboard.call_args
        filename = call_args[1]['filepath']
        
        # Check filename format: crypto_screener_dashboard_YYYYMMDD_HHMMSS.png
        pattern = r'crypto_screener_dashboard_\d{8}_\d{6}\.png'
        self.assertIsNotNone(re.match(pattern, filename), 
                           f"Filename '{filename}' should include timestamp in format YYYYMMDD_HHMMSS")
        
        print(f"\n[PASS] Dashboard filename includes timestamp: {filename}")
    
    @patch('crypto_screener.ExchangeConnector')
    def test_error_handling_connection_failure(self, mock_connector):
        """Verify that connection errors are handled gracefully."""
        
        # Setup mock to raise ConnectionError
        mock_conn_instance = Mock()
        mock_conn_instance.connect.side_effect = ConnectionError("Network error")
        mock_connector.return_value = mock_conn_instance
        
        # Run main() and expect SystemExit
        with self.assertRaises(SystemExit) as cm:
            crypto_screener.main()
        
        # Verify exit code is 1 (error)
        self.assertEqual(cm.exception.code, 1, "Should exit with code 1 on connection error")
        
        print("\n[PASS] Connection errors handled gracefully with sys.exit(1)")
    
    @patch('crypto_screener.ExchangeConnector')
    @patch('crypto_screener.MarketDataFetcher')
    def test_error_handling_no_data(self, mock_fetcher, mock_connector):
        """Verify that missing data errors are handled gracefully."""
        
        # Setup mocks
        mock_conn_instance = Mock()
        mock_exchange = Mock()
        mock_conn_instance.connect.return_value = True
        mock_conn_instance.get_exchange.return_value = mock_exchange
        mock_connector.return_value = mock_conn_instance
        
        # Return DataFrame with all NaN prices (no successful fetches)
        mock_data = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [float('nan')] * 5,
            'change_24h': [float('nan')] * 5,
            'funding_rate': [float('nan')] * 5,
            'long_short_ratio': [float('nan')] * 5
        })
        
        mock_fetcher_instance = Mock()
        mock_fetcher_instance.fetch_all_data.return_value = mock_data
        mock_fetcher.return_value = mock_fetcher_instance
        
        # Run main() and expect SystemExit
        with self.assertRaises(SystemExit) as cm:
            crypto_screener.main()
        
        # Verify exit code is 1 (error)
        self.assertEqual(cm.exception.code, 1, "Should exit with code 1 when no data fetched")
        
        print("\n[PASS] Missing data errors handled gracefully with sys.exit(1)")


if __name__ == '__main__':
    print("=" * 70)
    print("Testing main() function requirements (Task 8.1)")
    print("=" * 70)
    
    # Run tests
    unittest.main(verbosity=2)
