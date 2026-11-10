"""
Error handling tests for ExchangeConnector.connect().

CCXT NetworkError / ExchangeError raised while loading markets must surface as a
ConnectionError with a descriptive message naming the exchange.
"""

import unittest
from unittest.mock import Mock, patch

from src.exchange.connector import ExchangeConnector


class TestErrorHandling(unittest.TestCase):
    """Exchange connection error handling"""
    
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
