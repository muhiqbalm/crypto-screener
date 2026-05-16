#!/usr/bin/env python3
"""
Visual test for DashboardBuilder - generates an actual dashboard image.

This script creates a sample dashboard to visually verify the layout and appearance.
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

from src.signals.generator import SignalGenerator
from src.signals.ic_weights import ICWeightCalculator
from src.signals.scorer import MultiFactorScorer
from src.ranking.engine import RankingEngine
from src.visualization.dashboard import DashboardBuilder


def create_sample_dashboard():
    """Create a sample dashboard with realistic data."""
    print("Creating sample dashboard...")
    
    # Create realistic sample market data
    market_data = pd.DataFrame({
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                  'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
        'price': [45.2, 320.5, 5.8, 180.3, 95.7],
        'change_24h': [5.2, -3.1, 8.5, -1.2, 2.8],
        'funding_rate': [0.015, -0.008, 0.022, -0.012, 0.005],
        'long_short_ratio': [1.3, 1.7, 1.1, 0.9, 1.6]
    })
    
    print("Processing signals...")
    # Process through signal generation pipeline
    signal_gen = SignalGenerator()
    market_data['reversal_signal'] = signal_gen.calculate_reversal_signal(market_data)
    market_data['reversal_signal'] = signal_gen.normalize_signal(market_data['reversal_signal'])
    
    market_data['momentum_signal'] = signal_gen.calculate_momentum_signal(market_data)
    market_data['momentum_signal'] = signal_gen.normalize_signal(market_data['momentum_signal'])
    
    print("Calculating scores...")
    # Calculate multi-factor scores
    ic_calc = ICWeightCalculator()
    scorer = MultiFactorScorer(ic_calc)
    market_data['multi_factor_score'] = scorer.calculate_score(market_data)
    market_data['tier'] = scorer.classify_tiers(market_data['multi_factor_score'])
    
    print("Ranking assets...")
    # Rank assets
    ranker = RankingEngine()
    ranked_data = ranker.rank_assets(market_data)
    
    print("\nRanked Data:")
    print(ranked_data[['symbol', 'multi_factor_score', 'tier', 'funding_rate', 'long_short_ratio']])
    
    print("\nCreating dashboard...")
    # Create dashboard
    builder = DashboardBuilder(ranked_data)
    fig = builder.create_dashboard()
    
    # Save dashboard
    output_file = "sample_dashboard.png"
    builder.save_dashboard(output_file)
    
    print(f"\nDashboard saved to: {output_file}")
    print("Dashboard creation successful!")
    
    # Clean up
    plt.close(fig)


if __name__ == "__main__":
    create_sample_dashboard()
