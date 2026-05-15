"""
Signal Generator Module

Generates trading signals from market data including:
- 1-day reversal signal (mean reversion)
- 30-day momentum signal with trend exhaustion penalty
- Funding rate contrarian signal
- Long/short ratio sentiment signal
- OI-price momentum matrix signal
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Generates trading signals from market data.
    
    This class implements quantitative trading signals including:
    - 1-day reversal signal: Identifies potential price reversals based on recent moves
    - 30-day momentum signal: Identifies trending price movements with exhaustion penalty
    - Funding rate signal: Contrarian signal from perpetual swap funding rates
    - Sentiment signal: Contrarian signal from long/short ratio
    - OI momentum signal: Quantitative signal from OI delta + price action matrix
    
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
        
        Uses pre-calculated 30-day momentum from market data if available,
        otherwise falls back to 24h change as a proxy.
        
        Momentum signal interpretation:
        - Positive momentum: Asset has been trending upward
        - Negative momentum: Asset has been trending downward
        - Higher absolute values indicate stronger trends
        
        Args:
            df: DataFrame with 'momentum_30d' column (preferred) or 'change_24h' column (fallback)
            
        Returns:
            pd.Series: Momentum signal values (higher = stronger upward momentum)
            
        Raises:
            KeyError: If neither 'momentum_30d' nor 'change_24h' column is present
        """
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_momentum_signal")
            return pd.Series(dtype=float)
        
        # Prefer real 30-day momentum if available
        if 'momentum_30d' in df.columns and df['momentum_30d'].notna().any():
            momentum_signal = df['momentum_30d'].copy()
            logger.info("Using real 30-day momentum data for momentum signal")
        elif 'change_24h' in df.columns:
            # Fallback to 24h change if momentum_30d not available
            logger.warning("30-day momentum not available, using 24h change as fallback")
            momentum_signal = df['change_24h'].copy()
        else:
            error_msg = "DataFrame must contain 'momentum_30d' or 'change_24h' column"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Apply trend exhaustion penalty using distance_to_ma50
        if 'distance_to_ma50' in df.columns:
            distance = df['distance_to_ma50']
            
            # Penalty for buying the top: momentum > 0 and price far above MA50
            overbought_mask = (momentum_signal > 0) & (distance > 30) & distance.notna()
            momentum_signal.loc[overbought_mask] *= 0.6  # Reduce by 40%
            
            # Penalty for panic selling at the bottom: momentum < 0 and price far below MA50
            oversold_mask = (momentum_signal < 0) & (distance < -30) & distance.notna()
            momentum_signal.loc[oversold_mask] *= 0.6  # Reduce magnitude by 40%
            
            penalized_count = overbought_mask.sum() + oversold_mask.sum()
            if penalized_count > 0:
                logger.info(f"Applied trend exhaustion penalty to {penalized_count} assets")
        
        logger.debug(f"Calculated momentum signal for {len(momentum_signal)} assets")
        return momentum_signal
    
    def calculate_funding_rate_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate contrarian signal from perpetual swap funding rates.
        
        Logic: signal = -1 * funding_rate
        - High positive funding rate → market is overleveraged long → bearish signal
        - Negative funding rate → market is overleveraged short → bullish signal
        
        Args:
            df: DataFrame with 'funding_rate' column.
            
        Returns:
            pd.Series: Funding rate signal values. 0.0 for NaN rows.
        """
        if 'funding_rate' not in df.columns:
            logger.warning("'funding_rate' column not found, returning zeros")
            return pd.Series(0.0, index=df.index)
        
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_funding_rate_signal")
            return pd.Series(dtype=float)
        
        signal = -1 * df['funding_rate']
        signal = signal.fillna(0.0)
        
        logger.debug(f"Calculated funding rate signal for {len(signal)} assets")
        return signal
    
    def calculate_sentiment_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate contrarian signal from long/short ratio.
        
        Logic: signal = -1 * (long_short_ratio - 1.0)
        - Ratio > 1 means crowd is net long → contrarian bearish signal
        - Ratio < 1 means crowd is net short → contrarian bullish signal
        - Ratio = 1 means balanced → neutral signal (0.0)
        
        Args:
            df: DataFrame with 'long_short_ratio' column.
            
        Returns:
            pd.Series: Sentiment signal values. 0.0 for NaN rows.
        """
        if 'long_short_ratio' not in df.columns:
            logger.warning("'long_short_ratio' column not found, returning zeros")
            return pd.Series(0.0, index=df.index)
        
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_sentiment_signal")
            return pd.Series(dtype=float)
        
        signal = -1 * (df['long_short_ratio'] - 1.0)
        signal = signal.fillna(0.0)
        
        logger.debug(f"Calculated sentiment signal for {len(signal)} assets")
        return signal
    
    def calculate_oi_momentum_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate quantitative signal from OI delta + price action matrix.
        
        Maps the OI-price matrix to directional scores:
        - OI↑ (> 1%) + Price↑ (> 0) = +1.0  (new longs entering, bullish)
        - OI↑ (> 1%) + Price↓ (≤ 0) = -1.0  (new shorts entering, bearish)
        - OI↓ (< -1%) + Price↑ (> 0) = +0.5  (short squeeze, moderately bullish)
        - OI↓ (< -1%) + Price↓ (≤ 0) = -0.5  (long liquidation, moderately bearish)
        - Otherwise = 0.0  (neutral / insufficient OI change)
        
        Args:
            df: DataFrame with 'oi_delta_percent' and 'change_24h' columns.
            
        Returns:
            pd.Series: OI momentum signal values. 0.0 for NaN rows.
        """
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to calculate_oi_momentum_signal")
            return pd.Series(dtype=float)
        
        has_oi = 'oi_delta_percent' in df.columns
        has_price = 'change_24h' in df.columns
        
        if not has_oi or not has_price:
            logger.warning("Missing 'oi_delta_percent' or 'change_24h' columns, returning zeros")
            return pd.Series(0.0, index=df.index)
        
        oi_delta = df['oi_delta_percent']
        price_change = df['change_24h']
        
        # Initialize with zeros
        signal = pd.Series(0.0, index=df.index)
        
        # Mask for valid (non-NaN) data in both columns
        valid = oi_delta.notna() & price_change.notna()
        
        # OI increasing (> 1%)
        oi_up = valid & (oi_delta > 1.0)
        # OI decreasing (< -1%)
        oi_down = valid & (oi_delta < -1.0)
        # Price up (> 0)
        price_up = price_change > 0
        
        # New longs: OI↑ + Price↑ = +1.0 (bullish)
        signal.loc[oi_up & price_up] = 1.0
        # New shorts: OI↑ + Price↓ = -1.0 (bearish)
        signal.loc[oi_up & ~price_up] = -1.0
        # Short squeeze: OI↓ + Price↑ = +0.5 (moderately bullish)
        signal.loc[oi_down & price_up] = 0.5
        # Long liquidation: OI↓ + Price↓ = -0.5 (moderately bearish)
        signal.loc[oi_down & ~price_up] = -0.5
        
        logger.debug(f"Calculated OI momentum signal for {len(signal)} assets")
        return signal
    
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
