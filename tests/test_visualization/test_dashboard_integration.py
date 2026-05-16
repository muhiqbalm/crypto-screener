#!/usr/bin/env python3
"""
Integration test for DashboardBuilder with complete pipeline.

Tests that DashboardBuilder works correctly with data from the complete
signal processing and ranking pipeline.
"""

import pytest
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for testing
import matplotlib.pyplot as plt
import os

from src.signals.generator import SignalGenerator
from src.signals.ic_weights import ICWeightCalculator
from src.signals.scorer import MultiFactorScorer
from src.ranking.engine import RankingEngine
from src.visualization.dashboard import DashboardBuilder


class TestDashboardIntegrationWithPipeline:
    """Test DashboardBuilder integration with complete data pipeline."""
    
    def test_dashboard_with_pipeline_data(self, tmp_path):
        """Test creating dashboard with data from complete signal processing pipeline."""
        # Create sample market data
        market_data = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                      'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [45.2, 320.5, 5.8, 180.3, 95.7],
            'change_24h': [5.2, -3.1, 8.5, -1.2, 2.8],
            'funding_rate': [0.015, -0.008, 0.022, -0.012, 0.005],
            'long_short_ratio': [1.3, 1.7, 1.1, 0.9, 1.6]
        })
        
        # Process through signal generation pipeline
        signal_gen = SignalGenerator()
        market_data['reversal_signal'] = signal_gen.calculate_reversal_signal(market_data)
        market_data['reversal_signal'] = signal_gen.normalize_signal(market_data['reversal_signal'])
        
        market_data['momentum_signal'] = signal_gen.calculate_momentum_signal(market_data)
        market_data['momentum_signal'] = signal_gen.normalize_signal(market_data['momentum_signal'])
        
        # Calculate multi-factor scores
        ic_calc = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calc)
        market_data['multi_factor_score'] = scorer.calculate_score(market_data)
        market_data['tier'] = scorer.classify_tiers(market_data['multi_factor_score'])
        
        # Rank assets
        ranker = RankingEngine()
        ranked_data = ranker.rank_assets(market_data)
        
        # Create dashboard
        builder = DashboardBuilder(ranked_data)
        fig = builder.create_dashboard()
        
        # Verify dashboard was created
        assert fig is not None
        assert len(fig.get_axes()) == 3
        
        # Save dashboard
        filepath = tmp_path / "pipeline_dashboard.png"
        builder.save_dashboard(str(filepath))
        assert filepath.exists()
        
        # Clean up
        plt.close(fig)
    
    def test_dashboard_with_missing_optional_data(self, tmp_path):
        """Test dashboard handles missing optional data (funding_rate, long_short_ratio)."""
        # Create market data with some missing values
        market_data = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
            'price': [50000.0, 3000.0, 100.0],
            'change_24h': [2.5, -1.8, 5.3],
            'funding_rate': [0.01, np.nan, -0.02],  # One missing value
            'long_short_ratio': [1.2, 1.5, np.nan]  # One missing value
        })
        
        # Process through pipeline
        signal_gen = SignalGenerator()
        market_data['reversal_signal'] = signal_gen.calculate_reversal_signal(market_data)
        market_data['reversal_signal'] = signal_gen.normalize_signal(market_data['reversal_signal'])
        
        market_data['momentum_signal'] = signal_gen.calculate_momentum_signal(market_data)
        market_data['momentum_signal'] = signal_gen.normalize_signal(market_data['momentum_signal'])
        
        ic_calc = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calc)
        market_data['multi_factor_score'] = scorer.calculate_score(market_data)
        market_data['tier'] = scorer.classify_tiers(market_data['multi_factor_score'])
        
        ranker = RankingEngine()
        ranked_data = ranker.rank_assets(market_data)
        
        # Create dashboard (should handle NaN values gracefully)
        builder = DashboardBuilder(ranked_data)
        fig = builder.create_dashboard()
        
        assert fig is not None
        
        # Save dashboard
        filepath = tmp_path / "dashboard_with_missing_data.png"
        builder.save_dashboard(str(filepath))
        assert filepath.exists()
        
        # Clean up
        plt.close(fig)
    
    def test_dashboard_ordering_consistency(self):
        """Test that all panels display assets in the same order."""
        # Create sample data
        market_data = pd.DataFrame({
            'symbol': ['A/USDT:USDT', 'B/USDT:USDT', 'C/USDT:USDT', 'D/USDT:USDT'],
            'price': [100.0, 200.0, 300.0, 400.0],
            'change_24h': [5.0, -2.0, 3.0, -1.0],
            'funding_rate': [0.01, -0.02, 0.03, -0.01],
            'long_short_ratio': [1.2, 1.5, 0.9, 1.8]
        })
        
        # Process through pipeline
        signal_gen = SignalGenerator()
        market_data['reversal_signal'] = signal_gen.calculate_reversal_signal(market_data)
        market_data['reversal_signal'] = signal_gen.normalize_signal(market_data['reversal_signal'])
        
        market_data['momentum_signal'] = signal_gen.calculate_momentum_signal(market_data)
        market_data['momentum_signal'] = signal_gen.normalize_signal(market_data['momentum_signal'])
        
        ic_calc = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calc)
        market_data['multi_factor_score'] = scorer.calculate_score(market_data)
        market_data['tier'] = scorer.classify_tiers(market_data['multi_factor_score'])
        
        ranker = RankingEngine()
        ranked_data = ranker.rank_assets(market_data)
        
        # Create dashboard
        builder = DashboardBuilder(ranked_data)
        fig = builder.create_dashboard()
        
        # Extract Y-axis labels from all three panels
        axes = fig.get_axes()
        y_labels_panel1 = [label.get_text() for label in axes[0].get_yticklabels()]
        y_labels_panel2 = [label.get_text() for label in axes[1].get_yticklabels()]
        y_labels_panel3 = [label.get_text() for label in axes[2].get_yticklabels()]
        
        # Filter out empty labels
        y_labels_panel1 = [label for label in y_labels_panel1 if label]
        y_labels_panel2 = [label for label in y_labels_panel2 if label]
        y_labels_panel3 = [label for label in y_labels_panel3 if label]
        
        # Verify all panels have the same Y-axis labels in the same order
        # (This validates Property 8: Visualization Order Consistency)
        assert y_labels_panel1 == y_labels_panel2, "Panel 1 and 2 have different Y-axis ordering"
        assert y_labels_panel2 == y_labels_panel3, "Panel 2 and 3 have different Y-axis ordering"
        
        # Clean up
        plt.close(fig)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
