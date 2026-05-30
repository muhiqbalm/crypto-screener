#!/usr/bin/env python3
"""
Test script for MultiFactorPanel class.

This script creates sample data and tests the MultiFactorPanel visualization
to ensure it renders correctly with proper colors, labels, and layout.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Import the MultiFactorPanel class from crypto_screener
from src.visualization.panels import MultiFactorPanel

# Directory for test-generated images. Resolved relative to the project root
# so artifacts land in <project>/output/test_artifacts regardless of cwd.
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "output" / "test_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def create_sample_data():
    """
    Create sample DataFrame with multi-factor scores and tier classifications.
    
    Returns:
        pd.DataFrame: Sample data with symbol, multi_factor_score, and tier columns
    """
    # Create sample data with 5 assets
    data = {
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
        'multi_factor_score': [0.856, 0.423, -0.125, -0.389, -0.765],
        'tier': ['A', 'A', 'B', 'B', 'B']
    }
    
    df = pd.DataFrame(data)
    
    # Sort by multi_factor_score descending (as RankingEngine would do)
    df = df.sort_values('multi_factor_score', ascending=False).reset_index(drop=True)
    
    return df

def test_multi_factor_panel():
    """
    Test the MultiFactorPanel class with sample data.
    """
    print("Testing MultiFactorPanel class...")
    
    # Create sample data
    df = create_sample_data()
    print(f"\nSample data created with {len(df)} assets:")
    print(df)
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create MultiFactorPanel instance and render
    panel = MultiFactorPanel()
    panel.render(ax, df)
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = ARTIFACT_DIR / 'test_multi_factor_panel_output.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_file}")
    
    # Display the plot
    plt.show()
    
    print("\nTest completed successfully!")

def test_empty_dataframe():
    """
    Test MultiFactorPanel with empty DataFrame to verify error handling.
    """
    print("\nTesting MultiFactorPanel with empty DataFrame...")
    
    # Create empty DataFrame with correct columns
    df = pd.DataFrame(columns=['symbol', 'multi_factor_score', 'tier'])
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create MultiFactorPanel instance and render
    panel = MultiFactorPanel()
    panel.render(ax, df)
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = ARTIFACT_DIR / 'test_multi_factor_panel_empty.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Empty DataFrame visualization saved to: {output_file}")
    
    plt.close()
    
    print("Empty DataFrame test completed successfully!")

def test_missing_columns():
    """
    Test MultiFactorPanel with missing columns to verify error handling.
    """
    print("\nTesting MultiFactorPanel with missing columns...")
    
    # Create DataFrame with missing 'tier' column
    df = pd.DataFrame({
        'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
        'multi_factor_score': [0.5, -0.3]
    })
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create MultiFactorPanel instance and try to render
    panel = MultiFactorPanel()
    
    try:
        panel.render(ax, df)
        print("ERROR: Should have raised KeyError for missing columns!")
        return False
    except KeyError as e:
        print(f"Correctly raised KeyError: {e}")
        plt.close()
        return True

if __name__ == "__main__":
    # Run tests
    test_multi_factor_panel()
    test_empty_dataframe()
    test_missing_columns()
    
    print("\n" + "="*60)
    print("All tests completed!")
    print("="*60)
