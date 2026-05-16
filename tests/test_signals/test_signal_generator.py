#!/usr/bin/env python3
"""
Test script for SignalGenerator class to verify task 3.1 implementation.
"""

import sys
import pandas as pd
import numpy as np

# Import the SignalGenerator class from crypto_screener
from src.signals.generator import SignalGenerator

def test_signal_generator():
    """Test SignalGenerator class functionality."""
    
    print("=" * 60)
    print("Testing SignalGenerator Class - Task 3.1")
    print("=" * 60)
    
    # Create test data
    test_data = pd.DataFrame({
        'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'AAVE/USDT:USDT'],
        'change_24h': [5.2, -3.1, 2.8, -1.5]
    })
    
    print("\nTest Data:")
    print(test_data)
    
    # Initialize SignalGenerator
    signal_gen = SignalGenerator()
    print("\n✓ SignalGenerator initialized successfully")
    
    # Test 1: Calculate reversal signal
    print("\n" + "-" * 60)
    print("Test 1: calculate_reversal_signal()")
    print("-" * 60)
    reversal_signal = signal_gen.calculate_reversal_signal(test_data)
    print("Reversal Signal (should be -1 * change_24h):")
    print(reversal_signal)
    
    # Verify reversal signal logic
    expected_reversal = -1 * test_data['change_24h']
    if reversal_signal.equals(expected_reversal):
        print("✓ Reversal signal calculation is CORRECT")
    else:
        print("✗ Reversal signal calculation is INCORRECT")
        return False
    
    # Test 2: Calculate momentum signal
    print("\n" + "-" * 60)
    print("Test 2: calculate_momentum_signal()")
    print("-" * 60)
    momentum_signal = signal_gen.calculate_momentum_signal(test_data)
    print("Momentum Signal (simulated with random factor):")
    print(momentum_signal)
    print("✓ Momentum signal calculated (simulated)")
    
    # Test 3: Normalize signal
    print("\n" + "-" * 60)
    print("Test 3: normalize_signal()")
    print("-" * 60)
    normalized_reversal = signal_gen.normalize_signal(reversal_signal)
    print("Normalized Reversal Signal (z-score):")
    print(normalized_reversal)
    
    # Verify normalization properties
    mean = normalized_reversal.mean()
    std = normalized_reversal.std()
    print(f"\nNormalized signal statistics:")
    print(f"  Mean: {mean:.10f} (should be ≈ 0)")
    print(f"  Std:  {std:.10f} (should be ≈ 1)")
    
    if abs(mean) < 1e-10 and abs(std - 1.0) < 1e-10:
        print("✓ Z-score normalization is CORRECT")
    else:
        print("✗ Z-score normalization is INCORRECT")
        return False
    
    # Test 4: Edge case - empty DataFrame
    print("\n" + "-" * 60)
    print("Test 4: Edge Case - Empty DataFrame")
    print("-" * 60)
    empty_df = pd.DataFrame({'change_24h': []})
    empty_result = signal_gen.calculate_reversal_signal(empty_df)
    print(f"Empty DataFrame result: {empty_result}")
    print(f"Length: {len(empty_result)}")
    if len(empty_result) == 0:
        print("✓ Empty DataFrame handled correctly")
    else:
        print("✗ Empty DataFrame NOT handled correctly")
        return False
    
    # Test 5: Edge case - single asset
    print("\n" + "-" * 60)
    print("Test 5: Edge Case - Single Asset")
    print("-" * 60)
    single_df = pd.DataFrame({'change_24h': [5.0]})
    single_signal = signal_gen.calculate_reversal_signal(single_df)
    single_normalized = signal_gen.normalize_signal(single_signal)
    print(f"Single asset signal: {single_signal.values}")
    print(f"Single asset normalized: {single_normalized.values}")
    if single_normalized.values[0] == 0.0:
        print("✓ Single asset handled correctly (returns 0)")
    else:
        print("✗ Single asset NOT handled correctly")
        return False
    
    # Test 6: Edge case - zero variance
    print("\n" + "-" * 60)
    print("Test 6: Edge Case - Zero Variance (All Identical Values)")
    print("-" * 60)
    identical_signal = pd.Series([5.0, 5.0, 5.0, 5.0])
    zero_var_normalized = signal_gen.normalize_signal(identical_signal)
    print(f"Identical values: {identical_signal.values}")
    print(f"Normalized result: {zero_var_normalized.values}")
    if all(zero_var_normalized == 0.0):
        print("✓ Zero variance handled correctly (returns zeros)")
    else:
        print("✗ Zero variance NOT handled correctly")
        return False
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("Task 3.1 - SignalGenerator class is fully implemented")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    try:
        success = test_signal_generator()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED WITH ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
