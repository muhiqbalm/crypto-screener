#!/usr/bin/env python3
"""
Test script for FundingRatePanel class.

This script creates sample data and tests the FundingRatePanel visualization
to ensure it renders correctly with proper colors, labels, reference lines, and layout.
"""

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Import the FundingRatePanel class from crypto_screener
from crypto_screener import FundingRatePanel

def create_sample_data():
    """
    Create sample DataFrame with funding rates.
    
    Returns:
        pd.DataFrame: Sample data with symbol, funding_rate, and multi_factor_score columns
    """
    # Create sample data with 5 assets
    # Include both positive and negative funding rates to test color mapping
    data = {
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
        'funding_rate': [0.0125, -0.0087, 0.0234, -0.0156, 0.0045],  # Mix of positive and negative
        'multi_factor_score': [0.856, 0.423, -0.125, -0.389, -0.765]  # For ordering
    }
    
    df = pd.DataFrame(data)
    
    # Sort by multi_factor_score descending (as RankingEngine would do)
    # This ensures Y-axis order matches the multi-factor panel
    df = df.sort_values('multi_factor_score', ascending=False).reset_index(drop=True)
    
    return df

def test_funding_rate_panel():
    """
    Test the FundingRatePanel class with sample data.
    """
    print("Testing FundingRatePanel class...")
    
    # Create sample data
    df = create_sample_data()
    print(f"\nSample data created with {len(df)} assets:")
    print(df)
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create FundingRatePanel instance and render
    panel = FundingRatePanel()
    panel.render(ax, df)
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = 'test_funding_rate_panel_output.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_file}")
    
    # Display the plot
    plt.show()
    
    print("\nTest completed successfully!")

def test_empty_dataframe():
    """
    Test FundingRatePanel with empty DataFrame to verify error handling.
    """
    print("\nTesting FundingRatePanel with empty DataFrame...")
    
    # Create empty DataFrame with correct columns
    df = pd.DataFrame(columns=['symbol', 'funding_rate', 'multi_factor_score'])
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create FundingRatePanel instance and render
    panel = FundingRatePanel()
    panel.render(ax, df)
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = 'test_funding_rate_panel_empty.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Empty DataFrame visualization saved to: {output_file}")
    
    plt.close()
    
    print("Empty DataFrame test completed successfully!")

def test_missing_columns():
    """
    Test FundingRatePanel with missing columns to verify error handling.
    """
    print("\nTesting FundingRatePanel with missing columns...")
    
    # Create DataFrame with missing 'funding_rate' column
    df = pd.DataFrame({
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
        'multi_factor_score': [0.5, -0.3]
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create FundingRatePanel instance and try to render
    panel = FundingRatePanel()
    
    try:
        panel.render(ax, df)
        print("ERROR: Should have raised KeyError for missing columns!")
        return False
    except KeyError as e:
        print(f"Correctly raised KeyError: {e}")
        plt.close()
        return True

def test_nan_values():
    """
    Test FundingRatePanel with NaN values to verify graceful handling.
    """
    print("\nTesting FundingRatePanel with NaN values...")
    
    # Create DataFrame with some NaN funding rates
    data = {
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
        'funding_rate': [0.0125, np.nan, -0.0087],  # Middle value is NaN
        'multi_factor_score': [0.856, 0.423, -0.125]
    }
    
    df = pd.DataFrame(data)
    df = df.sort_values('multi_factor_score', ascending=False).reset_index(drop=True)
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create FundingRatePanel instance and render
    panel = FundingRatePanel()
    panel.render(ax, df)
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = 'test_funding_rate_panel_nan.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"NaN values visualization saved to: {output_file}")
    
    plt.close()
    
    print("NaN values test completed successfully!")

def test_extreme_values():
    """
    Test FundingRatePanel with extreme positive and negative values.
    """
    print("\nTesting FundingRatePanel with extreme values...")
    
    # Create DataFrame with extreme funding rates
    data = {
        'symbol': ['EXTREME_POS', 'MODERATE_POS', 'ZERO', 'MODERATE_NEG', 'EXTREME_NEG'],
        'funding_rate': [0.5, 0.05, 0.0, -0.05, -0.5],  # Wide range
        'multi_factor_score': [1.0, 0.5, 0.0, -0.5, -1.0]
    }
    
    df = pd.DataFrame(data)
    df = df.sort_values('multi_factor_score', ascending=False).reset_index(drop=True)
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create FundingRatePanel instance and render
    panel = FundingRatePanel()
    panel.render(ax, df)
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = 'test_funding_rate_panel_extreme.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Extreme values visualization saved to: {output_file}")
    
    plt.close()
    
    print("Extreme values test completed successfully!")

if __name__ == "__main__":
    # Run tests
    test_funding_rate_panel()
    test_empty_dataframe()
    test_missing_columns()
    test_nan_values()
    test_extreme_values()
    
    print("\n" + "="*60)
    print("All tests completed!")
    print("="*60)
