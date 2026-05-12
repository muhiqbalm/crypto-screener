"""
Visualization Panels Module

Contains panel classes for different visualization types.
"""

import logging
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)


class MultiFactorPanel:
    """
    Renders multi-factor score visualization panel.
    
    This class creates a horizontal bar chart displaying the composite multi-factor
    score for each asset. Assets are ordered by score (highest to lowest) and colored
    by tier classification:
    - Tier A (top 50%): Darker color #C85A82
    - Tier B (bottom 50%): Lighter shade #E8A5B8
    
    The visualization includes numeric score values displayed on or near each bar
    for easy reading.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for multi-factor scores.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (highest at top)
        2. X-axis: Multi-factor score values
        3. Bar colors: Tier A uses #C85A82 (darker), Tier B uses #E8A5B8 (lighter)
        4. Score labels: Numeric values displayed on each bar for readability
        5. Panel title: Descriptive title indicating multi-factor score content
        
        Color Scheme Rationale:
        - Darker color (#C85A82) for Tier A draws attention to top-performing assets
        - Lighter shade (#E8A5B8) for Tier B provides visual hierarchy
        - Both colors are from the same family for cohesive appearance
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'multi_factor_score': Composite score (float)
                - 'tier': Tier classification ('A' or 'B')
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'multi_factor_score', 'tier']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for MultiFactorPanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to MultiFactorPanel.render()")
            ax.text(0.5, 0.5, 'No data available', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # We'll reverse the order for plotting so highest scores appear at the top
        symbols = df['symbol'].values[::-1]  # Reverse for top-to-bottom display
        scores = df['multi_factor_score'].values[::-1]
        tiers = df['tier'].values[::-1]
        
        # Define colors for each tier
        # Tier A: Darker color #C85A82 (strong pink/rose)
        # Tier B: Lighter shade #E8A5B8 (light pink/rose)
        tier_colors = {
            'A': '#C85A82',  # Darker color for top-performing assets
            'B': '#E8A5B8'   # Lighter shade for lower-performing assets
        }
        
        # Map each asset to its tier color
        bar_colors = [tier_colors.get(tier, '#CCCCCC') for tier in tiers]
        
        # Create horizontal bar chart
        # Y-axis: Asset symbols (ordered by score, highest at top)
        # X-axis: Multi-factor score values
        bars = ax.barh(symbols, scores, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add numeric score values on each bar for readability
        # Position labels at the end of each bar (or inside if bar is long enough)
        for i, (bar, score) in enumerate(zip(bars, scores)):
            # Get bar width (score value)
            width = bar.get_width()
            
            # Determine label position: inside bar if positive, outside if negative
            if width >= 0:
                # Positive score: place label inside bar at the right edge
                label_x = width - 0.05 * abs(ax.get_xlim()[1] - ax.get_xlim()[0])
                ha = 'right'
            else:
                # Negative score: place label inside bar at the left edge
                label_x = width + 0.05 * abs(ax.get_xlim()[1] - ax.get_xlim()[0])
                ha = 'left'
            
            # Add text label with score value
            ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                   f'{score:.3f}',  # Format to 3 decimal places
                   ha=ha, va='center',
                   color='white', fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Multi-Factor Score by Asset', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Multi-Factor Score', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Add vertical reference line at 0 for visual reference
        ax.axvline(x=0, color='black', linestyle='-', linewidth=0.8, alpha=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"MultiFactorPanel rendered with {len(df)} assets")


class FundingRatePanel:
    """
    Renders funding rate visualization panel.
    
    This class creates a horizontal bar chart displaying the funding rate percentage
    for each asset. Assets are ordered consistently with the multi-factor panel
    (by multi-factor score, highest to lowest). Bars are colored based on the sign
    of the funding rate:
    - Negative rates (short bias/squeeze potential): Green/blue color scheme
    - Positive rates (crowded long positions): Red/orange color scheme
    
    A vertical reference line at 0% helps identify the transition between negative
    and positive funding rates.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for funding rates.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (same order as multi-factor panel)
        2. X-axis: Funding rate percentage values
        3. Reference line: Vertical line at 0% to separate negative/positive rates
        4. Bar colors:
           - Negative rates: #4CAF50 (green) - indicates short bias or squeeze potential
           - Positive rates: #FF5722 (red/orange) - indicates crowded long positions
        5. Panel title: Descriptive title indicating funding rate content
        
        Color Scheme Rationale:
        - Green for negative rates: Suggests potential short squeeze opportunity
        - Red/orange for positive rates: Warning color for crowded long positions
        - 0% reference line: Clear visual separator between the two regimes
        
        Funding Rate Interpretation:
        - Negative funding rate: Shorts pay longs (short bias in market)
        - Positive funding rate: Longs pay shorts (long bias in market)
        - Extreme rates (far from 0%) indicate crowded positioning
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'funding_rate': Funding rate percentage (float)
                - 'multi_factor_score': Used for ordering (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'funding_rate']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for FundingRatePanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to FundingRatePanel.render()")
            ax.text(0.5, 0.5, 'No data available', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # We'll reverse the order for plotting so highest scores appear at the top
        # This ensures Y-axis order matches the multi-factor panel
        symbols = df['symbol'].values[::-1]  # Reverse for top-to-bottom display
        funding_rates = df['funding_rate'].values[::-1]
        
        # Define colors based on funding rate sign
        # Negative rates: Green (#4CAF50) - short bias, potential squeeze
        # Positive rates: Red/orange (#FF5722) - long bias, crowded positioning
        bar_colors = []
        for rate in funding_rates:
            if pd.isna(rate):
                # Handle missing data with neutral gray color
                bar_colors.append('#CCCCCC')
            elif rate < 0:
                # Negative funding rate: green (short bias)
                bar_colors.append('#4CAF50')
            else:
                # Positive funding rate: red/orange (long bias)
                bar_colors.append('#FF5722')
        
        # Create horizontal bar chart
        # Y-axis: Asset symbols (same order as multi-factor panel)
        # X-axis: Funding rate percentage values
        bars = ax.barh(symbols, funding_rates, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add vertical reference line at 0% to separate negative/positive rates
        # This line helps identify the transition between short bias and long bias
        ax.axvline(x=0, color='black', linestyle='-', linewidth=1.2, alpha=0.7, zorder=3)
        
        # Add numeric funding rate values on each bar for readability
        # Position labels at the end of each bar (or inside if bar is long enough)
        for i, (bar, rate) in enumerate(zip(bars, funding_rates)):
            # Skip label if rate is NaN
            if pd.isna(rate):
                continue
            
            # Get bar width (funding rate value)
            width = bar.get_width()
            
            # Determine label position: inside bar if value is large enough, outside if small
            x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0])
            threshold = 0.1 * x_range  # 10% of x-axis range
            
            if abs(width) > threshold:
                # Large bar: place label inside bar
                if width >= 0:
                    label_x = width - 0.02 * x_range
                    ha = 'right'
                else:
                    label_x = width + 0.02 * x_range
                    ha = 'left'
                text_color = 'white'
            else:
                # Small bar: place label outside bar
                if width >= 0:
                    label_x = width + 0.02 * x_range
                    ha = 'left'
                else:
                    label_x = width - 0.02 * x_range
                    ha = 'right'
                text_color = 'black'
            
            # Add text label with funding rate value
            ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                   f'{rate:.4f}%',  # Format to 4 decimal places (funding rates are typically small)
                   ha=ha, va='center',
                   color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Funding Rate by Asset', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Funding Rate (%)', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"FundingRatePanel rendered with {len(df)} assets")


