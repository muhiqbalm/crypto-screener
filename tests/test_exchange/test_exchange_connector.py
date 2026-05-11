#!/usr/bin/env python3
"""
Basic tests for ExchangeConnector class
"""

import sys
import pytest
from crypto_screener import ExchangeConnector


def test_exchange_connector_initialization():
    """Test that ExchangeConnector initializes with OKX by default"""
    connector = ExchangeConnector()
    assert connector.exchange_id == 'okx'
    assert connector.exchange is None  # Not connected yet


def test_exchange_connector_binance_blocked():
    """Test that Binance is blocked and raises ValueError"""
    with pytest.raises(ValueError, match="Binance exchange is not allowed"):
        ExchangeConnector(exchange_id='binance')
    
    # Test case-insensitive blocking
    with pytest.raises(ValueError, match="Binance exchange is not allowed"):
        ExchangeConnector(exchange_id='BINANCE')


def test_get_exchange_before_connect():
    """Test that get_exchange() raises error if connect() not called"""
    connector = ExchangeConnector()
    with pytest.raises(RuntimeError, match="Exchange not connected"):
        connector.get_exchange()


def test_connect_success():
    """Test successful connection to OKX exchange"""
    connector = ExchangeConnector()
    
    try:
        result = connector.connect()
        assert result is True
        assert connector.exchange is not None
        
        # Verify we can get the exchange instance
        exchange = connector.get_exchange()
        assert exchange is not None
        assert hasattr(exchange, 'markets')
        
        print(f"✓ Successfully connected to OKX exchange")
        print(f"✓ Loaded {len(exchange.markets)} markets")
        
    except ConnectionError as e:
        # If connection fails due to network issues, that's acceptable for this test
        print(f"⚠ Connection test skipped due to network: {e}")
        pytest.skip(f"Network unavailable: {e}")


def test_invalid_exchange():
    """Test that invalid exchange ID raises appropriate error"""
    connector = ExchangeConnector(exchange_id='invalid_exchange_xyz')
    
    with pytest.raises(ConnectionError, match="not supported by CCXT"):
        connector.connect()


if __name__ == "__main__":
    print("Running ExchangeConnector tests...")
    print("\n1. Testing initialization...")
    test_exchange_connector_initialization()
    print("✓ Initialization test passed")
    
    print("\n2. Testing Binance blocking...")
    test_exchange_connector_binance_blocked()
    print("✓ Binance blocking test passed")
    
    print("\n3. Testing get_exchange before connect...")
    test_get_exchange_before_connect()
    print("✓ Get exchange before connect test passed")
    
    print("\n4. Testing invalid exchange...")
    test_invalid_exchange()
    print("✓ Invalid exchange test passed")
    
    print("\n5. Testing successful connection...")
    test_connect_success()
    
    print("\n✓ All tests passed!")
