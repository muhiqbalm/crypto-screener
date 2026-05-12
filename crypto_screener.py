#!/usr/bin/env python3
"""
Crypto Screener System (LEGACY FILE - DEPRECATED)

WARNING: This is a legacy monolithic file. Please use the modular structure in src/ instead.
The main entry point is now main.py which uses the modular components.

This file is kept for reference only and uses OKX exchange which is no longer supported.
For production use, please use:
- main.py (entry point)
- src/exchange/connector.py (Binance USDT-M Futures)
- src/data/fetcher.py (market data)
- src/signals/ (signal generation)
- src/visualization/ (dashboard)

A real-time cryptocurrency asset screener that fetches market data from OKX exchange,
applies quantitative scoring algorithms, and generates static visualization dashboards.

Requirements: ccxt, pandas, numpy, matplotlib, seaborn
"""

import sys
import logging
from datetime import datetime

# Dependency validation - check all required libraries are available
try:
    import ccxt
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError as e:
    print(f"ERROR: Missing required dependency: {e}")
    print("Please install dependencies using: pip install -r requirements.txt")
    print("Required packages: ccxt, pandas, numpy, matplotlib, seaborn")
    sys.exit(1)


# Configure logging with appropriate severity levels
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'crypto_screener_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)


class ExchangeConnector:
    """
    Manages connection to OKX exchange via CCXT library.
    
    This class initializes and validates the connection to OKX exchange,
    ensuring that Binance is NOT used (per regional restrictions).
    """
    
    def __init__(self, exchange_id: str = 'okx'):
        """
        Initialize CCXT exchange instance.
        
        Args:
            exchange_id: Exchange identifier (default: 'okx')
            
        Raises:
            ValueError: If exchange_id is 'binance' (blocked exchange)
        """
        # Validate that Binance is NOT used
        if exchange_id.lower() == 'binance':
            error_msg = "Binance exchange is not allowed due to regional restrictions"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.exchange_id = exchange_id
        self.exchange = None
        logger.info(f"ExchangeConnector initialized with exchange: {exchange_id}")
    
    def connect(self) -> bool:
        """
        Establish connection to the exchange and validate availability.
        
        Returns:
            bool: True if connection successful, False otherwise
            
        Raises:
            ConnectionError: If connection to exchange fails
        """
        try:
            # Initialize the exchange instance
            logger.info(f"Attempting to connect to {self.exchange_id} exchange...")
            
            # Get the exchange class dynamically
            if not hasattr(ccxt, self.exchange_id):
                raise ValueError(f"Exchange '{self.exchange_id}' is not supported by CCXT")
            
            exchange_class = getattr(ccxt, self.exchange_id)
            self.exchange = exchange_class()
            
            # Load markets to validate connection
            self.exchange.load_markets()
            
            logger.info(f"Successfully connected to {self.exchange_id} exchange")
            logger.info(f"Loaded {len(self.exchange.markets)} markets")
            return True
            
        except ccxt.NetworkError as e:
            error_msg = f"Network error connecting to {self.exchange_id} exchange: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
            
        except ccxt.ExchangeError as e:
            error_msg = f"{self.exchange_id} exchange error: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
            
        except Exception as e:
            error_msg = f"Unexpected error connecting to {self.exchange_id} exchange: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
    
    def get_exchange(self) -> ccxt.Exchange:
        """
        Return the configured exchange instance.
        
        Returns:
            ccxt.Exchange: The configured exchange instance
            
        Raises:
            RuntimeError: If exchange is not connected (connect() not called)
        """
        if self.exchange is None:
            error_msg = "Exchange not connected. Call connect() first."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        return self.exchange


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


