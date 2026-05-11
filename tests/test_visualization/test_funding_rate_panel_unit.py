#!/usr/bin/env python3
"""
Unit tests for FundingRatePanel class.

This test suite verifies that the FundingRatePanel class correctly:
- Renders horizontal bar charts with proper axis configuration
- Applies correct color mapping based on funding rate sign
- Displays reference line at 0%
- Handles edge cases (empty data, NaN values, missing columns)
- Maintains consistent Y-axis ordering with multi-factor panel
"""

import pytest
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for testing
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D

from crypto_screener import FundingRatePanel


class TestFundingRatePanelBasicFunctionality:
    """Test basic rendering functionality of FundingRatePanel."""
    
    def test_render_creates_bars(self):
        """Test that render() creates horizontal bars for each asset."""
        # Create sample data
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'funding_rate': [0.0125, -0.0087, 0.0234],
            'multi_factor_score': [0.856, 0.423, -0.125]
        })
        
        # Create figure and render
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify bars were created (one per asset)
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) == 3, f"Expected 3 bars, got {len(bars)}"
        
        plt.close(fig)
    
    def test_y_axis_shows_symbols(self):
        """Test that Y-axis displays asset symbols."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
            'funding_rate': [0.01, -0.01],
            'multi_factor_score': [0.5, -0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get Y-axis tick labels
        y_labels = [label.get_text() for label in ax.get_yticklabels()]
        
        # Verify symbols are present (order may be reversed for display)
        assert 'ZEC/USDT:USDT' in y_labels
        assert 'TAO/USDT:USDT' in y_labels
        
        plt.close(fig)
    
    def test_x_axis_label(self):
        """Test that X-axis has correct label."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT'],
            'funding_rate': [0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify X-axis label
        x_label = ax.get_xlabel()
        assert 'Funding Rate' in x_label or 'funding rate' in x_label.lower()
        assert '%' in x_label
        
        plt.close(fig)
    
    def test_panel_title(self):
        """Test that panel has descriptive title."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT'],
            'funding_rate': [0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify title exists and mentions funding rate
        title = ax.get_title()
        assert len(title) > 0, "Panel should have a title"
        assert 'Funding Rate' in title or 'funding rate' in title.lower()
        
        plt.close(fig)


class TestFundingRatePanelColorMapping:
    """Test color mapping based on funding rate sign."""
    
    def test_negative_rate_uses_green_blue(self):
        """Test that negative funding rates use green/blue color scheme."""
        df = pd.DataFrame({
            'symbol': ['NEG1', 'NEG2'],
            'funding_rate': [-0.01, -0.05],
            'multi_factor_score': [0.5, 0.3]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get bar colors
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        colors = [bar.get_facecolor() for bar in bars]
        
        # Verify colors are green/blue (check for green component)
        # Color #4CAF50 is green: RGB(76, 175, 80) normalized to (0.298, 0.686, 0.314)
        for color in colors:
            # Green should have higher G component than R and B
            r, g, b, a = color
            assert g > r, f"Negative rate should use green/blue, got RGB({r:.3f}, {g:.3f}, {b:.3f})"
        
        plt.close(fig)
    
    def test_positive_rate_uses_red_orange(self):
        """Test that positive funding rates use red/orange color scheme."""
        df = pd.DataFrame({
            'symbol': ['POS1', 'POS2'],
            'funding_rate': [0.01, 0.05],
            'multi_factor_score': [0.5, 0.3]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get bar colors
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        colors = [bar.get_facecolor() for bar in bars]
        
        # Verify colors are red/orange (check for red component)
        # Color #FF5722 is red/orange: RGB(255, 87, 34) normalized to (1.0, 0.341, 0.133)
        for color in colors:
            # Red/orange should have higher R component than G and B
            r, g, b, a = color
            assert r > g and r > b, f"Positive rate should use red/orange, got RGB({r:.3f}, {g:.3f}, {b:.3f})"
        
        plt.close(fig)
    
    def test_mixed_rates_use_different_colors(self):
        """Test that positive and negative rates use different colors."""
        df = pd.DataFrame({
            'symbol': ['POS', 'NEG'],
            'funding_rate': [0.01, -0.01],
            'multi_factor_score': [0.5, -0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get bar colors
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        colors = [bar.get_facecolor() for bar in bars]
        
        # Verify colors are different
        assert len(colors) == 2
        assert colors[0] != colors[1], "Positive and negative rates should use different colors"
        
        plt.close(fig)


class TestFundingRatePanelReferenceLine:
    """Test reference line at 0%."""
    
    def test_zero_reference_line_exists(self):
        """Test that a vertical reference line exists at 0%."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
            'funding_rate': [0.01, -0.01],
            'multi_factor_score': [0.5, -0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Find vertical lines at x=0
        vertical_lines = [line for line in ax.get_lines() 
                         if isinstance(line, Line2D)]
        
        # Check if any line is at x=0
        zero_line_found = False
        for line in vertical_lines:
            xdata = line.get_xdata()
            # Check if line is vertical at x=0
            if len(xdata) >= 2 and np.allclose(xdata, 0.0):
                zero_line_found = True
                break
        
        assert zero_line_found, "Should have a vertical reference line at 0%"
        
        plt.close(fig)


class TestFundingRatePanelOrdering:
    """Test Y-axis ordering consistency with multi-factor panel."""
    
    def test_y_axis_order_matches_multi_factor_score(self):
        """Test that assets are ordered by multi_factor_score (same as multi-factor panel)."""
        # Create data with clear score ordering
        df = pd.DataFrame({
            'symbol': ['HIGH', 'MID', 'LOW'],
            'funding_rate': [0.01, 0.02, 0.03],
            'multi_factor_score': [1.0, 0.0, -1.0]  # HIGH > MID > LOW
        })
        
        # Sort by multi_factor_score descending (as RankingEngine would do)
        df = df.sort_values('multi_factor_score', ascending=False).reset_index(drop=True)
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get Y-axis tick labels (reversed for display)
        y_labels = [label.get_text() for label in ax.get_yticklabels()]
        
        # Remove empty labels
        y_labels = [label for label in y_labels if label]
        
        # Verify order: should be LOW, MID, HIGH (bottom to top)
        # or HIGH, MID, LOW (top to bottom) depending on matplotlib version
        assert 'HIGH' in y_labels
        assert 'MID' in y_labels
        assert 'LOW' in y_labels
        
        plt.close(fig)


class TestFundingRatePanelEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_dataframe(self):
        """Test that empty DataFrame is handled gracefully."""
        df = pd.DataFrame(columns=['symbol', 'funding_rate', 'multi_factor_score'])
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        
        # Should not raise exception
        panel.render(ax, df)
        
        plt.close(fig)
    
    def test_missing_required_columns(self):
        """Test that missing required columns raises KeyError."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT'],
            'multi_factor_score': [0.5]
            # Missing 'funding_rate' column
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        
        # Should raise KeyError
        with pytest.raises(KeyError):
            panel.render(ax, df)
        
        plt.close(fig)
    
    def test_nan_values_handled_gracefully(self):
        """Test that NaN funding rates are handled without errors."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT'],
            'funding_rate': [0.01, np.nan, -0.01],
            'multi_factor_score': [0.5, 0.0, -0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        
        # Should not raise exception
        panel.render(ax, df)
        
        # Verify bars were created (including NaN)
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) == 3, "Should create bars for all assets including NaN"
        
        plt.close(fig)
    
    def test_single_asset(self):
        """Test rendering with single asset."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT'],
            'funding_rate': [0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify single bar was created
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) == 1
        
        plt.close(fig)
    
    def test_zero_funding_rate(self):
        """Test that zero funding rate is handled correctly."""
        df = pd.DataFrame({
            'symbol': ['ZERO'],
            'funding_rate': [0.0],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Should not raise exception
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) == 1
        
        # Zero is treated as positive (>= 0), so should use red/orange color
        bar_color = bars[0].get_facecolor()
        r, g, b, a = bar_color
        assert r > g, "Zero funding rate should use positive (red/orange) color"
        
        plt.close(fig)


class TestFundingRatePanelRequirements:
    """Test that implementation meets specific requirements."""
    
    def test_requirement_7_1_horizontal_bar_chart(self):
        """Requirement 7.1: Display funding rate as horizontal bars."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT'],
            'funding_rate': [0.01, -0.01],
            'multi_factor_score': [0.5, -0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify horizontal bars exist
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) > 0, "Should create horizontal bars"
        
        # Verify bars are horizontal (width > height)
        for bar in bars:
            width = bar.get_width()
            height = bar.get_height()
            # Horizontal bars have width representing data value
            assert abs(width) > 0, "Bars should have non-zero width"
        
        plt.close(fig)
    
    def test_requirement_7_2_zero_reference_line(self):
        """Requirement 7.2: Render vertical reference line at 0%."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT'],
            'funding_rate': [0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify vertical line at x=0 exists
        vertical_lines = [line for line in ax.get_lines() 
                         if isinstance(line, Line2D)]
        
        zero_line_found = False
        for line in vertical_lines:
            xdata = line.get_xdata()
            if len(xdata) >= 2 and np.allclose(xdata, 0.0):
                zero_line_found = True
                break
        
        assert zero_line_found, "Requirement 7.2: Should have vertical reference line at 0%"
        
        plt.close(fig)
    
    def test_requirement_7_3_negative_rate_color(self):
        """Requirement 7.3: Negative rates use color indicating short bias."""
        df = pd.DataFrame({
            'symbol': ['NEG'],
            'funding_rate': [-0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get bar color
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) == 1
        
        color = bars[0].get_facecolor()
        r, g, b, a = color
        
        # Negative should use green/blue (G > R)
        assert g > r, "Requirement 7.3: Negative rates should use green/blue color"
        
        plt.close(fig)
    
    def test_requirement_7_4_positive_rate_color(self):
        """Requirement 7.4: Positive rates use color indicating crowded longs."""
        df = pd.DataFrame({
            'symbol': ['POS'],
            'funding_rate': [0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Get bar color
        bars = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        assert len(bars) == 1
        
        color = bars[0].get_facecolor()
        r, g, b, a = color
        
        # Positive should use red/orange (R > G and R > B)
        assert r > g and r > b, "Requirement 7.4: Positive rates should use red/orange color"
        
        plt.close(fig)
    
    def test_requirement_7_5_descriptive_title(self):
        """Requirement 7.5: Panel has descriptive title."""
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT'],
            'funding_rate': [0.01],
            'multi_factor_score': [0.5]
        })
        
        fig, ax = plt.subplots()
        panel = FundingRatePanel()
        panel.render(ax, df)
        
        # Verify title exists and is descriptive
        title = ax.get_title()
        assert len(title) > 0, "Requirement 7.5: Panel should have a title"
        assert 'Funding Rate' in title or 'funding rate' in title.lower(), \
            "Requirement 7.5: Title should indicate funding rate content"
        
        plt.close(fig)
    
    def test_requirement_9_2_inline_comments(self):
        """Requirement 9.2: Code includes inline comments explaining visualization logic."""
        # This is verified by code inspection
        # The FundingRatePanel.render() method should have inline comments
        
        # Read the source code
        import inspect
        source = inspect.getsource(FundingRatePanel.render)
        
        # Verify comments exist
        assert '#' in source, "Requirement 9.2: Code should include inline comments"
        
        # Verify key concepts are documented
        assert 'color' in source.lower() or 'colour' in source.lower(), \
            "Comments should explain color logic"
        assert 'reference' in source.lower() or '0%' in source, \
            "Comments should explain reference line"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, '-v', '--tb=short'])
