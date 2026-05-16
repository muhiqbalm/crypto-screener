"""
Unit tests for RankingEngine class.

Tests cover:
- Basic ranking functionality
- Stable sort preservation for equal scores
- Edge cases (empty DataFrame, single asset)
- Error handling for missing columns
"""

import pytest
import pandas as pd
import numpy as np
from src.ranking.engine import RankingEngine


class TestRankingEngine:
    """Test suite for RankingEngine class."""
    
    def test_rank_assets_basic(self):
        """Test basic ranking with distinct scores."""
        # Create test DataFrame with distinct scores
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL', 'AAVE', 'ZEC'],
            'multi_factor_score': [1.5, 0.8, -0.3, 2.1, 0.0]
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify sorting: scores should be in descending order
        scores = df_ranked['multi_factor_score'].tolist()
        assert scores == sorted(scores, reverse=True), "Scores should be in descending order"
        
        # Verify rank column exists and has correct values
        assert 'rank' in df_ranked.columns, "Rank column should exist"
        assert df_ranked['rank'].tolist() == [1, 2, 3, 4, 5], "Ranks should be 1, 2, 3, 4, 5"
        
        # Verify highest score gets rank 1
        assert df_ranked.iloc[0]['symbol'] == 'AAVE', "AAVE should be rank 1 (highest score)"
        assert df_ranked.iloc[0]['rank'] == 1, "First row should have rank 1"
        assert df_ranked.iloc[0]['multi_factor_score'] == 2.1, "Rank 1 should have score 2.1"
        
        # Verify lowest score gets last rank
        assert df_ranked.iloc[-1]['symbol'] == 'SOL', "SOL should be last rank (lowest score)"
        assert df_ranked.iloc[-1]['rank'] == 5, "Last row should have rank 5"
        assert df_ranked.iloc[-1]['multi_factor_score'] == -0.3, "Last rank should have score -0.3"
    
    def test_rank_assets_stable_sort(self):
        """Test stable sort preservation for equal scores."""
        # Create test DataFrame with duplicate scores
        # Assets with score 1.0: BTC, ETH, SOL (in this order)
        # Assets with score 0.5: AAVE, ZEC (in this order)
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL', 'AAVE', 'ZEC'],
            'multi_factor_score': [1.0, 1.0, 1.0, 0.5, 0.5]
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify stable sort: assets with equal scores maintain original order
        # BTC, ETH, SOL should appear in this order (all have score 1.0)
        top_three = df_ranked.head(3)['symbol'].tolist()
        assert top_three == ['BTC', 'ETH', 'SOL'], "Assets with equal scores should maintain original order"
        
        # AAVE, ZEC should appear in this order (all have score 0.5)
        bottom_two = df_ranked.tail(2)['symbol'].tolist()
        assert bottom_two == ['AAVE', 'ZEC'], "Assets with equal scores should maintain original order"
        
        # Verify ranks are sequential
        assert df_ranked['rank'].tolist() == [1, 2, 3, 4, 5], "Ranks should be sequential"
    
    def test_rank_assets_all_equal_scores(self):
        """Test ranking when all assets have identical scores."""
        # Create test DataFrame with all equal scores
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL', 'AAVE', 'ZEC'],
            'multi_factor_score': [0.5, 0.5, 0.5, 0.5, 0.5]
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify stable sort: original order is preserved
        symbols = df_ranked['symbol'].tolist()
        assert symbols == ['BTC', 'ETH', 'SOL', 'AAVE', 'ZEC'], "Original order should be preserved"
        
        # Verify ranks are sequential
        assert df_ranked['rank'].tolist() == [1, 2, 3, 4, 5], "Ranks should be sequential"
    
    def test_rank_assets_single_asset(self):
        """Test ranking with single asset."""
        # Create test DataFrame with single asset
        df = pd.DataFrame({
            'symbol': ['BTC'],
            'multi_factor_score': [1.5]
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify single asset gets rank 1
        assert len(df_ranked) == 1, "Should have one row"
        assert df_ranked.iloc[0]['rank'] == 1, "Single asset should have rank 1"
        assert df_ranked.iloc[0]['symbol'] == 'BTC', "Symbol should be preserved"
    
    def test_rank_assets_empty_dataframe(self):
        """Test ranking with empty DataFrame."""
        # Create empty DataFrame with correct columns
        df = pd.DataFrame({
            'symbol': [],
            'multi_factor_score': []
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify empty DataFrame is returned with rank column
        assert len(df_ranked) == 0, "Should return empty DataFrame"
        assert 'rank' in df_ranked.columns, "Rank column should exist"
    
    def test_rank_assets_missing_score_column(self):
        """Test error handling when multi_factor_score column is missing."""
        # Create DataFrame without multi_factor_score column
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL']
        })
        
        # Create RankingEngine and attempt to rank assets
        engine = RankingEngine()
        
        # Verify KeyError is raised
        with pytest.raises(KeyError) as exc_info:
            engine.rank_assets(df)
        
        assert "multi_factor_score" in str(exc_info.value), "Error message should mention missing column"
    
    def test_rank_assets_preserves_all_columns(self):
        """Test that all original columns are preserved in output."""
        # Create test DataFrame with multiple columns
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL'],
            'price': [50000, 3000, 100],
            'change_24h': [2.5, -1.3, 5.0],
            'multi_factor_score': [1.5, 0.8, -0.3],
            'tier': ['A', 'A', 'B']
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify all original columns are preserved
        expected_columns = ['symbol', 'price', 'change_24h', 'multi_factor_score', 'tier', 'rank']
        assert list(df_ranked.columns) == expected_columns, "All columns should be preserved"
        
        # Verify data integrity for non-score columns
        assert df_ranked[df_ranked['symbol'] == 'BTC']['price'].iloc[0] == 50000
        assert df_ranked[df_ranked['symbol'] == 'ETH']['change_24h'].iloc[0] == -1.3
        assert df_ranked[df_ranked['symbol'] == 'SOL']['tier'].iloc[0] == 'B'
    
    def test_rank_assets_with_nan_scores(self):
        """Test ranking behavior with NaN scores."""
        # Create test DataFrame with NaN score
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL', 'AAVE'],
            'multi_factor_score': [1.5, np.nan, 0.8, -0.3]
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify DataFrame is sorted (NaN handling depends on pandas sort behavior)
        # pandas.sort_values places NaN at the end by default
        assert len(df_ranked) == 4, "Should have 4 rows"
        assert 'rank' in df_ranked.columns, "Rank column should exist"
        
        # Verify non-NaN values are sorted correctly
        non_nan_scores = df_ranked[df_ranked['multi_factor_score'].notna()]['multi_factor_score'].tolist()
        assert non_nan_scores == sorted(non_nan_scores, reverse=True), "Non-NaN scores should be sorted"
    
    def test_rank_assets_negative_scores(self):
        """Test ranking with negative scores."""
        # Create test DataFrame with negative scores
        df = pd.DataFrame({
            'symbol': ['BTC', 'ETH', 'SOL', 'AAVE', 'ZEC'],
            'multi_factor_score': [-0.5, -1.2, -0.1, -2.0, -0.8]
        })
        
        # Create RankingEngine and rank assets
        engine = RankingEngine()
        df_ranked = engine.rank_assets(df)
        
        # Verify sorting: highest (least negative) score should be rank 1
        assert df_ranked.iloc[0]['symbol'] == 'SOL', "SOL should be rank 1 (score -0.1)"
        assert df_ranked.iloc[0]['rank'] == 1
        
        # Verify lowest (most negative) score should be last rank
        assert df_ranked.iloc[-1]['symbol'] == 'AAVE', "AAVE should be last rank (score -2.0)"
        assert df_ranked.iloc[-1]['rank'] == 5
        
        # Verify descending order
        scores = df_ranked['multi_factor_score'].tolist()
        assert scores == sorted(scores, reverse=True), "Scores should be in descending order"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