class SignalGenerator:
    """
    Generates trading signals from market data.
    
    This class implements simulated quantitative trading signals including:
    - 1-day reversal signal: Identifies potential price reversals based on recent moves
    - 30-day momentum signal: Identifies trending price movements (simulated)
    
    All signals are normalized using z-score normalization to enable meaningful
    combination across different signal types.
    """
    
    def calculate_reversal_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate 1-day reversal signal for each asset.
        
        Simulated Logic:
        - Reversal signal = -1 * change_24h
        - Rationale: Assets that moved down recently may reverse upward (mean reversion)
        - Assets that moved up recently may reverse downward (profit taking)
        - This is a simplified mean-reversion signal for MVP demonstration
        
        Real Implementation Note:
        - Production version would use statistical measures (z-scores of returns,
          RSI divergence, volume-weighted price action, etc.)
        - Would incorporate multiple timeframes and volatility adjustments
        
        Args:
            df: DataFrame with 'change_24h' column (24-hour percentage change)
            
        Returns:
            pd.Series: Reversal signal values (higher = stronger reversal potential)
            
        Raises:
            KeyError: If 'change_24h' column is missing from DataFrame
        """
        if 'change_24h' not in df.columns:
            error_msg = "DataFrame must contain 'change_24h' column"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_reversal_signal")
            return pd.Series(dtype=float)
        
        # Calculate reversal signal: negative of recent price change
        # Interpretation: If price went up 5%, reversal signal is -5 (expect downward reversal)
        #                If price went down 5%, reversal signal is +5 (expect upward reversal)
        reversal_signal = -1 * df['change_24h']
        
        logger.debug(f"Calculated reversal signal for {len(reversal_signal)} assets")
        return reversal_signal
    
    def calculate_momentum_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate 30-day momentum signal for each asset.
        
        Simulated Logic:
        - Momentum signal = change_24h * random_factor
        - Random factor simulates longer-term trend strength (placeholder for real calculation)
        - This is a simplified momentum signal for MVP demonstration
        
        Real Implementation Note:
        - Production version would calculate actual 30-day returns or moving average crossovers
        - Would use historical price data to compute trend strength
        - Would incorporate volume, volatility, and market regime indicators
        - Current implementation uses 24h change as proxy since we don't have historical data
        
        Args:
            df: DataFrame with 'change_24h' column (24-hour percentage change)
            
        Returns:
            pd.Series: Momentum signal values (higher = stronger momentum)
            
        Raises:
            KeyError: If 'change_24h' column is missing from DataFrame
        """
        if 'change_24h' not in df.columns:
            error_msg = "DataFrame must contain 'change_24h' column"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_momentum_signal")
            return pd.Series(dtype=float)
        
        # Simulated momentum calculation using random factor
        # In production, this would be replaced with actual 30-day price momentum
        # Random factor between 0.5 and 1.5 simulates varying trend strengths
        import random
        random.seed(42)  # Fixed seed for reproducibility in testing
        
        momentum_signal = df['change_24h'].apply(
            lambda x: x * random.uniform(0.5, 1.5) if not pd.isna(x) else np.nan
        )
        
        logger.debug(f"Calculated momentum signal for {len(momentum_signal)} assets")
        logger.warning("Momentum signal is SIMULATED - implement real 30-day calculation for production")
        
        return momentum_signal
    
    def normalize_signal(self, signal: pd.Series) -> pd.Series:
        """
        Normalize signal values using z-score normalization.
        
        Z-score normalization formula: (x - mean) / std
        
        This transforms the signal to have:
        - Mean ≈ 0
        - Standard deviation ≈ 1
        
        Normalization enables meaningful combination of signals with different scales
        and distributions. For example, reversal signals might range from -10 to +10,
        while momentum signals might range from -50 to +50. After normalization,
        both signals are on the same scale and can be weighted and combined.
        
        Edge Cases Handled:
        - Empty series: Returns empty series
        - Single value: Returns series of zeros (cannot normalize single point)
        - Zero variance (all identical values): Returns series of zeros
        - NaN values: Preserved in output (not included in mean/std calculation)
        
        Args:
            signal: Series of signal values to normalize
            
        Returns:
            pd.Series: Normalized signal values (z-scores)
        """
        # Handle empty series
        if len(signal) == 0:
            logger.warning("Empty series provided to normalize_signal")
            return signal
        
        # Handle single asset case
        if len(signal) == 1:
            logger.warning("Single value in series, returning zero (cannot normalize single point)")
            return pd.Series([0.0], index=signal.index)
        
        # Calculate mean and standard deviation (ignoring NaN values)
        mean = signal.mean()
        std = signal.std()
        
        # Handle zero variance case (all values are identical)
        if std == 0 or pd.isna(std):
            logger.warning("Signal has zero variance (all values identical), returning zeros")
            return pd.Series(0.0, index=signal.index)
        
        # Apply z-score normalization: (x - mean) / std
        normalized = (signal - mean) / std
        
        logger.debug(f"Normalized signal: mean={mean:.4f}, std={std:.4f}")
        
        return normalized


class ICWeightCalculator:
    """
    Manages Information Coefficient (IC) weights for trading signals.
    
    IC weights represent the historical predictive power of each signal type.
    Higher IC weight indicates stronger historical correlation between the signal
    and future returns. These weights are used to combine multiple signals into
    a multi-factor score.
    
    Current Implementation:
    - Uses simulated IC weights for MVP demonstration
    - Real implementation would calculate IC weights from historical backtesting
    - IC weights would be updated periodically based on rolling performance analysis
    """
    
    def __init__(self):
        """
        Initialize with simulated IC weights.
        
        Simulated IC Weights:
        - reversal_1d: 0.3 (30% weight for 1-day reversal signal)
        - momentum_30d: 0.7 (70% weight for 30-day momentum signal)
        
        Rationale for weights:
        - Momentum signals typically have stronger predictive power in trending markets
        - Reversal signals provide diversification and capture mean-reversion opportunities
        - Weights sum to 1.0 for interpretability (though not strictly required)
        
        Real Implementation Note:
        - Production version would calculate IC weights from historical data
        - Would use rolling window analysis (e.g., past 12 months)
        - Would adjust weights based on market regime (trending vs. mean-reverting)
        - Would include confidence intervals and statistical significance tests
        """
        self.weights = {
            'reversal_1d': 0.3,
            'momentum_30d': 0.7
        }
        
        logger.info(f"ICWeightCalculator initialized with weights: {self.weights}")
        logger.warning("IC weights are SIMULATED - implement historical IC calculation for production")
    
    def get_weight(self, signal_name: str) -> float:
        """
        Return IC weight for a specific signal.
        
        Args:
            signal_name: Name of the signal (e.g., 'reversal_1d', 'momentum_30d')
            
        Returns:
            float: IC weight for the signal (0.0 to 1.0 typically)
            
        Raises:
            KeyError: If signal_name is not found in weights dictionary
        """
        if signal_name not in self.weights:
            error_msg = f"Signal '{signal_name}' not found in IC weights. Available signals: {list(self.weights.keys())}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        weight = self.weights[signal_name]
        logger.debug(f"Retrieved IC weight for '{signal_name}': {weight}")
        
        return weight


