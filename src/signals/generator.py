"""
Signal Generator Module

Generates trading signals from market data.
"""

import logging
import random
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
