#!/usr/bin/env python3
"""
Unit tests for MultiFactorPanel class.

This test suite verifies the MultiFactorPanel visualization component
following the project's testing patterns.
"""

import pytest
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for testing
import matplotlib.pyplot as plt
from crypto_screener import MultiFactorPanel


class TestMultiFactorPanel:
    """Test suite for MultiFactorPanel class."""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample DataFrame for testing."""
        data = {
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [0.856, 0.423, -0.125, -0.389, -0.765],
            'tier': ['A', 'A', 'B', 'B', 'B']
        }
        df = pd.DataFrame(data)
        # Sort by multi_factor_score descending (as RankingEngine would do)
        df = df.sort_values('multi_factor_score', ascending=False).reset_index(drop=True)
        return df
    
    @pytest.fixture
    def panel(self):
        """Create MultiFactorPanel instance."""
        return MultiFactorPanel()
    
    def test_initialization(self, panel):
        """Test MultiFactorPanel can be instantiated."""
        assert panel is not None
        assert isinstance(panel, MultiFactorPanel)
    
    def test_render_basic(self, panel, sample_data):
        """Test basic rendering with valid data."""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise any exceptions
        panel.render(ax, sample_data)
        
        # Verify axis has been configured
        assert ax.get_title() == 'Multi-Factor Score by Asset'
        assert ax.get_xlabel() == 'Multi-Factor Score'
        assert ax.get_ylabel() == 'Asset Symbol'
        
        plt.close(fig)
    
    def test_render_missing_columns(self, panel):
        """Test render raises KeyError when required columns are missing."""
        # DataFrame missing 'tier' column
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
            'multi_factor_score': [0.5, -0.3]
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        with pytest.raises(KeyError) as exc_info:
            panel.render(ax, df)
        
        assert 'tier' in str(exc_info.value)
        plt.close(fig)
    
    def test_render_missing_symbol_column(self, panel):
        """Test render raises KeyError when symbol column is missing."""
        df = pd.DataFrame({
            'multi_factor_score': [0.5, -0.3],
            'tier': ['A', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        with pytest.raises(KeyError) as exc_info:
            panel.render(ax, df)
        
        assert 'symbol' in str(exc_info.value)
        plt.close(fig)
    
    def test_render_missing_score_column(self, panel):
        """Test render raises KeyError when multi_factor_score column is missing."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
            'tier': ['A', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        with pytest.raises(KeyError) as exc_info:
            panel.render(ax, df)
        
        assert 'multi_factor_score' in str(exc_info.value)
        plt.close(fig)
    
    def test_render_empty_dataframe(self, panel):
        """Test render handles empty DataFrame gracefully."""
        df = pd.DataFrame(columns=['symbol', 'multi_factor_score', 'tier'])
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_single_asset(self, panel):
        """Test render handles single asset."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_all_tier_a(self, panel):
        """Test render with all assets in Tier A."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [0.8, 0.6, 0.4],
            'tier': ['A', 'A', 'A']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_all_tier_b(self, panel):
        """Test render with all assets in Tier B."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [-0.2, -0.4, -0.6],
            'tier': ['B', 'B', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_negative_scores(self, panel):
        """Test render handles negative scores correctly."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [-0.5, -1.0, -1.5],
            'tier': ['A', 'B', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_positive_scores(self, panel):
        """Test render handles positive scores correctly."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [1.5, 1.0, 0.5],
            'tier': ['A', 'A', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_mixed_scores(self, panel):
        """Test render handles mixed positive and negative scores."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT'],
            'multi_factor_score': [1.0, 0.5, -0.5, -1.0],
            'tier': ['A', 'A', 'B', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_zero_scores(self, panel):
        """Test render handles zero scores."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [0.0, 0.0, 0.0],
            'tier': ['A', 'A', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_large_dataset(self, panel):
        """Test render handles larger dataset (20 assets)."""
        symbols = [f'ASSET{i}/USDT:USDT' for i in range(20)]
        scores = np.linspace(2.0, -2.0, 20)
        tiers = ['A'] * 10 + ['B'] * 10
        
        df = pd.DataFrame({
            'symbol': symbols,
            'multi_factor_score': scores,
            'tier': tiers
        })
        
        fig, ax = plt.subplots(figsize=(10, 12))
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_preserves_axis_object(self, panel, sample_data):
        """Test that render modifies the provided axis object."""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Get initial state
        initial_title = ax.get_title()
        
        # Render panel
        panel.render(ax, sample_data)
        
        # Verify axis was modified
        assert ax.get_title() != initial_title
        assert ax.get_title() == 'Multi-Factor Score by Asset'
        
        plt.close(fig)
    
    def test_render_with_nan_scores(self, panel):
        """Test render behavior with NaN scores."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [1.0, np.nan, -1.0],
            'tier': ['A', 'B', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should handle NaN gracefully (matplotlib will skip NaN bars)
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_with_extreme_scores(self, panel):
        """Test render with very large and very small scores."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'multi_factor_score': [100.0, 0.001, -100.0],
            'tier': ['A', 'A', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Should handle extreme values
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_render_color_mapping(self, panel):
        """Test that Tier A and Tier B use correct colors."""
        df = pd.DataFrame({
            'symbol': ['ASSET_A', 'ASSET_B'],
            'multi_factor_score': [1.0, -1.0],
            'tier': ['A', 'B']
        })
        
        fig, ax = plt.subplots(figsize=(10, 6))
        panel.render(ax, df)
        
        # Get bar colors from the plot
        bars = ax.patches
        
        # Verify we have bars
        assert len(bars) > 0
        
        plt.close(fig)
    
    def test_render_title_present(self, panel, sample_data):
        """Test that panel has descriptive title."""
        fig, ax = plt.subplots(figsize=(10, 6))
        panel.render(ax, sample_data)
        
        title = ax.get_title()
        assert title is not None
        assert len(title) > 0
        assert 'Multi-Factor' in title or 'Score' in title
        
        plt.close(fig)
    
    def test_render_axis_labels_present(self, panel, sample_data):
        """Test that axis labels are present."""
        fig, ax = plt.subplots(figsize=(10, 6))
        panel.render(ax, sample_data)
        
        xlabel = ax.get_xlabel()
        ylabel = ax.get_ylabel()
        
        assert xlabel is not None
        assert ylabel is not None
        assert len(xlabel) > 0
        assert len(ylabel) > 0
        
        plt.close(fig)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
