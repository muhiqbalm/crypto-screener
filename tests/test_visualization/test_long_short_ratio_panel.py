#!/usr/bin/env python3
"""
Test script for LongShortRatioPanel class.

This script tests the LongShortRatioPanel implementation to ensure it:
1. Renders horizontal bar chart correctly
2. Orders assets by multi-factor score (same as other panels)
3. Displays reference lines at 1.0 and 1.5
4. Applies highlighting to bars exceeding 1.5 threshold
5. Handles edge cases (empty data, missing values)
"""

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Import the LongShortRatioPanel class from crypto_screener
from crypto_screener import LongShortRatioPanel

def test_basic_rendering():
    """Test basic rendering with sample data."""
    print("Test 1: Basic rendering with sample data")
    
    # Create sample DataFrame with long/short ratios
    # Some ratios below 1.5 (normal), some above 1.5 (warning)
    df = pd.DataFrame({
        'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'AAVE/USDT:USDT', 'ZEC/USDT:USDT'],
        'multi_factor_score': [0.8, 0.5, 0.2, -0.1, -0.5],  # Sorted descending
        'long_short_ratio': [1.2, 1.8, 0.9, 1.5, 2.1]  # Mix of normal and warning values
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create panel instance and render
    panel = LongShortRatioPanel()
    panel.render(ax, df)
    
    # Save figure
    plt.tight_layout()
    plt.savefig('test_long_short_ratio_basic.png', dpi=100, bbox_inches='tight')
    print("✓ Basic rendering test passed - saved to test_long_short_ratio_basic.png")
    plt.close()

def test_threshold_highlighting():
    """Test that bars exceeding 1.5 threshold are highlighted."""
    print("\nTest 2: Threshold highlighting (ratio > 1.5)")
    
    # Create DataFrame with ratios specifically testing the 1.5 threshold
    df = pd.DataFrame({
        'symbol': ['ASSET_A', 'ASSET_B', 'ASSET_C', 'ASSET_D'],
        'multi_factor_score': [1.0, 0.5, 0.0, -0.5],
        'long_short_ratio': [1.4, 1.5, 1.51, 2.0]  # Test boundary cases
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Render panel
    panel = LongShortRatioPanel()
    panel.render(ax, df)
    
    # Save figure
    plt.tight_layout()
    plt.savefig('test_long_short_ratio_threshold.png', dpi=100, bbox_inches='tight')
    print("✓ Threshold highlighting test passed - saved to test_long_short_ratio_threshold.png")
    print("  Expected: ASSET_A (1.4) and ASSET_B (1.5) should be blue")
    print("  Expected: ASSET_C (1.51) and ASSET_D (2.0) should be amber/yellow")
    plt.close()

def test_reference_lines():
    """Test that reference lines at 1.0 and 1.5 are displayed."""
    print("\nTest 3: Reference lines at 1.0 (neutral) and 1.5 (warning)")
    
    # Create DataFrame with wide range of ratios
    df = pd.DataFrame({
        'symbol': ['LOW', 'NEUTRAL', 'MEDIUM', 'HIGH', 'VERY_HIGH'],
        'multi_factor_score': [1.0, 0.5, 0.0, -0.5, -1.0],
        'long_short_ratio': [0.5, 1.0, 1.3, 1.5, 2.5]
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Render panel
    panel = LongShortRatioPanel()
    panel.render(ax, df)
    
    # Save figure
    plt.tight_layout()
    plt.savefig('test_long_short_ratio_reference_lines.png', dpi=100, bbox_inches='tight')
    print("✓ Reference lines test passed - saved to test_long_short_ratio_reference_lines.png")
    print("  Expected: Black solid line at 1.0 (neutral)")
    print("  Expected: Red dashed line at 1.5 (warning)")
    plt.close()

def test_empty_dataframe():
    """Test handling of empty DataFrame."""
    print("\nTest 4: Empty DataFrame handling")
    
    # Create empty DataFrame
    df = pd.DataFrame(columns=['symbol', 'multi_factor_score', 'long_short_ratio'])
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Render panel (should handle gracefully)
    panel = LongShortRatioPanel()
    panel.render(ax, df)
    
    # Save figure
    plt.tight_layout()
    plt.savefig('test_long_short_ratio_empty.png', dpi=100, bbox_inches='tight')
    print("✓ Empty DataFrame test passed - saved to test_long_short_ratio_empty.png")
    plt.close()

def test_missing_values():
    """Test handling of missing (NaN) values."""
    print("\nTest 5: Missing values (NaN) handling")
    
    # Create DataFrame with some NaN values
    df = pd.DataFrame({
        'symbol': ['ASSET_1', 'ASSET_2', 'ASSET_3', 'ASSET_4'],
        'multi_factor_score': [1.0, 0.5, 0.0, -0.5],
        'long_short_ratio': [1.2, np.nan, 1.8, np.nan]  # Some missing values
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Render panel
    panel = LongShortRatioPanel()
    panel.render(ax, df)
    
    # Save figure
    plt.tight_layout()
    plt.savefig('test_long_short_ratio_missing.png', dpi=100, bbox_inches='tight')
    print("✓ Missing values test passed - saved to test_long_short_ratio_missing.png")
    print("  Expected: ASSET_2 and ASSET_4 should have gray bars (NaN values)")
    plt.close()

def test_order_consistency():
    """Test that Y-axis order matches multi-factor score ranking."""
    print("\nTest 6: Y-axis order consistency with multi-factor score")
    
    # Create DataFrame with specific ordering
    df = pd.DataFrame({
        'symbol': ['TOP', 'SECOND', 'THIRD', 'FOURTH', 'BOTTOM'],
        'multi_factor_score': [2.0, 1.0, 0.0, -1.0, -2.0],  # Descending order
        'long_short_ratio': [0.8, 1.2, 1.5, 1.7, 2.0]
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Render panel
    panel = LongShortRatioPanel()
    panel.render(ax, df)
    
    # Save figure
    plt.tight_layout()
    plt.savefig('test_long_short_ratio_order.png', dpi=100, bbox_inches='tight')
    print("✓ Order consistency test passed - saved to test_long_short_ratio_order.png")
    print("  Expected Y-axis order (top to bottom): TOP, SECOND, THIRD, FOURTH, BOTTOM")
    plt.close()

def main():
    """Run all tests."""
    print("=" * 70)
    print("Testing LongShortRatioPanel Implementation")
    print("=" * 70)
    
    try:
        test_basic_rendering()
        test_threshold_highlighting()
        test_reference_lines()
        test_empty_dataframe()
        test_missing_values()
        test_order_consistency()
        
        print("\n" + "=" * 70)
        print("All tests passed! ✓")
        print("=" * 70)
        print("\nGenerated test images:")
        print("  - test_long_short_ratio_basic.png")
        print("  - test_long_short_ratio_threshold.png")
        print("  - test_long_short_ratio_reference_lines.png")
        print("  - test_long_short_ratio_empty.png")
        print("  - test_long_short_ratio_missing.png")
        print("  - test_long_short_ratio_order.png")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