class LongShortRatioPanel:
    """
    Renders long/short ratio visualization panel.
    
    This class creates a horizontal bar chart displaying the long/short ratio
    for each asset. Assets are ordered consistently with the multi-factor panel
    (by multi-factor score, highest to lowest). Bars exceeding the 1.5 threshold
    are highlighted to indicate crowded long positioning.
    
    Two vertical reference lines are displayed:
    - 1.0 (neutral): Equal long and short positions
    - 1.5 (warning): Threshold for crowded long positioning
    
    Ratios above 1.5 indicate potentially overcrowded long positions that may
    be vulnerable to reversal or liquidation cascades.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for long/short ratios.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (same order as multi-factor panel)
        2. X-axis: Long/short ratio values
        3. Reference lines:
           - Vertical line at 1.0 (neutral positioning)
           - Vertical line at 1.5 (warning threshold for crowded longs)
        4. Bar colors:
           - Normal (ratio <= 1.5): #2196F3 (blue) - normal positioning
           - Warning (ratio > 1.5): #FFC107 (amber/yellow) - crowded long positioning
        5. Panel title: Descriptive title indicating long/short ratio content
        
        Color Scheme Rationale:
        - Blue for normal ratios: Calm, neutral color for balanced positioning
        - Amber/yellow for high ratios: Warning color for crowded long positions
        - 1.0 reference line: Shows neutral positioning (equal longs and shorts)
        - 1.5 reference line: Shows warning threshold for overcrowded positioning
        
        Long/Short Ratio Interpretation:
        - Ratio = 1.0: Equal long and short positions (neutral)
        - Ratio > 1.0: More longs than shorts (bullish bias)
        - Ratio < 1.0: More shorts than longs (bearish bias)
        - Ratio > 1.5: Crowded long positioning (potential reversal risk)
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'long_short_ratio': Long/short ratio (float)
                - 'multi_factor_score': Used for ordering (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'long_short_ratio']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for LongShortRatioPanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to LongShortRatioPanel.render()")
            ax.text(0.5, 0.5, 'No data available', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # We'll reverse the order for plotting so highest scores appear at the top
        # This ensures Y-axis order matches the multi-factor panel
        symbols = df['symbol'].values[::-1]  # Reverse for top-to-bottom display
        ls_ratios = df['long_short_ratio'].values[::-1]
        
        # Define colors based on long/short ratio threshold
        # Normal (ratio <= 1.5): Blue (#2196F3) - normal positioning
        # Warning (ratio > 1.5): Amber/yellow (#FFC107) - crowded long positioning
        WARNING_THRESHOLD = 1.5
        bar_colors = []
        for ratio in ls_ratios:
            if pd.isna(ratio):
                # Handle missing data with neutral gray color
                bar_colors.append('#CCCCCC')
            elif ratio > WARNING_THRESHOLD:
                # High ratio: amber/yellow (warning for crowded longs)
                bar_colors.append('#FFC107')
            else:
                # Normal ratio: blue (normal positioning)
                bar_colors.append('#2196F3')
        
        # Create horizontal bar chart
        # Y-axis: Asset symbols (same order as multi-factor panel)
        # X-axis: Long/short ratio values
        bars = ax.barh(symbols, ls_ratios, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add vertical reference line at 1.0 (neutral positioning)
        # This line indicates equal long and short positions
        ax.axvline(x=1.0, color='black', linestyle='-', linewidth=1.2, alpha=0.7, zorder=3,
                  label='Neutral (1.0)')
        
        # Add vertical reference line at 1.5 (warning threshold)
        # This line indicates the threshold for crowded long positioning
        ax.axvline(x=1.5, color='red', linestyle='--', linewidth=1.2, alpha=0.7, zorder=3,
                  label='Warning (1.5)')
        
        # Add numeric long/short ratio values on each bar for readability
        # Position labels at the end of each bar (or inside if bar is long enough)
        for i, (bar, ratio) in enumerate(zip(bars, ls_ratios)):
            # Skip label if ratio is NaN
            if pd.isna(ratio):
                continue
            
            # Get bar width (long/short ratio value)
            width = bar.get_width()
            
            # Determine label position: inside bar if value is large enough, outside if small
            x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0])
            threshold = 0.15 * x_range  # 15% of x-axis range
            
            if abs(width) > threshold:
                # Large bar: place label inside bar at the right edge
                label_x = width - 0.02 * x_range
                ha = 'right'
                text_color = 'white'
            else:
                # Small bar: place label outside bar to the right
                label_x = width + 0.02 * x_range
                ha = 'left'
                text_color = 'black'
            
            # Add text label with long/short ratio value
            ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                   f'{ratio:.2f}',  # Format to 2 decimal places
                   ha=ha, va='center',
                   color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Long/Short Ratio by Asset', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Long/Short Ratio', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Add legend for reference lines
        ax.legend(loc='lower right', fontsize=8, framealpha=0.9)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"LongShortRatioPanel rendered with {len(df)} assets")
