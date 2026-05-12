"""
Signal Generator Module

Generates trading signals from market data.
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


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
            return momentum_signal
        
        # Fallback to 24h change if momentum_30d not available
        if 'change_24h' not in df.columns:
            error_msg = "DataFrame must contain 'momentum_30d' or 'change_24h' column"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        logger.warning("30-day momentum not available, using 24h change as fallback")
        momentum_signal = df['change_24h'].copy()
        
        logger.debug(f"Calculated momentum signal for {len(momentum_signal)} assets")
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
