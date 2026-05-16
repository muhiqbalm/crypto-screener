"""
Multi-Factor Scorer Module

Combines multiple trading signals into a multi-factor score with
risk adjustment and position sizing.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .ic_weights import ICWeightCalculator

logger = logging.getLogger(__name__)


class MultiFactorScorer:
    """
    Combines multiple trading signals into a multi-factor score.
    
    This class takes normalized signals and IC weights to calculate a composite
    score for each asset. The multi-factor score is a weighted combination of
    individual signals, where weights represent the historical predictive power
    (Information Coefficient) of each signal.
    
    Features:
    - 5-factor weighted scoring (momentum, reversal, funding, sentiment, OI)
    - Risk-adjusted scoring using ATR-based volatility penalty
    - Inverse volatility position sizing
    - 3-tier classification (A/B/C by percentile)
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
        Calculate multi-factor score as weighted combination of all 5 normalized signals.
        
        Formula: score = w1*reversal + w2*momentum + w3*funding + w4*sentiment + w5*oi_momentum
        
        For the current implementation:
        score = 0.10*reversal + 0.30*momentum + 0.25*funding + 0.15*sentiment + 0.20*oi_momentum
        
        The signals must be normalized (z-scores) before being passed to this method
        to ensure they are on comparable scales. The IC weights determine the relative
        importance of each signal in the final score.
        
        Args:
            df: DataFrame with normalized signal columns:
                - 'reversal_signal': Normalized 1-day reversal signal
                - 'momentum_signal': Normalized 30-day momentum signal
                - 'funding_rate_signal': Normalized funding rate contrarian signal
                - 'sentiment_signal': Normalized L/S ratio contrarian signal
                - 'oi_momentum_signal': Normalized OI-price matrix signal
                
        Returns:
            pd.Series: Multi-factor score for each asset (higher = better)
            
        Raises:
            KeyError: If required signal columns are missing from DataFrame
        """
        # All 5 signal columns required
        required_columns = [
            'reversal_signal', 'momentum_signal',
            'funding_rate_signal', 'sentiment_signal', 'oi_momentum_signal'
        ]
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
        w_funding = self.ic_calculator.get_weight('funding_rate')
        w_sentiment = self.ic_calculator.get_weight('sentiment_ls')
        w_oi = self.ic_calculator.get_weight('oi_momentum')
        
        # Calculate weighted combination of all 5 signals
        multi_factor_score = (
            w_reversal * df['reversal_signal'] +
            w_momentum * df['momentum_signal'] +
            w_funding * df['funding_rate_signal'] +
            w_sentiment * df['sentiment_signal'] +
            w_oi * df['oi_momentum_signal']
        )
        
        logger.info(f"Calculated multi-factor scores for {len(multi_factor_score)} assets")
        logger.debug(f"Score range: [{multi_factor_score.min():.4f}, {multi_factor_score.max():.4f}]")
        
        return multi_factor_score
    
    def calculate_risk_adjusted_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate risk-adjusted score by penalizing volatile assets.
        
        Formula: risk_adjusted_score = multi_factor_score / max(atr_percent, 1.0)
        
        This ensures that volatile assets need a proportionally higher raw score
        to rank well. The max(atr_percent, 1.0) floor prevents:
        - Division by zero
        - Unreasonable boosting of very low-ATR assets
        
        If atr_percent is NaN for an asset, the multi_factor_score is used as-is
        (no adjustment applied).
        
        Args:
            df: DataFrame with 'multi_factor_score' and 'atr_percent' columns.
            
        Returns:
            pd.DataFrame: Input DataFrame with new 'risk_adjusted_score' column added.
        """
        if 'multi_factor_score' not in df.columns:
            logger.error("'multi_factor_score' column required for risk adjustment")
            df['risk_adjusted_score'] = np.nan
            return df
        
        if 'atr_percent' not in df.columns:
            logger.warning("'atr_percent' not found, using multi_factor_score as risk_adjusted_score")
            df['risk_adjusted_score'] = df['multi_factor_score']
            return df
        
        # Start with multi_factor_score as default (for NaN atr_percent cases)
        risk_adjusted = df['multi_factor_score'].copy()
        
        # Only adjust where atr_percent is available
        valid_atr = df['atr_percent'].notna()
        if valid_atr.any():
            atr_floor = df.loc[valid_atr, 'atr_percent'].clip(lower=1.0)
            risk_adjusted.loc[valid_atr] = df.loc[valid_atr, 'multi_factor_score'] / atr_floor
        
        df['risk_adjusted_score'] = risk_adjusted
        
        logger.info(f"Calculated risk-adjusted scores for {len(df)} assets")
        logger.debug(
            f"Risk-adjusted score range: [{risk_adjusted.min():.4f}, {risk_adjusted.max():.4f}]"
        )
        
        return df
    
    def calculate_position_sizing(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate suggested position sizes using inverse volatility weighting.
        
        Formula:
        - raw_weight = 1.0 / max(atr_percent, 1.0) for each asset
        - suggested_position_pct = (raw_weight / sum_of_all_raw_weights) * 100
        
        This allocates more capital to lower-volatility assets and less to
        higher-volatility assets, producing a risk-parity-like allocation.
        
        If atr_percent is NaN for an asset, it receives equal weight (1/N * 100).
        
        Args:
            df: DataFrame with 'atr_percent' column.
            
        Returns:
            pd.DataFrame: Input DataFrame with new 'suggested_position_pct' column added.
        """
        n = len(df)
        
        if n == 0:
            df['suggested_position_pct'] = pd.Series(dtype=float)
            return df
        
        equal_weight = 100.0 / n
        
        if 'atr_percent' not in df.columns:
            logger.warning("'atr_percent' not found, using equal weights for position sizing")
            df['suggested_position_pct'] = equal_weight
            return df
        
        # Calculate raw inverse-volatility weights
        raw_weights = pd.Series(0.0, index=df.index)
        valid_atr = df['atr_percent'].notna()
        
        if valid_atr.any():
            atr_floor = df.loc[valid_atr, 'atr_percent'].clip(lower=1.0)
            raw_weights.loc[valid_atr] = 1.0 / atr_floor
        
        # Assets with NaN atr get equal weight placeholder
        nan_atr = ~valid_atr
        if nan_atr.any():
            # Assign mean of valid weights so they get "average" allocation
            if valid_atr.any():
                mean_weight = raw_weights.loc[valid_atr].mean()
                raw_weights.loc[nan_atr] = mean_weight
            else:
                # All NaN — use equal weights
                raw_weights[:] = 1.0
        
        # Normalize to percentages summing to 100%
        total_weight = raw_weights.sum()
        if total_weight > 0:
            df['suggested_position_pct'] = (raw_weights / total_weight) * 100.0
        else:
            df['suggested_position_pct'] = equal_weight
        
        logger.info(f"Calculated position sizing for {n} assets")
        logger.debug(
            f"Position size range: [{df['suggested_position_pct'].min():.2f}%, "
            f"{df['suggested_position_pct'].max():.2f}%]"
        )
        
        return df
    
    def calculate_confidence_rate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate trading signal confidence rate using a Hybrid method.
        
        Combines Magnitude Probability (derived from z-score CDF) and
        Confluence Probability (agreement across 5 factors).
        
        Args:
            df: DataFrame containing 'risk_adjusted_score' and individual signal columns.
            
        Returns:
            pd.DataFrame: Input DataFrame with new 'confidence_pct' and 'confidence_tier' columns.
        """
        if 'risk_adjusted_score' not in df.columns:
            logger.warning("'risk_adjusted_score' not found, cannot calculate confidence rate")
            df['confidence_pct'] = np.nan
            df['confidence_tier'] = None
            return df
            
        n = len(df)
        if n == 0:
            df['confidence_pct'] = pd.Series(dtype=float)
            df['confidence_tier'] = pd.Series(dtype=str)
            return df
            
        # 1. Magnitude Probability
        # Using math.erf to approximate normal CDF based on the absolute z-score
        def calc_magnitude_prob(score):
            if pd.isna(score):
                return np.nan
            return (1.0 + math.erf(abs(score) / math.sqrt(2.0))) / 2.0
            
        magnitude_prob = df['risk_adjusted_score'].apply(calc_magnitude_prob)
        
        # 2. Confluence Probability
        signal_factors = [
            'reversal_signal', 'momentum_signal', 
            'funding_rate_signal', 'sentiment_signal', 'oi_momentum_signal'
        ]
        
        # Determine target direction (+1 for LONG, -1 for SHORT)
        direction_sign = np.sign(df['risk_adjusted_score'].fillna(0))
        # Handle exactly 0 to avoid matching 0 signs incorrectly, default to +1
        direction_sign = direction_sign.replace(0, 1)
        
        confluence_count = pd.Series(0, index=df.index)
        valid_factors_count = 0
        
        for factor in signal_factors:
            if factor in df.columns:
                valid_factors_count += 1
                factor_sign = np.sign(df[factor].fillna(0))
                # Add 1 where signs match
                confluence_count += (factor_sign == direction_sign).astype(int)
                
        if valid_factors_count > 0:
            confluence_prob = confluence_count / valid_factors_count
        else:
            confluence_prob = pd.Series(0.5, index=df.index) # Default neutral if no factors found
            
        # 3. Hybrid Probability
        # 60% weight to magnitude, 40% weight to confluence
        hybrid_prob = (0.6 * magnitude_prob) + (0.4 * confluence_prob)
        df['confidence_pct'] = hybrid_prob * 100.0
        
        # 4. Confidence Tier
        def assign_confidence_tier(pct):
            if pd.isna(pct):
                return None
            if pct >= 80.0:
                return 'High'
            elif pct >= 60.0:
                return 'Medium'
            else:
                return 'Low'
                
        df['confidence_tier'] = df['confidence_pct'].apply(assign_confidence_tier)
        
        logger.info(f"Calculated confidence rates for {n} assets")
        return df

    def classify_tiers(self, scores: pd.Series) -> pd.Series:
        """
        Classify assets into 3 tiers based on percentile ranking of scores.
        
        Tier Classification:
        - Tier A: Top 33% of assets by score (strong buy candidates)
        - Tier B: Middle 34% of assets (moderate/hold)
        - Tier C: Bottom 33% of assets (avoid/short candidates)
        
        Uses percentile thresholds (33rd and 67th) for classification.
        
        Args:
            scores: Series of multi-factor scores for assets
            
        Returns:
            pd.Series: Tier classification ('A', 'B', or 'C') for each asset
        """
        # Handle empty series
        if len(scores) == 0:
            logger.warning("Empty series provided to classify_tiers")
            return pd.Series(dtype=str)
        
        # Handle single asset case
        if len(scores) == 1:
            logger.info("Single asset provided, classifying as Tier A")
            return pd.Series(['A'], index=scores.index)
        
        # Handle two assets: top is A, bottom is C
        if len(scores) == 2:
            logger.info("Two assets provided, classifying as Tier A and Tier C")
            tiers = scores.copy().astype(str)
            sorted_idx = scores.sort_values(ascending=False).index
            tiers.loc[sorted_idx[0]] = 'A'
            tiers.loc[sorted_idx[1]] = 'C'
            return tiers
        
        # Calculate percentile thresholds for 3-tier classification
        p33 = scores.quantile(1.0 / 3.0)
        p67 = scores.quantile(2.0 / 3.0)
        
        def assign_tier(score):
            if score >= p67:
                return 'A'
            elif score >= p33:
                return 'B'
            else:
                return 'C'
        
        tiers = scores.apply(assign_tier)
        
        # Log tier distribution
        tier_counts = tiers.value_counts()
        logger.info(f"Tier classification complete: {tier_counts.to_dict()}")
        logger.debug(f"Tier thresholds: p33={p33:.4f}, p67={p67:.4f}")
        
        return tiers
