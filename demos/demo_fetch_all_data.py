#!/usr/bin/env python3
"""
Demonstration of fetch_all_data() method with error handling
"""

from crypto_screener import ExchangeConnector, MarketDataFetcher
import logging

# Set up logging to see the output
logging.basicConfig(level=logging.INFO)

def main():
    print("=" * 60)
    print("fetch_all_data() Demonstration")
    print("=" * 60)
    
    # Initialize exchange connector
    print("\n1. Connecting to Binance USDT-M Futures exchange...")
    connector = ExchangeConnector()
    
    try:
        connector.connect()
        exchange = connector.get_exchange()
        print("✓ Successfully connected to Binance USDT-M Futures exchange")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return
    
    # Initialize MarketDataFetcher with the required symbol list
    symbols = ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
               'AAVE/USDT:USDT', 'SOL/USDT:USDT']
    
    print(f"\n2. Initializing MarketDataFetcher with {len(symbols)} symbols")
    fetcher = MarketDataFetcher(exchange, symbols)
    print("✓ MarketDataFetcher initialized")
    
    # Fetch all data using fetch_all_data() method
    print("\n3. Fetching all data for all symbols...")
    print("   (This will handle errors gracefully and continue processing)")
    
    try:
        df = fetcher.fetch_all_data()
        print("\n✓ Data fetch complete!")
        
        # Display the resulting DataFrame
        print("\n4. Resulting DataFrame:")
        print("-" * 60)
        print(df.to_string(index=False))
        print("-" * 60)
        
        # Display summary statistics
        print("\n5. Summary:")
        print(f"   Total symbols: {len(df)}")
        print(f"   Successful fetches: {df['price'].notna().sum()}")
        print(f"   Failed fetches: {df['price'].isna().sum()}")
        
        # Display data types
        print("\n6. DataFrame Info:")
        print(df.info())
        
    except Exception as e:
        print(f"\n✗ Failed to fetch data: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Demonstration complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
