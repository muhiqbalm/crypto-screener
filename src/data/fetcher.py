"""
Market Data Fetcher Module

Fetches market data for perpetual futures contracts from exchanges.
"""

import logging
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
        
        Uses OKX's Rubik API:
        GET /api/v5/rubik/stat/contracts/long-short-account-ratio-contract
        
        The ratio represents the proportion of accounts with net long positions
        to those with net short positions.
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            float: Long/short ratio (e.g., 1.5 means 1.5x more longs than shorts)
        """
        try:
            # Convert CCXT symbol format to OKX instId format
            # 'BTC/USDT:USDT' -> 'BTC-USDT-SWAP'
            market = self.exchange.market(symbol)
            inst_id = market['id']  # e.g., 'BTC-USDT-SWAP'
            
            # Extract base currency from symbol (e.g., 'BTC' from 'BTC/USDT:USDT')
            base_currency = market['base']  # e.g., 'BTC'
            
            # Try CCXT's built-in method first (newer versions)
            if hasattr(self.exchange, 'fetch_long_short_ratio'):
                try:
                    ls_data = self.exchange.fetch_long_short_ratio(symbol)
                    if ls_data and len(ls_data) > 0:
                        latest = ls_data[-1] if isinstance(ls_data, list) else ls_data
                        ratio = latest.get('longShortRatio', None)
                        if ratio is not None:
                            logger.debug(f"Fetched long/short ratio for {symbol}: {ratio}")
                            return float(ratio)
                except Exception:
                    pass  # Fall through to manual API call
            
            # Fallback: Call OKX Rubik API directly
            # Use the contract-specific endpoint which requires instId
            # GET /api/v5/rubik/stat/contracts/long-short-account-ratio-contract
            response = self.exchange.publicGetRubikStatContractsLongShortAccountRatioContract({
                'instId': inst_id,
                'period': '5m'  # 5-minute period for most recent data
            })
            
            if response and 'data' in response and len(response['data']) > 0:
                # Get the most recent data point
                latest_data = response['data'][0]
                # OKX returns 'longShortRatio' field
                ratio = float(latest_data.get('longShortRatio', 0))
                logger.debug(f"Fetched long/short ratio for {symbol}: {ratio}")
                return ratio
            
            logger.warning(f"Long/short ratio data not available for {symbol}")
            return None
            
        except Exception as e:
            logger.warning(f"Failed to fetch long/short ratio for {symbol}: {e}")
            return None
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = '1d', limit: int = 30) -> list:
        """
        Fetch OHLCV (candlestick) data for momentum calculation.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT')
            timeframe: Candle timeframe (default: '1d' for daily)
            limit: Number of candles to fetch (default: 30 for 30-day momentum)
            
        Returns:
            list: List of OHLCV candles [[timestamp, open, high, low, close, volume], ...]
            
        Raises:
            Exception: If OHLCV data cannot be fetched
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            logger.debug(f"Fetched {len(ohlcv)} OHLCV candles for {symbol}")
            return ohlcv
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV data for {symbol}: {e}")
            raise
    
    def calculate_momentum_30d(self, symbol: str) -> float:
        """
        Calculate 30-day price momentum from OHLCV data.
        
        Momentum = (current_price - price_30d_ago) / price_30d_ago * 100
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            float: 30-day momentum as percentage, or None if calculation fails
        """
        try:
            ohlcv = self.fetch_ohlcv(symbol, '1d', limit=31)  # 31 to ensure we have 30 days
            
            if len(ohlcv) < 2:
                logger.warning(f"Insufficient OHLCV data for {symbol} momentum calculation")
                return None
            
            # Get closing prices
            # OHLCV format: [timestamp, open, high, low, close, volume]
            current_close = ohlcv[-1][4]  # Most recent close
            old_close = ohlcv[0][4]       # Oldest close (approximately 30 days ago)
            
            if old_close == 0:
                logger.warning(f"Zero price in historical data for {symbol}")
                return None
            
            # Calculate momentum as percentage change
            momentum = ((current_close - old_close) / old_close) * 100
            
            logger.debug(f"Calculated 30-day momentum for {symbol}: {momentum:.2f}%")
            return momentum
            
        except Exception as e:
            logger.warning(f"Failed to calculate momentum for {symbol}: {e}")
            return None
    
    def fetch_all_data(self) -> pd.DataFrame:
        """
        Fetch all market data fields for all symbols with graceful error handling.
        
        This method loops through the symbol list and fetches ticker data, funding rate,
        long/short ratio, and 30-day momentum for each symbol. If any field fails to fetch,
        it logs a warning and continues, setting NaN values for failed fields.
        
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
                - momentum_30d: 30-day price momentum percentage (float, NaN if failed)
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
                'long_short_ratio': np.nan,
                'momentum_30d': np.nan
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
            
            # Fetch 30-day momentum with error handling
            try:
                momentum = self.calculate_momentum_30d(symbol)
                record['momentum_30d'] = momentum if momentum is not None else np.nan
            except Exception as e:
                logger.warning(f"Failed to calculate momentum for {symbol}: {e}")
            
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