class MultiFactorScorer:
    """
    Combines multiple trading signals into a multi-factor score.
    
    This class takes normalized signals and IC weights to calculate a composite
    score for each asset. The multi-factor score is a weighted combination of
    individual signals, where weights represent the historical predictive power
    (Information Coefficient) of each signal.
    
    The class also classifies assets into tiers based on their scores:
    - Tier A: Top 50% of assets by score (highest scoring)
    - Tier B: Bottom 50% of assets by score (lower scoring)
    """
    
    def __init__(self, ic_calculator: ICWeightCalculator):
        """
        Initialize MultiFactorScorer with IC weight calculator.
        
        Args:
            ic_calculator: ICWeightCalculator instance providing signal weights
        """
        self.ic_calculator = ic_calculator
        logger.info("MultiFactorScorer initialized")
    
    def calculate_score(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate multi-factor score as weighted combination of normalized signals.
        
        Formula: score = w1 * signal1 + w2 * signal2 + ... + wn * signaln
        
        For the current implementation:
        score = 0.3 * reversal_signal + 0.7 * momentum_signal
        
        The signals must be normalized (z-scores) before being passed to this method
        to ensure they are on comparable scales. The IC weights determine the relative
        importance of each signal in the final score.
        
        Args:
            df: DataFrame with normalized signal columns:
                - 'reversal_signal': Normalized 1-day reversal signal
                - 'momentum_signal': Normalized 30-day momentum signal
                
        Returns:
            pd.Series: Multi-factor score for each asset (higher = better)
            
        Raises:
            KeyError: If required signal columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['reversal_signal', 'momentum_signal']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_score")
            return pd.Series(dtype=float)
        
        # Get IC weights for each signal
        w_reversal = self.ic_calculator.get_weight('reversal_1d')
        w_momentum = self.ic_calculator.get_weight('momentum_30d')
        
        # Calculate weighted combination of signals
        # score = w1 * signal1 + w2 * signal2
        multi_factor_score = (
            w_reversal * df['reversal_signal'] +
            w_momentum * df['momentum_signal']
        )
        
        logger.info(f"Calculated multi-factor scores for {len(multi_factor_score)} assets")
        logger.debug(f"Score range: [{multi_factor_score.min():.4f}, {multi_factor_score.max():.4f}]")
        
        return multi_factor_score
    
    def classify_tiers(self, scores: pd.Series) -> pd.Series:
        """
        Classify assets into Tier A (top 50%) and Tier B (bottom 50%) based on scores.
        
        Tier Classification:
        - Tier A: Assets with scores in the top 50% (highest scoring half)
        - Tier B: Assets with scores in the bottom 50% (lower scoring half)
        
        The classification uses the median score as the threshold:
        - score >= median → Tier A
        - score < median → Tier B
        
        This ensures exactly 50% of assets are in each tier (or as close as possible
        when there's an odd number of assets or ties at the median).
        
        Args:
            scores: Series of multi-factor scores for assets
            
        Returns:
            pd.Series: Tier classification ('A' or 'B') for each asset
        """
        # Handle empty series
        if len(scores) == 0:
            logger.warning("Empty series provided to classify_tiers")
            return pd.Series(dtype=str)
        
        # Handle single asset case
        if len(scores) == 1:
            logger.info("Single asset provided, classifying as Tier A")
            return pd.Series(['A'], index=scores.index)
        
        # Calculate median score as threshold
        median_score = scores.median()
        
        # Classify assets: >= median is Tier A, < median is Tier B
        tiers = scores.apply(lambda score: 'A' if score >= median_score else 'B')
        
        # Log tier distribution
        tier_counts = tiers.value_counts()
        logger.info(f"Tier classification complete: {tier_counts.to_dict()}")
        logger.debug(f"Median score threshold: {median_score:.4f}")
        
        return tiers


class RankingEngine:
    """
    Ranks assets by multi-factor score.
    
    This class sorts assets in descending order by their multi-factor scores
    and assigns ranking positions. The ranking uses a stable sort algorithm
    to preserve the relative order of assets with equal scores.
    
    Ranking Properties:
    - Assets are sorted by multi_factor_score in descending order (highest first)
    - Rank 1 = highest score, Rank 2 = second highest, etc.
    - Stable sort ensures assets with equal scores maintain their original relative order
    - All original DataFrame columns are preserved in the output
    """
    
    def rank_assets(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Sort DataFrame by multi_factor_score descending and add rank column.
        
        This method performs the following operations:
        1. Validates that the DataFrame contains a 'multi_factor_score' column
        2. Sorts the DataFrame by 'multi_factor_score' in descending order
        3. Uses stable sort (kind='mergesort') to preserve relative order for equal scores
        4. Adds a 'rank' column with position numbers (1 = highest score)
        5. Returns the sorted DataFrame with all original columns plus rank
        
        Stable Sort Behavior:
        - When two assets have the same multi_factor_score, their relative order
          from the input DataFrame is preserved in the output
        - This ensures deterministic and reproducible ranking results
        - Example: If assets A and B both have score 0.5, and A appears before B
          in the input, then A will appear before B in the output
        
        Args:
            df: DataFrame with 'multi_factor_score' column and other asset data
            
        Returns:
            pd.DataFrame: Sorted DataFrame with added 'rank' column
                - All original columns are preserved
                - Sorted by multi_factor_score descending
                - 'rank' column contains position numbers (1, 2, 3, ...)
                
        Raises:
            KeyError: If 'multi_factor_score' column is missing from DataFrame
        """
        # Validate required column exists
        if 'multi_factor_score' not in df.columns:
            error_msg = "DataFrame must contain 'multi_factor_score' column"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to rank_assets")
            # Return empty DataFrame with rank column added
            df_ranked = df.copy()
            df_ranked['rank'] = pd.Series(dtype=int)
            return df_ranked
        
        # Sort DataFrame by multi_factor_score in descending order
        # Use stable sort (kind='mergesort') to preserve relative order for equal scores
        # ascending=False means highest scores come first
        df_sorted = df.sort_values(
            by='multi_factor_score',
            ascending=False,
            kind='mergesort',  # Stable sort algorithm
            ignore_index=False  # Preserve original index
        ).reset_index(drop=True)  # Reset index to get clean sequential indices
        
        # Add rank column with position numbers (1 = highest score)
        # rank = index + 1 (since index starts at 0)
        df_sorted['rank'] = range(1, len(df_sorted) + 1)
        
        # Log ranking results
        logger.info(f"Ranked {len(df_sorted)} assets by multi-factor score")
        if len(df_sorted) > 0:
            top_score = df_sorted.iloc[0]['multi_factor_score']
            bottom_score = df_sorted.iloc[-1]['multi_factor_score']
            logger.debug(f"Top ranked score: {top_score:.4f}, Bottom ranked score: {bottom_score:.4f}")
        
        return df_sorted


class MultiFactorPanel:
    """
    Renders multi-factor score visualization panel.
    
    This class creates a horizontal bar chart displaying the composite multi-factor
    score for each asset. Assets are ordered by score (highest to lowest) and colored
    by tier classification:
    - Tier A (top 50%): Darker color #C85A82
    - Tier B (bottom 50%): Lighter shade #E8A5B8
    
    The visualization includes numeric score values displayed on or near each bar
    for easy reading.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for multi-factor scores.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (highest at top)
        2. X-axis: Multi-factor score values
        3. Bar colors: Tier A uses #C85A82 (darker), Tier B uses #E8A5B8 (lighter)
        4. Score labels: Numeric values displayed on each bar for readability
        5. Panel title: Descriptive title indicating multi-factor score content
        
        Color Scheme Rationale:
        - Darker color (#C85A82) for Tier A draws attention to top-performing assets
        - Lighter shade (#E8A5B8) for Tier B provides visual hierarchy
        - Both colors are from the same family for cohesive appearance
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'multi_factor_score': Composite score (float)
                - 'tier': Tier classification ('A' or 'B')
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'multi_factor_score', 'tier']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for MultiFactorPanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to MultiFactorPanel.render()")
            ax.text(0.5, 0.5, 'No data available', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # We'll reverse the order for plotting so highest scores appear at the top
        symbols = df['symbol'].values[::-1]  # Reverse for top-to-bottom display
        scores = df['multi_factor_score'].values[::-1]
        tiers = df['tier'].values[::-1]
        
        # Define colors for each tier
        # Tier A: Darker color #C85A82 (strong pink/rose)
        # Tier B: Lighter shade #E8A5B8 (light pink/rose)
        tier_colors = {
            'A': '#C85A82',  # Darker color for top-performing assets
            'B': '#E8A5B8'   # Lighter shade for lower-performing assets
        }
        
        # Map each asset to its tier color
        bar_colors = [tier_colors.get(tier, '#CCCCCC') for tier in tiers]
        
        # Create horizontal bar chart
        # Y-axis: Asset symbols (ordered by score, highest at top)
        # X-axis: Multi-factor score values
        bars = ax.barh(symbols, scores, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add numeric score values on each bar for readability
        # Position labels at the end of each bar (or inside if bar is long enough)
        for i, (bar, score) in enumerate(zip(bars, scores)):
            # Get bar width (score value)
            width = bar.get_width()
            
            # Determine label position: inside bar if positive, outside if negative
            if width >= 0:
                # Positive score: place label inside bar at the right edge
                label_x = width - 0.05 * abs(ax.get_xlim()[1] - ax.get_xlim()[0])
                ha = 'right'
            else:
                # Negative score: place label inside bar at the left edge
                label_x = width + 0.05 * abs(ax.get_xlim()[1] - ax.get_xlim()[0])
                ha = 'left'
            
            # Add text label with score value
            ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                   f'{score:.3f}',  # Format to 3 decimal places
                   ha=ha, va='center',
                   color='white', fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Multi-Factor Score by Asset', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Multi-Factor Score', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Add vertical reference line at 0 for visual reference
        ax.axvline(x=0, color='black', linestyle='-', linewidth=0.8, alpha=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"MultiFactorPanel rendered with {len(df)} assets")


class FundingRatePanel:
    """
    Renders funding rate visualization panel.
    
    This class creates a horizontal bar chart displaying the funding rate percentage
    for each asset. Assets are ordered consistently with the multi-factor panel
    (by multi-factor score, highest to lowest). Bars are colored based on the sign
    of the funding rate:
    - Negative rates (short bias/squeeze potential): Green/blue color scheme
    - Positive rates (crowded long positions): Red/orange color scheme
    
    A vertical reference line at 0% helps identify the transition between negative
    and positive funding rates.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for funding rates.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (same order as multi-factor panel)
        2. X-axis: Funding rate percentage values
        3. Reference line: Vertical line at 0% to separate negative/positive rates
        4. Bar colors:
           - Negative rates: #4CAF50 (green) - indicates short bias or squeeze potential
           - Positive rates: #FF5722 (red/orange) - indicates crowded long positions
        5. Panel title: Descriptive title indicating funding rate content
        
        Color Scheme Rationale:
        - Green for negative rates: Suggests potential short squeeze opportunity
        - Red/orange for positive rates: Warning color for crowded long positions
        - 0% reference line: Clear visual separator between the two regimes
        
        Funding Rate Interpretation:
        - Negative funding rate: Shorts pay longs (short bias in market)
        - Positive funding rate: Longs pay shorts (long bias in market)
        - Extreme rates (far from 0%) indicate crowded positioning
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'funding_rate': Funding rate percentage (float)
                - 'multi_factor_score': Used for ordering (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'funding_rate']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for FundingRatePanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to FundingRatePanel.render()")
            ax.text(0.5, 0.5, 'No data available', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # We'll reverse the order for plotting so highest scores appear at the top
        # This ensures Y-axis order matches the multi-factor panel
        symbols = df['symbol'].values[::-1]  # Reverse for top-to-bottom display
        funding_rates = df['funding_rate'].values[::-1]
        
        # Define colors based on funding rate sign
        # Negative rates: Green (#4CAF50) - short bias, potential squeeze
        # Positive rates: Red/orange (#FF5722) - long bias, crowded positioning
        bar_colors = []
        for rate in funding_rates:
            if pd.isna(rate):
                # Handle missing data with neutral gray color
                bar_colors.append('#CCCCCC')
            elif rate < 0:
                # Negative funding rate: green (short bias)
                bar_colors.append('#4CAF50')
            else:
                # Positive funding rate: red/orange (long bias)
                bar_colors.append('#FF5722')
        
        # Create horizontal bar chart
        # Y-axis: Asset symbols (same order as multi-factor panel)
        # X-axis: Funding rate percentage values
        bars = ax.barh(symbols, funding_rates, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add vertical reference line at 0% to separate negative/positive rates
        # This line helps identify the transition between short bias and long bias
        ax.axvline(x=0, color='black', linestyle='-', linewidth=1.2, alpha=0.7, zorder=3)
        
        # Add numeric funding rate values on each bar for readability
        # Position labels at the end of each bar (or inside if bar is long enough)
        for i, (bar, rate) in enumerate(zip(bars, funding_rates)):
            # Skip label if rate is NaN
            if pd.isna(rate):
                continue
            
            # Get bar width (funding rate value)
            width = bar.get_width()
            
            # Determine label position: inside bar if value is large enough, outside if small
            x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0])
            threshold = 0.1 * x_range  # 10% of x-axis range
            
            if abs(width) > threshold:
                # Large bar: place label inside bar
                if width >= 0:
                    label_x = width - 0.02 * x_range
                    ha = 'right'
                else:
                    label_x = width + 0.02 * x_range
                    ha = 'left'
                text_color = 'white'
            else:
                # Small bar: place label outside bar
                if width >= 0:
                    label_x = width + 0.02 * x_range
                    ha = 'left'
                else:
                    label_x = width - 0.02 * x_range
                    ha = 'right'
                text_color = 'black'
            
            # Add text label with funding rate value
            ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                   f'{rate:.4f}%',  # Format to 4 decimal places (funding rates are typically small)
                   ha=ha, va='center',
                   color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Funding Rate by Asset', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Funding Rate (%)', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"FundingRatePanel rendered with {len(df)} assets")


class LongShortRatioPanel:
    """
    Renders long/short ratio visualization panel.
    
    This class creates a horizontal bar chart displaying the long/short ratio
    for each asset. Assets are ordered consistently with the multi-factor panel
    (by multi-factor score, highest to lowest). Bars exceeding the 1.5 threshold
    are highlighted to indicate crowded long positioning.
    
    Two vertical reference lines are displayed:
    - 1.0 (neutral): Equal long and short positions
    - 1.5 (warning): Threshold for crowded long positioning
    
    Ratios above 1.5 indicate potentially overcrowded long positions that may
    be vulnerable to reversal or liquidation cascades.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for long/short ratios.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (same order as multi-factor panel)
        2. X-axis: Long/short ratio values
        3. Reference lines:
           - Vertical line at 1.0 (neutral positioning)
           - Vertical line at 1.5 (warning threshold for crowded longs)
        4. Bar colors:
           - Normal (ratio <= 1.5): #2196F3 (blue) - normal positioning
           - Warning (ratio > 1.5): #FFC107 (amber/yellow) - crowded long positioning
        5. Panel title: Descriptive title indicating long/short ratio content
        
        Color Scheme Rationale:
        - Blue for normal ratios: Calm, neutral color for balanced positioning
        - Amber/yellow for high ratios: Warning color for crowded long positions
        - 1.0 reference line: Shows neutral positioning (equal longs and shorts)
        - 1.5 reference line: Shows warning threshold for overcrowded positioning
        
        Long/Short Ratio Interpretation:
        - Ratio = 1.0: Equal long and short positions (neutral)
        - Ratio > 1.0: More longs than shorts (bullish bias)
        - Ratio < 1.0: More shorts than longs (bearish bias)
        - Ratio > 1.5: Crowded long positioning (potential reversal risk)
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'long_short_ratio': Long/short ratio (float)
                - 'multi_factor_score': Used for ordering (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'long_short_ratio']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for LongShortRatioPanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to LongShortRatioPanel.render()")
            ax.text(0.5, 0.5, 'No data available', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # We'll reverse the order for plotting so highest scores appear at the top
        # This ensures Y-axis order matches the multi-factor panel
        symbols = df['symbol'].values[::-1]  # Reverse for top-to-bottom display
        ls_ratios = df['long_short_ratio'].values[::-1]
        
        # Define colors based on long/short ratio threshold
        # Normal (ratio <= 1.5): Blue (#2196F3) - normal positioning
        # Warning (ratio > 1.5): Amber/yellow (#FFC107) - crowded long positioning
        WARNING_THRESHOLD = 1.5
        bar_colors = []
        for ratio in ls_ratios:
            if pd.isna(ratio):
                # Handle missing data with neutral gray color
                bar_colors.append('#CCCCCC')
            elif ratio > WARNING_THRESHOLD:
                # High ratio: amber/yellow (warning for crowded longs)
                bar_colors.append('#FFC107')
            else:
                # Normal ratio: blue (normal positioning)
                bar_colors.append('#2196F3')
        
        # Create horizontal bar chart
        # Y-axis: Asset symbols (same order as multi-factor panel)
        # X-axis: Long/short ratio values
        bars = ax.barh(symbols, ls_ratios, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add vertical reference line at 1.0 (neutral positioning)
        # This line indicates equal long and short positions
        ax.axvline(x=1.0, color='black', linestyle='-', linewidth=1.2, alpha=0.7, zorder=3,
                  label='Neutral (1.0)')
        
        # Add vertical reference line at 1.5 (warning threshold)
        # This line indicates the threshold for crowded long positioning
        ax.axvline(x=1.5, color='red', linestyle='--', linewidth=1.2, alpha=0.7, zorder=3,
                  label='Warning (1.5)')
        
        # Add numeric long/short ratio values on each bar for readability
        # Position labels at the end of each bar (or inside if bar is long enough)
        for i, (bar, ratio) in enumerate(zip(bars, ls_ratios)):
            # Skip label if ratio is NaN
            if pd.isna(ratio):
                continue
            
            # Get bar width (long/short ratio value)
            width = bar.get_width()
            
            # Determine label position: inside bar if value is large enough, outside if small
            x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0])
            threshold = 0.15 * x_range  # 15% of x-axis range
            
            if abs(width) > threshold:
                # Large bar: place label inside bar at the right edge
                label_x = width - 0.02 * x_range
                ha = 'right'
                text_color = 'white'
            else:
                # Small bar: place label outside bar to the right
                label_x = width + 0.02 * x_range
                ha = 'left'
                text_color = 'black'
            
            # Add text label with long/short ratio value
            ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                   f'{ratio:.2f}',  # Format to 2 decimal places
                   ha=ha, va='center',
                   color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Long/Short Ratio by Asset', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Long/Short Ratio', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Add legend for reference lines
        ax.legend(loc='lower right', fontsize=8, framealpha=0.9)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"LongShortRatioPanel rendered with {len(df)} assets")


class DashboardBuilder:
    """
    Builds complete visualization dashboard with three panels.
    
    This class coordinates the creation of a comprehensive dashboard displaying:
    1. Multi-factor scores (top panel)
    2. Funding rates (middle panel)
    3. Long/short ratios (bottom panel)
    
    All three panels share a common Y-axis showing asset symbols ordered by
    multi-factor score (highest to lowest). This consistent ordering enables
    easy visual comparison across different metrics.
    
    The dashboard uses matplotlib's subplot functionality to create a vertical
    stack of three panels with proper spacing and shared axes.
    """
    
    def __init__(self, df: pd.DataFrame):
        """
        Initialize DashboardBuilder with ranked DataFrame.
        
        Args:
            df: Ranked DataFrame containing all required columns:
                - 'symbol': Asset symbol (str)
                - 'multi_factor_score': Composite score (float)
                - 'tier': Tier classification ('A' or 'B')
                - 'funding_rate': Funding rate percentage (float)
                - 'long_short_ratio': Long/short ratio (float)
                
                The DataFrame should already be sorted by multi_factor_score
                in descending order (from RankingEngine).
        
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'multi_factor_score', 'tier', 
                          'funding_rate', 'long_short_ratio']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for DashboardBuilder: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        self.df = df
        self.figure = None
        
        logger.info(f"DashboardBuilder initialized with {len(df)} assets")
    
    def create_dashboard(self):
        """
        Create 3-panel figure with shared Y-axis.
        
        Dashboard Layout:
        - Vertical stack of 3 panels (subplots)
        - Panel 1 (top): Multi-factor scores
        - Panel 2 (middle): Funding rates
        - Panel 3 (bottom): Long/short ratios
        - Shared Y-axis: Asset symbols ordered by multi-factor score
        - Figure size: 12 inches wide x 10 inches tall (suitable for display/print)
        
        The method creates the figure, renders all three panels by calling their
        respective render() methods, and applies tight_layout() for proper spacing.
        
        Returns:
            matplotlib.figure.Figure: The complete dashboard figure
            
        Raises:
            ValueError: If DataFrame is empty or missing required data
            RuntimeError: If matplotlib rendering fails
            Exception: If visualization rendering fails for other reasons
        """
        try:
            # Log warning if DataFrame is empty, but continue to create empty panels
            if len(self.df) == 0:
                logger.warning("Creating dashboard with empty DataFrame (no assets to visualize)")
            else:
                logger.info(f"Creating dashboard with 3 panels for {len(self.df)} assets...")
            
            # Create figure with 3 subplots in vertical stack
            # figsize=(width, height) in inches
            # - Width: 12 inches provides good horizontal space for labels and bars
            # - Height: 10 inches (3-4 inches per panel) provides good vertical space
            # sharex=False: Each panel has independent X-axis (different metrics)
            # sharey=True: All panels share Y-axis (same asset ordering)
            try:
                fig, axes = plt.subplots(
                    nrows=3,           # 3 panels stacked vertically
                    ncols=1,           # Single column
                    figsize=(12, 10),  # Figure size in inches
                    sharex=False,      # Independent X-axes (different metrics)
                    sharey=True        # Shared Y-axis (same asset ordering)
                )
            except Exception as e:
                error_msg = f"Failed to create matplotlib figure: {e}. Check matplotlib installation and display backend."
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Store figure reference
            self.figure = fig
            
            # Render Panel 1: Multi-Factor Score (top panel)
            try:
                logger.info("Rendering multi-factor score panel...")
                multi_factor_panel = MultiFactorPanel()
                multi_factor_panel.render(axes[0], self.df)
                logger.info("Multi-factor score panel rendered successfully")
            except KeyError as e:
                error_msg = f"Failed to render multi-factor score panel: Missing required data column - {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                error_msg = f"Failed to render multi-factor score panel: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Render Panel 2: Funding Rate (middle panel)
            try:
                logger.info("Rendering funding rate panel...")
                funding_rate_panel = FundingRatePanel()
                funding_rate_panel.render(axes[1], self.df)
                logger.info("Funding rate panel rendered successfully")
            except KeyError as e:
                error_msg = f"Failed to render funding rate panel: Missing required data column - {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                error_msg = f"Failed to render funding rate panel: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Render Panel 3: Long/Short Ratio (bottom panel)
            try:
                logger.info("Rendering long/short ratio panel...")
                long_short_panel = LongShortRatioPanel()
                long_short_panel.render(axes[2], self.df)
                logger.info("Long/short ratio panel rendered successfully")
            except KeyError as e:
                error_msg = f"Failed to render long/short ratio panel: Missing required data column - {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                error_msg = f"Failed to render long/short ratio panel: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Apply tight_layout() for proper spacing between panels
            # This automatically adjusts subplot parameters to give specified padding
            # and avoid overlapping labels, titles, and axes
            # pad: Padding between the figure edge and the edges of subplots (in font-size units)
            # h_pad: Height padding between subplots (in font-size units)
            try:
                fig.tight_layout(pad=2.0, h_pad=3.0)
            except Exception as e:
                # tight_layout can fail with certain figure configurations
                # Log warning but don't fail the entire dashboard creation
                logger.warning(f"Failed to apply tight_layout (non-critical): {e}")
            
            logger.info("Dashboard creation complete")
            
            return fig
            
        except (ValueError, RuntimeError) as e:
            # Re-raise specific exceptions with context preserved
            raise
        except Exception as e:
            error_msg = f"Unexpected error during dashboard creation: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def save_dashboard(self, filepath: str):
        """
        Save figure to disk.
        
        This method saves the dashboard figure to a file on disk. The file format
        is automatically determined from the filepath extension (e.g., .png, .pdf, .svg).
        
        Common formats:
        - PNG: Raster format, good for web display and presentations
        - PDF: Vector format, good for printing and publications
        - SVG: Vector format, good for web and editing in vector graphics software
        
        Args:
            filepath: Path where the figure should be saved (e.g., 'dashboard.png')
                     The file extension determines the output format.
        
        Raises:
            RuntimeError: If create_dashboard() has not been called yet
            ValueError: If filepath is invalid or empty
            PermissionError: If file cannot be written due to permissions
            OSError: If file saving fails due to disk/path issues
        """
        # Validate that dashboard has been created
        if self.figure is None:
            error_msg = "Dashboard not created yet. Call create_dashboard() first."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Validate filepath is not empty
        if not filepath or not filepath.strip():
            error_msg = "Filepath cannot be empty"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            logger.info(f"Saving dashboard to {filepath}...")
            
            # Validate file extension is supported
            import os
            _, ext = os.path.splitext(filepath)
            supported_formats = ['.png', '.pdf', '.svg', '.jpg', '.jpeg']
            if ext.lower() not in supported_formats:
                logger.warning(f"File extension '{ext}' may not be supported. Supported formats: {supported_formats}")
            
            # Save figure to disk
            # dpi: Dots per inch (resolution) - 300 is high quality for printing
            # bbox_inches='tight': Trim whitespace around the figure
            # facecolor='white': Set background color to white (default is transparent)
            self.figure.savefig(
                filepath,
                dpi=300,              # High resolution for quality output
                bbox_inches='tight',  # Trim whitespace
                facecolor='white'     # White background
            )
            
            logger.info(f"Dashboard successfully saved to {filepath}")
            
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot write to {filepath}. Check file permissions and ensure the file is not open in another program."
            logger.error(error_msg)
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Failed to save dashboard to {filepath}: {e}. Check that the directory exists and disk space is available."
            logger.error(error_msg)
            raise OSError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error saving dashboard to {filepath}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)


def main():
    """
    Main execution flow for the crypto screener system.
    
    Pipeline stages:
    1. Validate dependencies (completed at import time)
    2. Initialize exchange connector and establish connection
    3. Fetch market data for symbol list
    4. Generate signals and calculate scores
    5. Rank assets
    6. Generate visualization
    7. Save dashboard to disk with timestamp
    
    Each stage is wrapped in try-except blocks for appropriate error handling.
    Errors are logged and the system exits gracefully with descriptive messages.
    
    Requirements: 9.4, 9.5
    """
    logger.info("=" * 70)
    logger.info("Starting Crypto Screener System")
    logger.info("=" * 70)
    
    # Define symbol list for perpetual futures contracts
    SYMBOLS = [
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'ZEC/USDT:USDT',
        'TAO/USDT:USDT',
        'TON/USDT:USDT',
        'AAVE/USDT:USDT',
        'SOL/USDT:USDT'
    ]
    
    logger.info(f"Target symbols: {SYMBOLS}")
    
    # Stage 1: Initialize ExchangeConnector and establish connection
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 1: Initializing exchange connection")
        logger.info("=" * 70)
        
        connector = ExchangeConnector(exchange_id='okx')
        connector.connect()
        exchange = connector.get_exchange()
        
        logger.info("[SUCCESS] Exchange connection established successfully")
        
    except ConnectionError as e:
        logger.error(f"[FAILED] Failed to connect to exchange: {e}")
        logger.error("System cannot proceed without exchange connection")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Unexpected error during exchange initialization: {e}")
        sys.exit(1)
    
    # Stage 2: Create MarketDataFetcher and fetch all data
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 2: Fetching market data")
        logger.info("=" * 70)
        
        fetcher = MarketDataFetcher(exchange=exchange, symbols=SYMBOLS)
        market_data_df = fetcher.fetch_all_data()
        
        # Log summary of fetched data
        successful_fetches = market_data_df['price'].notna().sum()
        logger.info(f"[SUCCESS] Market data fetch complete: {successful_fetches}/{len(SYMBOLS)} symbols successful")
        
        # Check if we have at least some data to proceed
        if successful_fetches == 0:
            logger.error("[FAILED] No market data could be fetched for any symbol")
            logger.error("System cannot proceed without market data")
            sys.exit(1)
        
        logger.info(f"\nFetched data preview:\n{market_data_df.to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to fetch market data: {e}")
        sys.exit(1)
    
    # Stage 3: Create SignalGenerator and generate signals
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 3: Generating trading signals")
        logger.info("=" * 70)
        
        signal_generator = SignalGenerator()
        
        # Calculate reversal signal
        reversal_signal = signal_generator.calculate_reversal_signal(market_data_df)
        logger.info("[SUCCESS] Reversal signal calculated")
        
        # Calculate momentum signal
        momentum_signal = signal_generator.calculate_momentum_signal(market_data_df)
        logger.info("[SUCCESS] Momentum signal calculated")
        
        # Normalize signals
        reversal_signal_norm = signal_generator.normalize_signal(reversal_signal)
        momentum_signal_norm = signal_generator.normalize_signal(momentum_signal)
        logger.info("[SUCCESS] Signals normalized")
        
        # Add normalized signals to DataFrame
        market_data_df['reversal_signal'] = reversal_signal_norm
        market_data_df['momentum_signal'] = momentum_signal_norm
        
        logger.info(f"\nSignals preview:\n{market_data_df[['symbol', 'reversal_signal', 'momentum_signal']].to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to generate signals: {e}")
        sys.exit(1)
    
    # Stage 4: Create ICWeightCalculator and MultiFactorScorer
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 4: Calculating multi-factor scores")
        logger.info("=" * 70)
        
        # Initialize IC weight calculator
        ic_calculator = ICWeightCalculator()
        logger.info("[SUCCESS] IC weight calculator initialized")
        
        # Initialize multi-factor scorer
        scorer = MultiFactorScorer(ic_calculator=ic_calculator)
        logger.info("[SUCCESS] Multi-factor scorer initialized")
        
        # Calculate multi-factor scores
        multi_factor_scores = scorer.calculate_score(market_data_df)
        market_data_df['multi_factor_score'] = multi_factor_scores
        logger.info("[SUCCESS] Multi-factor scores calculated")
        
        # Classify tiers
        tiers = scorer.classify_tiers(multi_factor_scores)
        market_data_df['tier'] = tiers
        logger.info("[SUCCESS] Tier classification complete")
        
        logger.info(f"\nScores and tiers preview:\n{market_data_df[['symbol', 'multi_factor_score', 'tier']].to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to calculate multi-factor scores: {e}")
        sys.exit(1)
    
    # Stage 5: Create RankingEngine and rank assets
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 5: Ranking assets")
        logger.info("=" * 70)
        
        ranking_engine = RankingEngine()
        ranked_df = ranking_engine.rank_assets(market_data_df)
        
        logger.info("[SUCCESS] Assets ranked by multi-factor score")
        logger.info(f"\nFinal rankings:\n{ranked_df[['rank', 'symbol', 'multi_factor_score', 'tier']].to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to rank assets: {e}")
        sys.exit(1)
    
    # Stage 6: Create DashboardBuilder and generate visualization
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 6: Generating visualization dashboard")
        logger.info("=" * 70)
        
        dashboard_builder = DashboardBuilder(df=ranked_df)
        figure = dashboard_builder.create_dashboard()
        
        logger.info("[SUCCESS] Dashboard visualization created")
        
    except ValueError as e:
        logger.error(f"[FAILED] Visualization failed due to invalid data: {e}")
        logger.error("This may be caused by missing required columns or empty dataset")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"[FAILED] Visualization rendering failed: {e}")
        logger.error("This may be caused by matplotlib configuration or display backend issues")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Unexpected error during visualization: {e}")
        sys.exit(1)
    
    # Stage 7: Save dashboard to disk with timestamp in filename
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 7: Saving dashboard to disk")
        logger.info("=" * 70)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"crypto_screener_dashboard_{timestamp}.png"
        
        dashboard_builder.save_dashboard(filepath=filename)
        
        logger.info(f"[SUCCESS] Dashboard saved to: {filename}")
        
    except PermissionError as e:
        logger.error(f"[FAILED] Permission denied when saving dashboard: {e}")
        logger.error("Check file permissions and ensure the file is not open in another program")
        sys.exit(1)
    except OSError as e:
        logger.error(f"[FAILED] File system error when saving dashboard: {e}")
        logger.error("Check that the directory exists and disk space is available")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Unexpected error saving dashboard: {e}")
        sys.exit(1)
    
    # System completion
    logger.info("\n" + "=" * 70)
    logger.info("Crypto Screener System completed successfully!")
    logger.info("=" * 70)
    logger.info(f"Output file: {filename}")
    logger.info(f"Total assets processed: {len(ranked_df)}")
    logger.info(f"Tier A assets: {(ranked_df['tier'] == 'A').sum()}")
    logger.info(f"Tier B assets: {(ranked_df['tier'] == 'B').sum()}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
