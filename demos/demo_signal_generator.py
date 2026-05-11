"""
Demo script for SignalGenerator class.

This script demonstrates the signal generation functionality including:
- Reversal signal calculation
- Momentum signal calculation
- Signal normalization
"""

import pandas as pd
import numpy as np
from crypto_screener import SignalGenerator


def main():
    print("=" * 70)
    print("SignalGenerator Demo")
    print("=" * 70)
    print()
    
    # Create sample market data
    print("Creating sample market data...")
    df = pd.DataFrame({
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                   'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
        'price': [45.23, 512.45, 5.67, 234.56, 123.45],
        'change_24h': [5.2, -3.1, 2.8, -1.5, 4.3]
    })
    
    print("\nMarket Data:")
    print(df.to_string(index=False))
    print()
    
    # Initialize SignalGenerator
    generator = SignalGenerator()
    
    # Calculate reversal signal
    print("-" * 70)
    print("1. Calculating Reversal Signal (simulated logic: -1 * change_24h)")
    print("-" * 70)
    reversal_signal = generator.calculate_reversal_signal(df)
    df['reversal_signal'] = reversal_signal
    
    print("\nReversal Signal (raw):")
    for idx, row in df.iterrows():
        print(f"  {row['symbol']:20s} | change_24h: {row['change_24h']:6.2f}% | reversal: {row['reversal_signal']:6.2f}")
    print()
    
    # Calculate momentum signal
    print("-" * 70)
    print("2. Calculating Momentum Signal (simulated with random factor)")
    print("-" * 70)
    momentum_signal = generator.calculate_momentum_signal(df)
    df['momentum_signal'] = momentum_signal
    
    print("\nMomentum Signal (raw):")
    for idx, row in df.iterrows():
        print(f"  {row['symbol']:20s} | change_24h: {row['change_24h']:6.2f}% | momentum: {row['momentum_signal']:6.2f}")
    print()
    
    # Normalize reversal signal
    print("-" * 70)
    print("3. Normalizing Reversal Signal (z-score normalization)")
    print("-" * 70)
    reversal_normalized = generator.normalize_signal(reversal_signal)
    df['reversal_normalized'] = reversal_normalized
    
    print("\nReversal Signal (normalized):")
    print(f"  Mean: {reversal_normalized.mean():.10f} (should be ≈ 0)")
    print(f"  Std:  {reversal_normalized.std():.10f} (should be ≈ 1)")
    print()
    for idx, row in df.iterrows():
        print(f"  {row['symbol']:20s} | raw: {row['reversal_signal']:6.2f} | normalized: {row['reversal_normalized']:7.4f}")
    print()
    
    # Normalize momentum signal
    print("-" * 70)
    print("4. Normalizing Momentum Signal (z-score normalization)")
    print("-" * 70)
    momentum_normalized = generator.normalize_signal(momentum_signal)
    df['momentum_normalized'] = momentum_normalized
    
    print("\nMomentum Signal (normalized):")
    print(f"  Mean: {momentum_normalized.mean():.10f} (should be ≈ 0)")
    print(f"  Std:  {momentum_normalized.std():.10f} (should be ≈ 1)")
    print()
    for idx, row in df.iterrows():
        print(f"  {row['symbol']:20s} | raw: {row['momentum_signal']:6.2f} | normalized: {row['momentum_normalized']:7.4f}")
    print()
    
    # Display final DataFrame
    print("-" * 70)
    print("5. Final DataFrame with All Signals")
    print("-" * 70)
    print()
    print(df.to_string(index=False))
    print()
    
    # Test edge cases
    print("=" * 70)
    print("Edge Case Testing")
    print("=" * 70)
    print()
    
    # Test with single asset
    print("Test 1: Single Asset (should return zero for normalization)")
    single_df = pd.DataFrame({
        'symbol': ['BTC/USDT:USDT'],
        'change_24h': [5.0]
    })
    single_reversal = generator.calculate_reversal_signal(single_df)
    single_normalized = generator.normalize_signal(single_reversal)
    print(f"  Raw signal: {single_reversal.iloc[0]}")
    print(f"  Normalized: {single_normalized.iloc[0]} (expected: 0.0)")
    print()
    
    # Test with zero variance
    print("Test 2: Zero Variance (all identical values)")
    zero_var_df = pd.DataFrame({
        'symbol': ['BTC', 'ETH', 'SOL'],
        'change_24h': [3.0, 3.0, 3.0]
    })
    zero_var_reversal = generator.calculate_reversal_signal(zero_var_df)
    zero_var_normalized = generator.normalize_signal(zero_var_reversal)
    print(f"  Raw signals: {zero_var_reversal.tolist()}")
    print(f"  Normalized: {zero_var_normalized.tolist()} (expected: all zeros)")
    print()
    
    # Test with NaN values
    print("Test 3: NaN Values (should be preserved)")
    nan_df = pd.DataFrame({
        'symbol': ['BTC', 'ETH', 'SOL'],
        'change_24h': [5.0, np.nan, 3.0]
    })
    nan_reversal = generator.calculate_reversal_signal(nan_df)
    nan_normalized = generator.normalize_signal(nan_reversal)
    print(f"  Raw signals: {nan_reversal.tolist()}")
    print(f"  Normalized: {nan_normalized.tolist()}")
    print(f"  NaN preserved: {pd.isna(nan_normalized.iloc[1])}")
    print()
    
    print("=" * 70)
    print("Demo Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
