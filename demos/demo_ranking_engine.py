"""
Demo script for RankingEngine class.

This script demonstrates the ranking functionality by creating sample data
with multi-factor scores and showing how assets are ranked in descending order.
"""

import pandas as pd
from crypto_screener import RankingEngine


def main():
    """Demonstrate RankingEngine functionality."""
    print("=" * 70)
    print("RankingEngine Demo")
    print("=" * 70)
    print()
    
    # Create sample DataFrame with multi-factor scores
    print("Creating sample data with multi-factor scores...")
    df = pd.DataFrame({
        'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 
                   'AAVE/USDT:USDT', 'ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
        'price': [50000, 3000, 100, 250, 45, 500, 5],
        'change_24h': [2.5, -1.3, 5.0, 0.8, -2.1, 3.2, 1.5],
        'reversal_signal': [-0.5, 0.8, -1.2, -0.3, 1.0, -0.7, -0.4],
        'momentum_signal': [1.2, -0.5, 1.8, 0.3, -0.8, 1.0, 0.5],
        'multi_factor_score': [0.69, -0.20, 0.90, 0.06, -0.26, 0.49, 0.23],
        'tier': ['A', 'B', 'A', 'A', 'B', 'A', 'B']
    })
    
    print("\nOriginal DataFrame (unsorted):")
    print(df[['symbol', 'multi_factor_score', 'tier']].to_string(index=False))
    print()
    
    # Create RankingEngine instance
    print("Creating RankingEngine instance...")
    engine = RankingEngine()
    print()
    
    # Rank assets
    print("Ranking assets by multi-factor score...")
    df_ranked = engine.rank_assets(df)
    print()
    
    # Display ranked results
    print("Ranked DataFrame (sorted by multi_factor_score descending):")
    print(df_ranked[['rank', 'symbol', 'multi_factor_score', 'tier']].to_string(index=False))
    print()
    
    # Show top 3 assets
    print("=" * 70)
    print("Top 3 Ranked Assets:")
    print("=" * 70)
    for i in range(min(3, len(df_ranked))):
        row = df_ranked.iloc[i]
        print(f"Rank {row['rank']}: {row['symbol']}")
        print(f"  Multi-Factor Score: {row['multi_factor_score']:.4f}")
        print(f"  Tier: {row['tier']}")
        print(f"  Price: ${row['price']:.2f}")
        print(f"  24h Change: {row['change_24h']:.2f}%")
        print()
    
    # Demonstrate stable sort with duplicate scores
    print("=" * 70)
    print("Stable Sort Demonstration (Equal Scores)")
    print("=" * 70)
    print()
    
    # Create DataFrame with duplicate scores
    df_duplicates = pd.DataFrame({
        'symbol': ['Asset_A', 'Asset_B', 'Asset_C', 'Asset_D', 'Asset_E'],
        'multi_factor_score': [1.0, 1.0, 0.5, 1.0, 0.5]
    })
    
    print("Original order with duplicate scores:")
    print(df_duplicates.to_string(index=False))
    print()
    
    # Rank with stable sort
    df_duplicates_ranked = engine.rank_assets(df_duplicates)
    
    print("After ranking (stable sort preserves relative order):")
    print(df_duplicates_ranked.to_string(index=False))
    print()
    print("Note: Assets with score 1.0 maintain order A, B, D")
    print("      Assets with score 0.5 maintain order C, E")
    print()
    
    print("=" * 70)
    print("Demo Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
