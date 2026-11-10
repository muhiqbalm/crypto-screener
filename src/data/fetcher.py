"""
Market Data Fetcher Module

Fetches market data for perpetual futures contracts from exchanges.
"""

import logging
import threading
import ccxt

logger = logging.getLogger(__name__)


def _as_float_or_none(value):
    """Parse an exchange numeric field; missing/blank/non-numeric -> None."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


class MarketDataFetcher:
    """
    Fetches market data for perpetual futures contracts from the exchange.
    
    This class retrieves real-time market data including price, 24h change,
    funding rate, and long/short ratio for specified cryptocurrency symbols.
    """
    
    # When memoizing, daily candles are fetched once with this many bars and
    # sliced for momentum (31), ATR (15) and MA50 (50).
    DAILY_OHLCV_LIMIT = 50

    def __init__(self, exchange: ccxt.Exchange, symbols: list, memoize: bool = False):
        """
        Initialize MarketDataFetcher with exchange and symbol list.
        
        Args:
            exchange: CCXT exchange instance (e.g., Binance USDT-M Futures)
            symbols: List of perpetual futures symbols (e.g., ['ZEC/USDT:USDT', 'TAO/USDT:USDT'])
            memoize: If True, ticker / daily OHLCV / current OI results are
                cached on this instance so the several derived metrics for a
                symbol share one request each. Use one instance per refresh
                cycle (the cache never expires).
        """
        self.exchange = exchange
        self.symbols = symbols
        self.memoize = memoize
        self._memo: dict = {}
        self._memo_lock = threading.Lock()
        logger.info(f"MarketDataFetcher initialized with {len(symbols)} symbols")
    
    def fetch_ticker_data(self, symbol: str) -> dict:
        """
        Fetch current price, 24-hour change percentage, and 24-hour volume for a symbol.
        
        CCXT Endpoint Mapping:
        - Uses exchange.fetch_ticker(symbol) method
        - Extracts 'last' field for current price
        - Extracts 'percentage' field for 24-hour percentage change
        - Extracts 'quoteVolume' field for 24-hour trading volume (with 'baseVolume' as fallback)
        
        Args:
            symbol: Trading pair symbol (e.g., 'ZEC/USDT:USDT')
            
        Returns:
            dict: Dictionary with 'price', 'change_24h', and 'volume_24h' keys
            
        Raises:
            Exception: If ticker data cannot be fetched
        """
        if self.memoize:
            cached = self._memo_get(('ticker', symbol))
            if cached is not None:
                return dict(cached)
        try:
            # Fetch ticker data from CCXT
            # CCXT endpoint: exchange.fetch_ticker() returns ticker dictionary
            ticker = self.exchange.fetch_ticker(symbol)
            
            # Extract price from 'last' field (most recent trade price)
            price = ticker.get('last', None)
            
            # Extract 24h percentage change from 'percentage' field
            change_24h = ticker.get('percentage', None)
            
            # Extract 24-hour trading volume
            # Prefer quoteVolume (volume in quote currency, e.g., USDT) for consistency across assets
            # Fall back to baseVolume if quoteVolume is not available
            volume_24h = ticker.get('quoteVolume', None)
            if volume_24h is None:
                volume_24h = ticker.get('baseVolume', None)
                if volume_24h is not None:
                    logger.debug(f"Using baseVolume for {symbol} (quoteVolume not available)")
            
            logger.debug(f"Fetched ticker for {symbol}: price={price}, change_24h={change_24h}%, volume_24h={volume_24h}")
            
            result = {
                'price': price,
                'change_24h': change_24h,
                'volume_24h': volume_24h
            }
            if self.memoize:
                self._memo_set(('ticker', symbol), dict(result))
            return result
            
        except Exception as e:
            logger.error(f"Failed to fetch ticker data for {symbol}: {e}")
            raise
    
    def fetch_open_interest(self, symbol: str) -> float:
        """
        Fetch current open interest for a perpetual futures contract.
        
        CCXT Endpoint Mapping:
        - Uses exchange.fetch_open_interest(symbol) method
        - Extracts 'openInterestAmount' or 'openInterest' field from response
        - Open interest represents the total number of outstanding derivative contracts
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            float: Open interest value, or None if data unavailable or request times out
        """
        try:
            # Fetch open interest from CCXT with 5-second timeout
            # CCXT endpoint: exchange.fetch_open_interest() returns open interest info
            open_interest_data = self.exchange.fetch_open_interest(symbol, params={'timeout': 5000})
            
            # Extract open interest from 'openInterestAmount' field (preferred)
            # Fall back to 'openInterest' if 'openInterestAmount' is not available
            open_interest = open_interest_data.get('openInterestAmount', None)
            if open_interest is None:
                open_interest = open_interest_data.get('openInterest', None)
            
            if open_interest is not None:
                # Validate that the value is numeric and within acceptable range
                try:
                    open_interest_value = float(open_interest)
                    
                    # Validate range: must be non-negative and not exceed max value
                    if open_interest_value < 0 or open_interest_value > 999999999999.99:
                        logger.warning(
                            f"Open interest value out of range for {symbol}: {open_interest_value}"
                        )
                        return None
                    
                    logger.debug(f"Fetched open interest for {symbol}: {open_interest_value}")
                    if self.memoize:
                        self._memo_set(('oi', symbol), open_interest_value)
                    return open_interest_value
                    
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid open interest value for {symbol}: {open_interest} - {e}")
                    return None
            else:
                logger.debug(f"Open interest not available for {symbol}")
                return None
                
        except Exception as e:
            # Handle timeout and other exceptions gracefully
            logger.warning(f"Failed to fetch open interest for {symbol}: {e}")
            return None
    
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
        
        Uses Binance Futures API for top trader long/short ratio.
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            float: Long/short ratio (e.g., 1.5 means 1.5x more longs than shorts)
        """
        try:
            import requests
            
            exchange_id = self.exchange.id.lower()
            market = self.exchange.market(symbol)
            
            if exchange_id in ['binance', 'binanceusdm']:
                # Binance Futures API for top trader long/short ratio
                # Extract symbol without slash (e.g., 'BTCUSDT')
                binance_symbol = market['id']  # e.g., 'BTCUSDT'
                
                url = 'https://fapi.binance.com/futures/data/topLongShortAccountRatio'
                params = {
                    'symbol': binance_symbol,
                    'period': '5m',
                    'limit': 1
                }
                
                response = requests.get(url, params=params, timeout=10)
                data = response.json()
                
                ratio = None
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    ratio = _as_float_or_none(data[0].get('longShortRatio'))
                if ratio is not None:
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
        if self.memoize:
            return self._fetch_ohlcv_memoized(symbol, timeframe, limit)
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            logger.debug(f"Fetched {len(ohlcv)} OHLCV candles for {symbol}")
            return ohlcv
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV data for {symbol}: {e}")
            raise
    
    def _memo_get(self, key):
        with self._memo_lock:
            return self._memo.get(key)

    def _memo_set(self, key, value) -> None:
        with self._memo_lock:
            self._memo[key] = value

    def _fetch_ohlcv_memoized(self, symbol: str, timeframe: str, limit: int) -> list:
        """One request per (symbol, timeframe); daily bars fetched once and sliced."""
        fetch_limit = max(limit, self.DAILY_OHLCV_LIMIT) if timeframe == '1d' else limit
        key = ('ohlcv', symbol, timeframe)
        cached = self._memo_get(key)  # (limit_fetched, candles)
        if cached is None or cached[0] < fetch_limit:
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=fetch_limit)
            except Exception as e:
                logger.error(f"Failed to fetch OHLCV data for {symbol}: {e}")
                raise
            logger.debug(f"Fetched {len(ohlcv)} {timeframe} OHLCV candles for {symbol}")
            cached = (fetch_limit, ohlcv)
            self._memo_set(key, cached)
        ohlcv = cached[1]
        return ohlcv[-limit:] if limit else ohlcv

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
    
    def calculate_atr(self, symbol: str, period: int = 14) -> dict:
        """
        Calculate Average True Range for a symbol.
        
        ATR Calculation:
        1. Fetch 15+ daily OHLCV candles
        2. Calculate True Range for each period:
           TR = max(High - Low, |High - Prev Close|, |Low - Prev Close|)
        3. Calculate 14-period SMA of True Range values
        4. Express as percentage of current price
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT')
            period: ATR period (default: 14)
            
        Returns:
            dict: {
                'atr_value': float or None,
                'atr_percent': float or None,
                'volatility_level': str or None  # 'low', 'medium', 'high'
            }
        """
        null_result = {
            'atr_value': None,
            'atr_percent': None,
            'volatility_level': None
        }
        
        try:
            # Fetch OHLCV data: need period + 1 candles to calculate period True Range values
            ohlcv = self.fetch_ohlcv(symbol, '1d', limit=period + 1)
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV data for ATR calculation ({symbol}): {e}")
            return null_result
        
        # Handle insufficient data (< 15 candles for default 14-period ATR)
        if len(ohlcv) < period + 1:
            logger.warning(
                f"Insufficient data for ATR: {symbol} has {len(ohlcv)} candles, need {period + 1}"
            )
            return null_result
        
        # Calculate True Range for each period
        # OHLCV format: [timestamp, open, high, low, close, volume]
        true_ranges = []
        for i in range(1, len(ohlcv)):
            high = ohlcv[i][2]
            low = ohlcv[i][3]
            prev_close = ohlcv[i - 1][4]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        # Calculate ATR as the simple moving average of the last `period` True Range values
        atr_value = sum(true_ranges[-period:]) / period
        
        # Calculate ATR percentage using the most recent candle's closing price
        current_price = ohlcv[-1][4]
        if current_price == 0:
            logger.warning(f"Current price is zero for {symbol}, cannot calculate ATR percentage")
            return null_result
        
        atr_percent = (atr_value / current_price) * 100
        
        # Determine volatility level based on ATR percentage thresholds
        if atr_percent < 3.0:
            volatility_level = 'low'
        elif atr_percent <= 6.0:
            volatility_level = 'medium'
        else:
            volatility_level = 'high'
        
        logger.debug(
            f"Calculated ATR for {symbol}: value={atr_value:.4f}, "
            f"percent={atr_percent:.2f}%, level={volatility_level}"
        )
        
        return {
            'atr_value': atr_value,
            'atr_percent': atr_percent,
            'volatility_level': volatility_level
        }
    
    def calculate_distance_to_ma50(self, symbol: str) -> dict:
        """
        Calculate distance from current price to 50-day Simple Moving Average.
        
        MA50 Calculation:
        1. Fetch 50 daily OHLCV candles
        2. Calculate SMA of closing prices
        3. Get current price from the most recent candle's close
        4. Calculate: ((current_price - MA50) / MA50) * 100
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            dict: {
                'ma50': float or None,           # 50-day SMA value
                'current_price': float or None,  # Current price
                'distance_percent': float or None,  # Distance as percentage
                'position': str or None          # 'above' or 'below'
            }
        """
        null_result = {
            'ma50': None,
            'current_price': None,
            'distance_percent': None,
            'position': None
        }
        
        try:
            # Fetch 50 daily OHLCV candles
            ohlcv = self.fetch_ohlcv(symbol, '1d', limit=50)
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV data for MA50 calculation ({symbol}): {e}")
            return null_result
        
        # Handle insufficient data (< 50 candles)
        if len(ohlcv) < 50:
            logger.warning(
                f"Insufficient data for MA50: {symbol} has {len(ohlcv)} candles, need 50"
            )
            return null_result
        
        # Calculate 50-day SMA from closing prices (index 4 in OHLCV)
        closing_prices = [candle[4] for candle in ohlcv]
        ma50 = sum(closing_prices) / 50
        
        # Get current price from the most recent candle's close
        current_price = ohlcv[-1][4]
        
        if ma50 == 0:
            logger.warning(f"MA50 is zero for {symbol}, cannot calculate distance percentage")
            return null_result
        
        # Calculate distance as ((current_price - MA50) / MA50) * 100
        distance_percent = ((current_price - ma50) / ma50) * 100
        
        # Determine position relative to MA50
        position = 'above' if current_price >= ma50 else 'below'
        
        logger.debug(
            f"Calculated MA50 distance for {symbol}: MA50={ma50:.4f}, "
            f"price={current_price:.4f}, distance={distance_percent:.2f}%, position={position}"
        )
        
        return {
            'ma50': ma50,
            'current_price': current_price,
            'distance_percent': distance_percent,
            'position': position
        }
    
    def fetch_sparkline_data(self, symbol: str) -> dict:
        """
        Fetch 24-hour price sparkline data for visualization.
        
        Sparkline Data Fetching:
        1. Fetch 24 hourly OHLCV candles (1-hour timeframe)
        2. Fallback to 42 4-hour candles if hourly fails (covers ~7 days)
        3. Extract closing prices as sparkline data points
        4. Determine trend direction (uptrend/downtrend)
        5. Calculate 24h change percentage
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            dict: {
                'prices': list of float or None,  # Closing prices for sparkline
                'trend': str or None,             # 'uptrend' or 'downtrend'
                'timeframe': str or None,         # '1h' or '4h'
                'change_percent': float or None   # Percentage change from first to last
            }
        """
        null_result = {
            'prices': None,
            'trend': None,
            'timeframe': None,
            'change_percent': None
        }
        
        # Try fetching 24 hourly candles first
        try:
            ohlcv = self.fetch_ohlcv(symbol, '1h', limit=24)
            timeframe = '1h'
            logger.debug(f"Fetched {len(ohlcv)} hourly candles for sparkline ({symbol})")
        except Exception as e:
            logger.warning(f"Failed to fetch hourly data for sparkline ({symbol}): {e}")
            # Fallback to 4-hour candles (42 candles = ~7 days)
            try:
                ohlcv = self.fetch_ohlcv(symbol, '4h', limit=42)
                timeframe = '4h'
                logger.debug(f"Fetched {len(ohlcv)} 4-hour candles for sparkline ({symbol}) as fallback")
            except Exception as e2:
                logger.error(f"Failed to fetch 4-hour fallback data for sparkline ({symbol}): {e2}")
                return null_result
        
        # Handle insufficient data
        if len(ohlcv) < 2:
            logger.warning(f"Insufficient data for sparkline: {symbol} has {len(ohlcv)} candles")
            return null_result
        
        # Extract closing prices (index 4 in OHLCV)
        closing_prices = [candle[4] for candle in ohlcv]
        
        # Determine trend direction by comparing first and last prices
        first_price = closing_prices[0]
        last_price = closing_prices[-1]
        
        if last_price > first_price:
            trend = 'uptrend'
        elif last_price < first_price:
            trend = 'downtrend'
        else:
            trend = 'neutral'
        
        # Calculate percentage change
        if first_price != 0:
            change_percent = ((last_price - first_price) / first_price) * 100
        else:
            change_percent = 0.0
        
        logger.debug(
            f"Sparkline data for {symbol}: {len(closing_prices)} points, "
            f"trend={trend}, change={change_percent:.2f}%, timeframe={timeframe}"
        )
        
        return {
            'prices': closing_prices,
            'trend': trend,
            'timeframe': timeframe,
            'change_percent': change_percent
        }
    
    def calculate_oi_delta(self, symbol: str) -> dict:
        """
        Calculate Open Interest delta (24-hour change) for a perpetual futures contract.
        
        OI Delta Calculation:
        1. Fetch current Open Interest using Binance API
        2. Fetch historical Open Interest from 24 hours ago
        3. Calculate delta: ((current - 24h_ago) / 24h_ago) * 100
        4. Interpret based on OI delta + price change combination
        
        Interpretation Matrix:
        - OI↑ + Price↑ = New longs opening (bullish)
        - OI↑ + Price↓ = New shorts opening (bearish)
        - OI↓ + Price↑ = Shorts closing (short squeeze)
        - OI↓ + Price↓ = Longs closing (long liquidation)
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            dict: {
                'current_oi': float or None,      # Current open interest
                'oi_24h_ago': float or None,      # OI from 24h ago
                'oi_delta_percent': float or None,  # Percentage change
                'interpretation': str or None     # Market interpretation
            }
        """
        null_result = {
            'current_oi': None,
            'oi_24h_ago': None,
            'oi_delta_percent': None,
            'interpretation': None
        }
        
        try:
            # Fetch current and historical OI
            current_oi = self._fetch_current_oi(symbol)
            oi_24h_ago = self._fetch_historical_oi(symbol, hours_ago=24)
            
            if current_oi is None or oi_24h_ago is None:
                logger.warning(f"Could not fetch OI data for {symbol}")
                return null_result
            
            # Handle zero OI_24h_ago (division by zero protection)
            if oi_24h_ago == 0:
                logger.warning(f"OI 24h ago is zero for {symbol}, cannot calculate delta")
                return null_result
            
            # Calculate OI delta percentage
            oi_delta_percent = ((current_oi - oi_24h_ago) / oi_24h_ago) * 100
            
            # Get price change for interpretation (use existing ticker data if available)
            try:
                ticker = self.fetch_ticker_data(symbol)
                price_change = ticker.get('change_24h', 0)
            except:
                price_change = 0
            
            # Interpret based on OI delta + price change combination
            if oi_delta_percent > 1:  # OI increasing
                if price_change > 0:
                    interpretation = 'New longs opening (bullish)'
                else:
                    interpretation = 'New shorts opening (bearish)'
            elif oi_delta_percent < -1:  # OI decreasing
                if price_change > 0:
                    interpretation = 'Shorts closing (squeeze)'
                else:
                    interpretation = 'Longs closing (liquidation)'
            else:  # OI relatively stable
                interpretation = 'Neutral (OI stable)'
            
            logger.debug(
                f"OI delta for {symbol}: current={current_oi:.2f}, "
                f"24h_ago={oi_24h_ago:.2f}, delta={oi_delta_percent:.2f}%, "
                f"interpretation={interpretation}"
            )
            
            return {
                'current_oi': current_oi,
                'oi_24h_ago': oi_24h_ago,
                'oi_delta_percent': oi_delta_percent,
                'interpretation': interpretation
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate OI delta for {symbol}: {e}")
            return null_result
    
    def _fetch_current_oi(self, symbol: str) -> float:
        """
        Fetch current Open Interest using Binance Futures API.
        
        API Endpoint: GET /fapi/v1/openInterest
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'BTC/USDT:USDT')
            
        Returns:
            float: Current open interest value, or None if fetch fails
        """
        if self.memoize:
            cached = self._memo_get(('oi', symbol))
            if cached is not None:
                return cached
        try:
            import requests
            
            # Get Binance symbol format (e.g., 'BTCUSDT')
            market = self.exchange.market(symbol)
            binance_symbol = market['id']
            
            # Binance Futures API endpoint for current OI
            url = 'https://fapi.binance.com/fapi/v1/openInterest'
            params = {'symbol': binance_symbol}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Extract OI value.  A missing/empty field means "unknown", not
            # zero: a fake 0 would turn into a -100% OI delta downstream.
            oi_value = _as_float_or_none(data.get('openInterest') if isinstance(data, dict) else None)
            if oi_value is None:
                logger.warning(f"Current OI missing in Binance response for {symbol}")
                return None
            logger.debug(f"Current OI for {symbol}: {oi_value}")

            if self.memoize:
                self._memo_set(('oi', symbol), oi_value)
            return oi_value
            
        except Exception as e:
            logger.error(f"Failed to fetch current OI for {symbol}: {e}")
            return None
    
    def _fetch_historical_oi(self, symbol: str, hours_ago: int = 24) -> float:
        """
        Fetch historical Open Interest using Binance Futures API.
        
        API Endpoint: GET /futures/data/openInterestHist
        
        Args:
            symbol: Perpetual futures symbol (e.g., 'BTC/USDT:USDT')
            hours_ago: How many hours back to fetch (default: 24)
            
        Returns:
            float: Historical open interest value, or None if fetch fails
        """
        try:
            import requests
            import time
            
            # Get Binance symbol format (e.g., 'BTCUSDT')
            market = self.exchange.market(symbol)
            binance_symbol = market['id']
            
            # Calculate timestamp for hours_ago
            current_time = int(time.time() * 1000)  # milliseconds
            target_time = current_time - (hours_ago * 60 * 60 * 1000)
            
            # Binance Futures API endpoint for historical OI
            url = 'https://fapi.binance.com/futures/data/openInterestHist'
            params = {
                'symbol': binance_symbol,
                'period': '1h',  # 1-hour intervals
                'limit': hours_ago + 1,  # Get enough data points
                'endTime': current_time
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data or len(data) == 0:
                logger.warning(f"No historical OI data for {symbol}")
                return None
            
            # Find the data point closest to target_time
            # Data is sorted by timestamp ascending
            closest_point = min(data, key=lambda x: abs(x['timestamp'] - target_time))
            oi_value = _as_float_or_none(closest_point.get('sumOpenInterest'))
            if oi_value is None:
                logger.warning(f"Historical OI missing in Binance response for {symbol}")
                return None
            
            logger.debug(f"Historical OI for {symbol} ({hours_ago}h ago): {oi_value}")
            
            return oi_value
            
        except Exception as e:
            logger.error(f"Failed to fetch historical OI for {symbol}: {e}")
            return None
