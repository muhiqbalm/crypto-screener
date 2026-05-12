"""
Visualization Panels Module

Contains panel classes for different visualization types.
"""

import logging
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)


class ATRPanel:
    """
    Renders ATR (Average True Range) visualization panel.
    
    This class creates a horizontal bar chart displaying the ATR percentage
    for each asset. Assets are ordered consistently with the multi-factor panel
    (by multi-factor score, highest to lowest). Bars are colored based on
    volatility thresholds:
    - Green (#4CAF50): ATR < 3% (low volatility)
    - Yellow (#FFC107): 3% <= ATR <= 6% (medium volatility)
    - Red (#F44336): ATR > 6% (high volatility)
    
    The visualization includes numeric ATR percentage values displayed on each bar
    formatted to 2 decimal places.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for ATR percentage values.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (highest at top)
        2. X-axis: ATR percentage values (0% to max)
        3. Bar colors: Based on volatility thresholds
           - Green (#4CAF50): ATR < 3% (low volatility)
           - Yellow (#FFC107): 3% <= ATR <= 6% (medium volatility)
           - Red (#F44336): ATR > 6% (high volatility)
        4. Labels: ATR % formatted to 2 decimal places
        5. Panel title: "ATR (Volatility Risk)"
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'atr_percent': ATR as percentage of price (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'atr_percent']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for ATRPanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to ATRPanel.render()")
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            ax.set_title('ATR (Volatility Risk)', fontsize=12, fontweight='bold', pad=10)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # Reverse the order for plotting so highest scores appear at the top
        symbols = df['symbol'].values[::-1]
        atr_values = df['atr_percent'].values[::-1]
        
        # Define colors based on ATR volatility thresholds
        # Green (#4CAF50): ATR < 3% (low volatility)
        # Yellow (#FFC107): 3% <= ATR <= 6% (medium volatility)
        # Red (#F44336): ATR > 6% (high volatility)
        bar_colors = []
        display_values = []
        has_missing = False
        
        for atr in atr_values:
            if pd.isna(atr):
                bar_colors.append('#CCCCCC')
                display_values.append(0)
                has_missing = True
            elif atr < 3.0:
                bar_colors.append('#4CAF50')  # Green - low volatility
                display_values.append(atr)
            elif atr <= 6.0:
                bar_colors.append('#FFC107')  # Yellow - medium volatility
                display_values.append(atr)
            else:
                bar_colors.append('#F44336')  # Red - high volatility
                display_values.append(atr)
        
        # Create horizontal bar chart
        bars = ax.barh(symbols, display_values, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add numeric ATR percentage values on each bar
        for i, (bar, atr) in enumerate(zip(bars, atr_values)):
            if pd.isna(atr):
                # Display placeholder text for missing data
                ax.text(0.05, bar.get_y() + bar.get_height() / 2,
                       'N/A',
                       ha='left', va='center',
                       color='gray', fontweight='bold', fontsize=9,
                       fontstyle='italic')
            else:
                # Get bar width
                width = bar.get_width()
                
                # Determine label position
                x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0]) if ax.get_xlim()[1] != ax.get_xlim()[0] else 1
                threshold = 0.15 * x_range
                
                if width > threshold:
                    # Large bar: place label inside bar at the right edge
                    label_x = width - 0.02 * x_range
                    ha = 'right'
                    text_color = 'white'
                else:
                    # Small bar: place label outside bar to the right
                    label_x = width + 0.02 * x_range
                    ha = 'left'
                    text_color = 'black'
                
                ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                       f'{atr:.2f}%',
                       ha=ha, va='center',
                       color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('ATR (Volatility Risk)', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('ATR (%)', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"ATRPanel rendered with {len(df)} assets")


class MA50Panel:
    """
    Renders Distance to MA50 visualization panel.
    
    This class creates a horizontal bar chart displaying the percentage distance
    from the current price to the 50-day moving average for each asset. Assets are
    ordered consistently with the multi-factor panel (by multi-factor score, highest
    to lowest). Bars are colored based on the sign of the distance:
    - Green (#4CAF50): Positive distance (price above MA50)
    - Red (#F44336): Negative distance (price below MA50)
    
    A vertical reference line at 0% indicates where price equals MA50.
    The visualization includes numeric distance percentage values displayed on each
    bar formatted to 2 decimal places.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for Distance to MA50 percentage values.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (highest at top)
        2. X-axis: Distance to MA50 percentage values (can be negative)
        3. Bar colors: Based on distance sign
           - Green (#4CAF50): Positive distance (price above MA50)
           - Red (#F44336): Negative distance (price below MA50)
        4. Reference line: Vertical line at 0% (price at MA50)
        5. Labels: Distance % formatted to 2 decimal places
        6. Panel title: "Distance to MA50 (Price Context)"
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'distance_to_ma50': Distance as percentage (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'distance_to_ma50']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for MA50Panel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to MA50Panel.render()")
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            ax.set_title('Distance to MA50 (Price Context)', fontsize=12, fontweight='bold', pad=10)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # Reverse the order for plotting so highest scores appear at the top
        symbols = df['symbol'].values[::-1]
        distance_values = df['distance_to_ma50'].values[::-1]
        
        # Define colors based on distance sign
        # Green (#4CAF50): Positive distance (price above MA50)
        # Red (#F44336): Negative distance (price below MA50)
        bar_colors = []
        display_values = []
        has_missing = False
        
        for dist in distance_values:
            if pd.isna(dist):
                bar_colors.append('#CCCCCC')
                display_values.append(0)
                has_missing = True
            elif dist >= 0:
                bar_colors.append('#4CAF50')  # Green - above MA50
                display_values.append(dist)
            else:
                bar_colors.append('#F44336')  # Red - below MA50
                display_values.append(dist)
        
        # Create horizontal bar chart
        bars = ax.barh(symbols, display_values, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add vertical reference line at 0% (price at MA50)
        ax.axvline(x=0, color='black', linestyle='-', linewidth=1.2, alpha=0.7, zorder=3)
        
        # Add numeric distance percentage values on each bar
        for i, (bar, dist) in enumerate(zip(bars, distance_values)):
            if pd.isna(dist):
                # Display placeholder text for missing data
                ax.text(0.05, bar.get_y() + bar.get_height() / 2,
                       'N/A',
                       ha='left', va='center',
                       color='gray', fontweight='bold', fontsize=9,
                       fontstyle='italic')
            else:
                # Get bar width
                width = bar.get_width()
                
                # Determine label position
                x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0]) if ax.get_xlim()[1] != ax.get_xlim()[0] else 1
                threshold = 0.15 * x_range
                
                if abs(width) > threshold:
                    # Large bar: place label inside bar at the end
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
                
                ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                       f'{dist:.2f}%',
                       ha=ha, va='center',
                       color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('Distance to MA50 (Price Context)', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('Distance to MA50 (%)', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"MA50Panel rendered with {len(df)} assets")


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


class SparklinePanel:
    """
    Renders 24-hour price trend sparkline visualization panel.
    
    This class creates mini line charts showing 24-hour price movement for each asset.
    Assets are ordered consistently with the multi-factor panel (by multi-factor score,
    highest to lowest). Sparklines are colored based on trend direction:
    - Green (#4CAF50): Uptrend (price increased over 24h)
    - Red (#F44336): Downtrend (price decreased over 24h)
    - Gray (#9E9E9E): Neutral (no significant change)
    
    The visualization uses min-max normalization per asset to fit sparklines in
    consistent vertical space while preserving relative price movements.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create sparkline mini charts for 24-hour price trends.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (highest at top)
        2. X-axis: Time progression (24 data points for hourly data)
        3. Line colors: Based on trend direction
           - Green (#4CAF50): Uptrend
           - Red (#F44336): Downtrend
           - Gray (#9E9E9E): Neutral
        4. Normalization: Min-max scaling per asset for consistent display
        5. Panel title: "24h Price Trend (Sparkline)"
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'sparkline_data': List of closing prices (list of float)
                - 'sparkline_trend': Trend direction ('uptrend'/'downtrend'/'neutral')
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'sparkline_data', 'sparkline_trend']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for SparklinePanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to SparklinePanel.render()")
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            ax.set_title('24h Price Trend (Sparkline)', fontsize=12, fontweight='bold', pad=10)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # Reverse the order for plotting so highest scores appear at the top
        symbols = df['symbol'].values[::-1]
        sparkline_data = df['sparkline_data'].values[::-1]
        trends = df['sparkline_trend'].values[::-1]
        
        # Define colors based on trend
        trend_colors = {
            'uptrend': '#4CAF50',    # Green
            'downtrend': '#F44336',  # Red
            'neutral': '#9E9E9E'     # Gray
        }
        
        # Create sparklines for each asset
        num_assets = len(symbols)
        
        for i, (symbol, prices, trend) in enumerate(zip(symbols, sparkline_data, trends)):
            # Handle missing data
            if prices is None or (isinstance(prices, float) and np.isnan(prices)):
                # Display "No data" text
                ax.text(0.5, i, 'No data',
                       ha='center', va='center',
                       color='gray', fontsize=8, fontstyle='italic')
                continue
            
            # Check if prices is a valid list/array
            if not isinstance(prices, (list, np.ndarray)) or len(prices) < 2:
                ax.text(0.5, i, 'No data',
                       ha='center', va='center',
                       color='gray', fontsize=8, fontstyle='italic')
                continue
            
            # Normalize prices using min-max scaling (0 to 1 range)
            prices_array = np.array(prices)
            
            price_min = prices_array.min()
            price_max = prices_array.max()
            
            if price_max == price_min:
                # Flat line - all prices the same
                normalized = np.full_like(prices_array, 0.5)
            else:
                normalized = (prices_array - price_min) / (price_max - price_min)
            
            # Scale to fit in row space (0.2 height per row, centered at row index)
            scaled = normalized * 0.4 + (i - 0.2)
            
            # Create x-axis points
            x_points = np.linspace(0, 1, len(prices_array))
            
            # Get color based on trend
            color = trend_colors.get(trend, '#9E9E9E')
            
            # Plot sparkline
            ax.plot(x_points, scaled, color=color, linewidth=1.5, alpha=0.8)
        
        # Set Y-axis to show symbols
        ax.set_yticks(range(num_assets))
        ax.set_yticklabels(symbols, fontsize=9)
        
        # Remove X-axis ticks (sparklines are relative, not absolute time)
        ax.set_xticks([])
        ax.set_xlim(0, 1)
        ax.set_ylim(-0.5, num_assets - 0.5)
        
        # Set panel title
        ax.set_title('24h Price Trend (Sparkline)', fontsize=12, fontweight='bold', pad=10)
        
        # Add subtle grid
        ax.grid(axis='y', alpha=0.2, linestyle='--', linewidth=0.5)
        
        logger.info(f"SparklinePanel rendered with {len(df)} assets")


class OIDeltaPanel:
    """
    Renders Open Interest Delta visualization panel.
    
    This class creates a horizontal bar chart displaying the 24-hour percentage change
    in Open Interest for each asset. Assets are ordered consistently with the multi-factor
    panel (by multi-factor score, highest to lowest). Bars are colored based on the sign
    of the OI delta:
    - Blue (#2196F3): Positive OI delta (Open Interest increasing)
    - Orange (#FF9800): Negative OI delta (Open Interest decreasing)
    - Gray (#9E9E9E): Zero or near-zero change
    
    A vertical reference line at 0% helps identify the transition between increasing
    and decreasing Open Interest.
    """
    
    def render(self, ax, df: pd.DataFrame):
        """
        Create horizontal bar chart for OI Delta percentage values.
        
        Visualization Logic:
        1. Y-axis: Asset symbols ordered by multi-factor score (highest at top)
        2. X-axis: OI Delta percentage values (can be negative)
        3. Bar colors: Based on OI delta sign
           - Blue (#2196F3): Positive delta (OI increasing)
           - Orange (#FF9800): Negative delta (OI decreasing)
           - Gray (#9E9E9E): Near-zero change
        4. Reference line: Vertical line at 0% (no change)
        5. Labels: OI delta % formatted to 1 decimal place
        6. Panel title: "OI Delta 24h (Market Context)"
        
        Args:
            ax: matplotlib axes object to render the chart on
            df: DataFrame with columns:
                - 'symbol': Asset symbol (str)
                - 'oi_delta_percent': OI delta as percentage (float)
                
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'oi_delta_percent']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for OIDeltaPanel: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to OIDeltaPanel.render()")
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes)
            ax.set_title('OI Delta 24h (Market Context)', fontsize=12, fontweight='bold', pad=10)
            return
        
        # Extract data for visualization
        # DataFrame is already sorted by multi_factor_score descending (from RankingEngine)
        # Reverse the order for plotting so highest scores appear at the top
        symbols = df['symbol'].values[::-1]
        oi_deltas = df['oi_delta_percent'].values[::-1]
        
        # Define colors based on OI delta sign
        # Blue: Positive (OI increasing)
        # Orange: Negative (OI decreasing)
        # Gray: Near-zero
        bar_colors = []
        display_values = []
        
        for delta in oi_deltas:
            if pd.isna(delta):
                bar_colors.append('#CCCCCC')
                display_values.append(0)
            elif abs(delta) < 0.5:  # Near-zero threshold
                bar_colors.append('#9E9E9E')  # Gray
                display_values.append(delta)
            elif delta > 0:
                bar_colors.append('#2196F3')  # Blue - OI increasing
                display_values.append(delta)
            else:
                bar_colors.append('#FF9800')  # Orange - OI decreasing
                display_values.append(delta)
        
        # Create horizontal bar chart
        bars = ax.barh(symbols, display_values, color=bar_colors, edgecolor='black', linewidth=0.5)
        
        # Add vertical reference line at 0% (no change)
        ax.axvline(x=0, color='black', linestyle='-', linewidth=1.2, alpha=0.7, zorder=3)
        
        # Add numeric OI delta percentage values on each bar
        for i, (bar, delta) in enumerate(zip(bars, oi_deltas)):
            if pd.isna(delta):
                # Display placeholder text for missing data
                ax.text(0.05, bar.get_y() + bar.get_height() / 2,
                       'N/A',
                       ha='left', va='center',
                       color='gray', fontweight='bold', fontsize=9,
                       fontstyle='italic')
            else:
                # Get bar width
                width = bar.get_width()
                
                # Determine label position
                x_range = abs(ax.get_xlim()[1] - ax.get_xlim()[0]) if ax.get_xlim()[1] != ax.get_xlim()[0] else 1
                threshold = 0.15 * x_range
                
                if abs(width) > threshold:
                    # Large bar: place label inside bar at the end
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
                
                ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                       f'{delta:.1f}%',  # 1 decimal place
                       ha=ha, va='center',
                       color=text_color, fontweight='bold', fontsize=9)
        
        # Set panel title
        ax.set_title('OI Delta 24h (Market Context)', fontsize=12, fontweight='bold', pad=10)
        
        # Set axis labels
        ax.set_xlabel('OI Delta (%)', fontsize=10)
        ax.set_ylabel('Asset Symbol', fontsize=10)
        
        # Add grid for easier reading of values
        ax.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Adjust layout for better appearance
        ax.tick_params(axis='both', labelsize=9)
        
        logger.info(f"OIDeltaPanel rendered with {len(df)} assets")
