"""
Demo script for MultiFactorScorer class.

This script demonstrates how to use the MultiFactorScorer to:
1. Calculate multi-factor scores from normalized signals
2. Classify assets into Tier A and Tier B
"""

import pandas as pd
import numpy as np
from crypto_screener import MultiFactorScorer, ICWeightCalculator, SignalGenerator


def main():
    print("=" * 70)
    print("MultiFactorScorer Demo")
    print("=" * 70)
    print()
    
    # Create sample market data
    print("1. Creating sample market data...")
    df = pd.DataFrame({
        'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 
                   'AVAX/USDT:USDT', 'MATIC/USDT:USDT', 'LINK/USDT:USDT'],
        'price': [45000, 2500, 100, 35, 0.85, 15],
        'change_24h': [5.2, 3.1, -2.5, 1.8, -4.3, 0.5]
    })
    print(df)
    print()
    
    # Generate signals
    print("2. Generating trading signals...")
    signal_gen = SignalGenerator()
    
    # Calculate reversal signal
    reversal_signal = signal_gen.calculate_reversal_signal(df)
    df['reversal_signal_raw'] = reversal_signal
    
    # Calculate momentum signal
    momentum_signal = signal_gen.calculate_momentum_signal(df)
    df['momentum_signal_raw'] = momentum_signal
    
    # Normalize signals
    df['reversal_signal'] = signal_gen.normalize_signal(reversal_signal)
    df['momentum_signal'] = signal_gen.normalize_signal(momentum_signal)
    
    print("Normalized signals:")
    print(df[['symbol', 'reversal_signal', 'momentum_signal']])
    print()
    
    # Initialize IC weight calculator and scorer
    print("3. Initializing MultiFactorScorer...")
    ic_calculator = ICWeightCalculator()
    scorer = MultiFactorScorer(ic_calculator)
    
    print(f"IC Weights: reversal_1d={ic_calculator.get_weight('reversal_1d')}, "
          f"momentum_30d={ic_calculator.get_weight('momentum_30d')}")
    print()
    
    # Calculate multi-factor scores
    print("4. Calculating multi-factor scores...")
    df['multi_factor_score'] = scorer.calculate_score(df)
    
    print("Multi-factor scores:")
    print(df[['symbol', 'reversal_signal', 'momentum_signal', 'multi_factor_score']])
    print()
    
    # Classify tiers
    print("5. Classifying assets into tiers...")
    df['tier'] = scorer.classify_tiers(df['multi_factor_score'])
    
    # Sort by score for better visualization
    df_sorted = df.sort_values('multi_factor_score', ascending=False)
    
    print("Final results (sorted by score):")
    print(df_sorted[['symbol', 'multi_factor_score', 'tier']])
    print()
    
    # Show tier distribution
    tier_counts = df['tier'].value_counts()
    print("Tier distribution:")
    print(f"  Tier A (top 50%): {tier_counts.get('A', 0)} assets")
    print(f"  Tier B (bottom 50%): {tier_counts.get('B', 0)} assets")
    print()
    
    # Show median threshold
    median_score = df['multi_factor_score'].median()
    print(f"Median score threshold: {median_score:.4f}")
    print(f"  Assets with score >= {median_score:.4f} are classified as Tier A")
    print(f"  Assets with score < {median_score:.4f} are classified as Tier B")
    print()
    
    # Explain the scoring formula
    print("=" * 70)
    print("Scoring Formula:")
    print("=" * 70)
    print("Multi-factor score = 0.3 × reversal_signal + 0.7 × momentum_signal")
    print()
    print("Where:")
    print("  - reversal_signal: Normalized 1-day reversal signal (mean reversion)")
    print("  - momentum_signal: Normalized 30-day momentum signal (trend following)")
    print("  - IC weights (0.3, 0.7): Historical predictive power of each signal")
    print()
    print("Example calculation for", df_sorted.iloc[0]['symbol'] + ":")
    rev_sig = df_sorted.iloc[0]['reversal_signal']
    mom_sig = df_sorted.iloc[0]['momentum_signal']
    score = df_sorted.iloc[0]['multi_factor_score']
    print(f"  Score = 0.3 × {rev_sig:.4f} + 0.7 × {mom_sig:.4f}")
    print(f"        = {0.3 * rev_sig:.4f} + {0.7 * mom_sig:.4f}")
    print(f"        = {score:.4f}")
    print()
    
    print("=" * 70)
    print("Demo complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
