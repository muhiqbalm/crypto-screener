#!/usr/bin/env python3
"""
Demo script to show ExchangeConnector usage
"""

from crypto_screener import ExchangeConnector
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def demo_exchange_connector():
    """Demonstrate ExchangeConnector functionality"""
    
    print("=" * 60)
    print("ExchangeConnector Demo")
    print("=" * 60)
    
    # 1. Initialize connector with OKX (default)
    print("\n1. Initializing ExchangeConnector with OKX...")
    connector = ExchangeConnector()
    print(f"   Exchange ID: {connector.exchange_id}")
    
    # 2. Try to initialize with Binance (should fail)
    print("\n2. Attempting to initialize with Binance (should fail)...")
    try:
        binance_connector = ExchangeConnector(exchange_id='binance')
        print("   ERROR: Binance should have been blocked!")
    except ValueError as e:
        print(f"   ✓ Correctly blocked: {e}")
    
    # 3. Try to get exchange before connecting (should fail)
    print("\n3. Attempting to get exchange before connecting (should fail)...")
    try:
        exchange = connector.get_exchange()
        print("   ERROR: Should have raised RuntimeError!")
    except RuntimeError as e:
        print(f"   ✓ Correctly raised error: {e}")
    
    # 4. Connect to exchange
    print("\n4. Connecting to OKX exchange...")
    try:
        result = connector.connect()
        if result:
            print("   ✓ Successfully connected!")
            exchange = connector.get_exchange()
            print(f"   ✓ Exchange instance retrieved: {type(exchange).__name__}")
            print(f"   ✓ Markets loaded: {len(exchange.markets)}")
    except ConnectionError as e:
        print(f"   ⚠ Connection failed (network issue): {e}")
        print("   This is expected if OKX is not accessible from your network.")
    
    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)

if __name__ == "__main__":
    demo_exchange_connector()
