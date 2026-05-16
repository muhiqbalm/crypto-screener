"""
Unit tests for MultiFactorScorer class.

Tests the multi-factor score calculation and tier classification functionality.
"""

import pytest
import pandas as pd
import numpy as np
from src.signals.scorer import MultiFactorScorer
from src.signals.ic_weights import ICWeightCalculator


class TestMultiFactorScorer:
    """Test suite for MultiFactorScorer class."""
    
    @pytest.fixture
    def ic_calculator(self):
        """Fixture providing ICWeightCalculator instance."""
        return ICWeightCalculator()
    
    @pytest.fixture
    def scorer(self, ic_calculator):
        """Fixture providing MultiFactorScorer instance."""
        return MultiFactorScorer(ic_calculator)
    
    def test_initialization(self, ic_calculator):
        """Test MultiFactorScorer initialization."""
        scorer = MultiFactorScorer(ic_calculator)
        assert scorer.ic_calculator is ic_calculator
    
    def test_calculate_score_basic(self, scorer):
        """Test basic multi-factor score calculation."""
        # Create test DataFrame with normalized signals
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL'],
            'reversal_signal': [1.0, 0.0, -1.0],
            'momentum_signal': [0.5, 0.0, -0.5]
        })
        
        # Calculate scores
        scores = scorer.calculate_score(df)
        
        # Verify scores are calculated correctly
        # score = 0.3 * reversal + 0.7 * momentum
        expected_scores = [
            0.3 * 1.0 + 0.7 * 0.5,   # BTC: 0.3 + 0.35 = 0.65
            0.3 * 0.0 + 0.7 * 0.0,   # ETH: 0.0
            0.3 * (-1.0) + 0.7 * (-0.5)  # SOL: -0.3 + -0.35 = -0.65
        ]
        
        assert len(scores) == 3
        np.testing.assert_array_almost_equal(scores.values, expected_scores, decimal=10)
    
    def test_calculate_score_weights(self, scorer):
        """Test that IC weights are correctly applied in score calculation."""
        # Create DataFrame with signals
        df = pd.DataFrame({
            'reversal_signal': [1.0],
            'momentum_signal': [1.0]
        })
        
        # Calculate score
        score = scorer.calculate_score(df).iloc[0]
        
        # With weights 0.3 and 0.7, score should be 1.0
        expected_score = 0.3 * 1.0 + 0.7 * 1.0
        assert abs(score - expected_score) < 1e-10
    
    def test_calculate_score_missing_columns(self, scorer):
        """Test that calculate_score raises KeyError for missing columns."""
        # DataFrame missing momentum_signal
        df = pd.DataFrame({
            'reversal_signal': [1.0, 0.0]
        })
        
        with pytest.raises(KeyError) as exc_info:
            scorer.calculate_score(df)
        
        assert 'momentum_signal' in str(exc_info.value)
    
    def test_calculate_score_empty_dataframe(self, scorer):
        """Test calculate_score with empty DataFrame."""
        df = pd.DataFrame({
            'reversal_signal': [],
            'momentum_signal': []
        })
        
        scores = scorer.calculate_score(df)
        
        assert len(scores) == 0
        assert scores.dtype == float
    
    def test_calculate_score_with_nan(self, scorer):
        """Test calculate_score handles NaN values correctly."""
        df = pd.DataFrame({
            'reversal_signal': [1.0, np.nan, -1.0],
            'momentum_signal': [0.5, 0.0, np.nan]
        })
        
        scores = scorer.calculate_score(df)
        
        # First score should be valid
        assert not pd.isna(scores.iloc[0])
        assert abs(scores.iloc[0] - (0.3 * 1.0 + 0.7 * 0.5)) < 1e-10
        
        # Second and third scores should be NaN due to NaN inputs
        assert pd.isna(scores.iloc[1])
        assert pd.isna(scores.iloc[2])
    
    def test_classify_tiers_basic(self, scorer):
        """Test basic tier classification."""
        # Create scores with clear top 50% and bottom 50%
        scores = pd.Series([10.0, 8.0, 6.0, 4.0, 2.0, 0.0])
        
        tiers = scorer.classify_tiers(scores)
        
        # Median is 5.0, so scores >= 5.0 should be Tier A
        assert len(tiers) == 6
        assert tiers.iloc[0] == 'A'  # 10.0 >= 5.0
        assert tiers.iloc[1] == 'A'  # 8.0 >= 5.0
        assert tiers.iloc[2] == 'A'  # 6.0 >= 5.0
        assert tiers.iloc[3] == 'B'  # 4.0 < 5.0
        assert tiers.iloc[4] == 'B'  # 2.0 < 5.0
        assert tiers.iloc[5] == 'B'  # 0.0 < 5.0
    
    def test_classify_tiers_even_split(self, scorer):
        """Test tier classification produces roughly 50/50 split."""
        scores = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0, 0.0])
        
        tiers = scorer.classify_tiers(scores)
        
        # Count tiers
        tier_counts = tiers.value_counts()
        
        # Should have both tiers
        assert 'A' in tier_counts
        assert 'B' in tier_counts
        
        # Should be roughly 50/50 (3 and 3 for 6 assets)
        assert tier_counts['A'] == 3
        assert tier_counts['B'] == 3
    
    def test_classify_tiers_single_asset(self, scorer):
        """Test tier classification with single asset."""
        scores = pd.Series([5.0])
        
        tiers = scorer.classify_tiers(scores)
        
        assert len(tiers) == 1
        assert tiers.iloc[0] == 'A'  # Single asset should be Tier A
    
    def test_classify_tiers_empty(self, scorer):
        """Test tier classification with empty series."""
        scores = pd.Series([], dtype=float)
        
        tiers = scorer.classify_tiers(scores)
        
        assert len(tiers) == 0
        # Check that it's a string-like dtype (could be 'object' or 'str' depending on pandas version)
        assert tiers.dtype in [object, 'object', 'str', pd.StringDtype()]
    
    def test_classify_tiers_all_equal(self, scorer):
        """Test tier classification when all scores are equal."""
        scores = pd.Series([5.0, 5.0, 5.0, 5.0])
        
        tiers = scorer.classify_tiers(scores)
        
        # All scores equal median, so all should be Tier A (>= median)
        assert len(tiers) == 4
        assert all(tiers == 'A')
    
    def test_classify_tiers_with_ties_at_median(self, scorer):
        """Test tier classification with ties at the median."""
        scores = pd.Series([10.0, 5.0, 5.0, 5.0, 0.0])
        
        tiers = scorer.classify_tiers(scores)
        
        # Median is 5.0
        # Scores >= 5.0 should be Tier A
        assert tiers.iloc[0] == 'A'  # 10.0
        assert tiers.iloc[1] == 'A'  # 5.0
        assert tiers.iloc[2] == 'A'  # 5.0
        assert tiers.iloc[3] == 'A'  # 5.0
        assert tiers.iloc[4] == 'B'  # 0.0
    
    def test_classify_tiers_negative_scores(self, scorer):
        """Test tier classification with negative scores."""
        scores = pd.Series([2.0, 1.0, 0.0, -1.0, -2.0, -3.0])
        
        tiers = scorer.classify_tiers(scores)
        
        # Median is -0.5
        assert tiers.iloc[0] == 'A'  # 2.0 >= -0.5
        assert tiers.iloc[1] == 'A'  # 1.0 >= -0.5
        assert tiers.iloc[2] == 'A'  # 0.0 >= -0.5
        assert tiers.iloc[3] == 'B'  # -1.0 < -0.5
        assert tiers.iloc[4] == 'B'  # -2.0 < -0.5
        assert tiers.iloc[5] == 'B'  # -3.0 < -0.5
    
    def test_end_to_end_scoring_and_classification(self, scorer):
        """Test complete workflow: calculate scores and classify tiers."""
        # Create test DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC'],
            'reversal_signal': [1.5, 0.5, 0.0, -0.5, -1.5],
            'momentum_signal': [1.0, 0.5, 0.0, -0.5, -1.0]
        })
        
        # Calculate scores
        scores = scorer.calculate_score(df)
        
        # Classify tiers
        tiers = scorer.classify_tiers(scores)
        
        # Verify results
        assert len(scores) == 5
        assert len(tiers) == 5
        
        # Higher scores should get Tier A
        # BTC has highest signals, should be Tier A
        assert tiers.iloc[0] == 'A'
        
        # MATIC has lowest signals, should be Tier B
        assert tiers.iloc[4] == 'B'
        
        # Verify tier distribution
        tier_counts = tiers.value_counts()
        assert tier_counts['A'] + tier_counts['B'] == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
