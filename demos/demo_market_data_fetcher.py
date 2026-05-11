#!/usr/bin/env python3
"""
Demonstration of MarketDataFetcher class functionality
"""

from crypto_screener import ExchangeConnector, MarketDataFetcher
import logging

# Set up logging to see the output
logging.basicConfig(level=logging.INFO)

def main():
    print("=" * 60)
    print("MarketDataFetcher Demonstration")
    print("=" * 60)
    
    # Initialize exchange connector
    print("\n1. Connecting to OKX exchange...")
    connector = ExchangeConnector()
    
    try:
        connector.connect()
        exchange = connector.get_exchange()
        print("✓ Successfully connected to OKX exchange")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return
    
    # Initialize MarketDataFetcher with a small symbol list
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
    print(f"\n2. Initializing MarketDataFetcher with symbols: {symbols}")
    fetcher = MarketDataFetcher(exchange, symbols)
    print("✓ MarketDataFetcher initialized")
    
    # Fetch ticker data for each symbol
    print("\n3. Fetching ticker data...")
    for symbol in symbols:
        try:
            ticker_data = fetcher.fetch_ticker_data(symbol)
            print(f"\n   {symbol}:")
            print(f"   - Price: ${ticker_data['price']:,.2f}")
            print(f"   - 24h Change: {ticker_data['change_24h']:.2f}%")
        except Exception as e:
            print(f"   ✗ Failed to fetch ticker for {symbol}: {e}")
    
    # Fetch funding rate for each symbol
    print("\n4. Fetching funding rates...")
    for symbol in symbols:
        try:
            funding_rate = fetcher.fetch_funding_rate(symbol)
            if funding_rate is not None:
                print(f"   {symbol}: {funding_rate:.4f}%")
            else:
                print(f"   {symbol}: Not available")
        except Exception as e:
            print(f"   ✗ Failed to fetch funding rate for {symbol}: {e}")
    
    # Fetch long/short ratio for each symbol
    print("\n5. Fetching long/short ratios (simulated)...")
    for symbol in symbols:
        try:
            ls_ratio = fetcher.fetch_long_short_ratio(symbol)
            print(f"   {symbol}: {ls_ratio:.2f}")
        except Exception as e:
            print(f"   ✗ Failed to fetch long/short ratio for {symbol}: {e}")
    
    print("\n" + "=" * 60)
    print("Demonstration complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
