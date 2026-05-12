"""
Market Data Fetcher Module

Fetches market data for perpetual futures contracts from exchanges.
"""

import logging
import random
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """
    Fetches market data for perpetual futures contracts from the exchange.
    
    This class retrieves real-time market data including price, 24h change,
    funding rate, and long/short ratio for specified cryptocurrency symbols.
    """
    
    def __init__(self, exchange: ccxt.Exchange, symbols: list):
        """
        Initialize MarketDataFetcher with exchange and symbol list.
        
        Args:
            exchange: CCXT exchange instance (e.g., OKX)
            symbols: List of perpetual futures symbols (e.g., ['ZEC/USDT:USDT', 'TAO/USDT:USDT'])
        """
        self.exchange = exchange
        self.symbols = symbols
        logger.info(f"MarketDataFetcher initialized with {len(symbols)} symbols")
    
    def fetch_ticker_data(self, symbol: str) -> dict:
        """
        Fetch current price and 24-hour change percentage for a symbol.
        
        CCXT Endpoint Mapping:
        - Uses exchange.fetch_ticker(symbol) method
        - Extracts 'last' field for current price
        - Extracts 'percentage' field for 24-hour percentage change
        
        Args:
            symbol: Trading pair symbol (e.g., 'ZEC/USDT:USDT')
            
        Returns:
            dict: Dictionary with 'price' and 'change_24h' keys
            
        Raises:
            Exception: If ticker data cannot be fetched
        """
        try:
            # Fetch ticker data from CCXT
            # CCXT endpoint: exchange.fetch_ticker() returns ticker dictionary
            ticker = self.exchange.fetch_ticker(symbol)
            
            # Extract price from 'last' field (most recent trade price)
            price = ticker.get('last', None)
            
            # Extract 24h percentage change from 'percentage' field
            change_24h = ticker.get('percentage', None)
            
            logger.debug(f"Fetched ticker for {symbol}: price={price}, change_24h={change_24h}%")
            
            return {
                'price': price,
                'change_24h': change_24h
            }
            
        except Exception as e:
            logger.error(f"Failed to fetch ticker data for {symbol}: {e}")
            raise
    
    def fetch_funding_rate(self, symbol: str) -> float:
        """
        Fetch current funding rate percentage for a perpetual futures contract.
        
        CCXT Endpoint Mapping:
        - Uses exchange.fetch_funding_rate(symbol) method
        - Extracts 'fundingRate' field from response
        - Funding rate is typically expressed as a decimal (e.g., 0.0001 = 0.01%)
        - Converts to percentage by multiplying by 100
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'ZEC/USDT:USDT')
            
        Returns:
            float: Funding rate as percentage (e.g., 0.01 for 0.01%)
            
        Raises:
            Exception: If funding rate cannot be fetched
        """
        try:
            # Fetch funding rate from CCXT
            # CCXT endpoint: exchange.fetch_funding_rate() returns funding rate info
            funding_data = self.exchange.fetch_funding_rate(symbol)
            
            # Extract funding rate from 'fundingRate' field
            # Funding rate is typically a small decimal (e.g., 0.0001)
            funding_rate = funding_data.get('fundingRate', None)
            
            if funding_rate is not None:
                # Convert to percentage (multiply by 100)
                funding_rate_pct = funding_rate * 100
                logger.debug(f"Fetched funding rate for {symbol}: {funding_rate_pct}%")
                return funding_rate_pct
            else:
                logger.warning(f"Funding rate not available for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to fetch funding rate for {symbol}: {e}")
            raise
    
    def fetch_long_short_ratio(self, symbol: str) -> float:
        """
        Fetch current long/short ratio for a perpetual futures contract.
        
        CCXT Endpoint Mapping:
        - OKX-specific: May require custom API endpoint or simulation
        - Standard CCXT does not have a universal long/short ratio method
        - For OKX: Could use exchange.publicGetMarketOpenInterestAndVolume() or similar
        - Current implementation: SIMULATED with random values for MVP
        
        Note: This is a placeholder implementation. Real implementation would require:
        1. OKX-specific API endpoint for long/short ratio
        2. Parsing of OKX's proprietary response format
        3. Proper error handling for OKX-specific errors
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'ZEC/USDT:USDT')
            
        Returns:
            float: Long/short ratio (e.g., 1.5 means 1.5x more longs than shorts)
            
        Raises:
            Exception: If long/short ratio cannot be fetched
        """
        try:
            # SIMULATED IMPLEMENTATION for MVP
            # Real implementation would use OKX-specific API endpoint
            # Example: exchange.publicGetMarketOpenInterestAndVolume({'instId': symbol})
            
            # For now, generate simulated ratio between 0.5 and 2.0
            # This provides realistic-looking data for testing visualization
            import random
            simulated_ratio = random.uniform(0.5, 2.0)
            
            logger.debug(f"Fetched (simulated) long/short ratio for {symbol}: {simulated_ratio}")
            logger.warning(f"Long/short ratio for {symbol} is SIMULATED - implement OKX-specific API for production")
            
            return simulated_ratio
            
        except Exception as e:
            logger.error(f"Failed to fetch long/short ratio for {symbol}: {e}")
            raise
    
    def fetch_all_data(self) -> pd.DataFrame:
        """
        Fetch all market data fields for all symbols with graceful error handling.
        
        This method loops through the symbol list and fetches ticker data, funding rate,
        and long/short ratio for each symbol. If any symbol fails to fetch, it logs a
        warning and continues processing remaining symbols, setting null/NaN values for
        the failed symbol's data fields.
        
        Error Handling Strategy:
        - Catches exceptions per-symbol during data fetching loop
        - Logs warning with symbol name and error details
        - Sets null/NaN values for failed symbol's data fields
        - Continues processing remaining symbols
        - Returns partial results in DataFrame
        
        Returns:
            pd.DataFrame: DataFrame with columns:
                - symbol: Asset symbol (str)
                - price: Current price (float, NaN if failed)
                - change_24h: 24-hour percentage change (float, NaN if failed)
                - funding_rate: Funding rate percentage (float, NaN if failed)
                - long_short_ratio: Long/short ratio (float, NaN if failed)
        
        Requirements: 2.2, 2.7, 10.1, 10.2
        """
        logger.info(f"Starting to fetch data for {len(self.symbols)} symbols")
        
        # List to collect data for each symbol
        data_records = []
        
        # Loop through each symbol and fetch all data fields
        for symbol in self.symbols:
            logger.info(f"Fetching data for {symbol}...")
            
            # Initialize record with symbol and NaN values (default for failures)
            record = {
                'symbol': symbol,
                'price': np.nan,
                'change_24h': np.nan,
                'funding_rate': np.nan,
                'long_short_ratio': np.nan
            }
            
            # Fetch ticker data (price and 24h change) with error handling
            try:
                ticker_data = self.fetch_ticker_data(symbol)
                record['price'] = ticker_data.get('price', np.nan)
                record['change_24h'] = ticker_data.get('change_24h', np.nan)
            except Exception as e:
                logger.warning(f"Failed to fetch ticker data for {symbol}: {e}")
            
            # Fetch funding rate with error handling
            try:
                funding_rate = self.fetch_funding_rate(symbol)
                record['funding_rate'] = funding_rate if funding_rate is not None else np.nan
            except Exception as e:
                logger.warning(f"Failed to fetch funding rate for {symbol}: {e}")
            
            # Fetch long/short ratio with error handling
            try:
                ls_ratio = self.fetch_long_short_ratio(symbol)
                record['long_short_ratio'] = ls_ratio if ls_ratio is not None else np.nan
            except Exception as e:
                logger.warning(f"Failed to fetch long/short ratio for {symbol}: {e}")
            
            # Log success or partial success
            if not pd.isna(record['price']):
                logger.info(f"Successfully fetched data for {symbol}")
            else:
                logger.warning(f"Continuing with null/NaN values for {symbol}")
            
            # Add record to list (whether successful or failed)
            data_records.append(record)
        
        # Create DataFrame from collected records
        df = pd.DataFrame(data_records)
        
        # Log summary of fetch results
        successful_count = df['price'].notna().sum()
        failed_count = len(df) - successful_count
        logger.info(f"Data fetch complete: {successful_count} successful, {failed_count} failed")
        
        return df
