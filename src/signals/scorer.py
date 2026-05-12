"""
Multi-Factor Scorer Module

Combines multiple trading signals into a multi-factor score.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


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
