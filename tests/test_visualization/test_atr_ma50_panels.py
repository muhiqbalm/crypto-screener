#!/usr/bin/env python3
"""
Unit tests for ATRPanel and MA50Panel visualization classes.

Tests cover:
- ATRPanel rendering with valid data
- ATRPanel color thresholds
- MA50Panel rendering with valid data
- MA50Panel reference line at 0%
- Panels with missing data columns
"""

import pytest
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from src.visualization.panels import ATRPanel, MA50Panel


class TestATRPanelRendering:
    """Tests for ATRPanel rendering with valid data."""

    def setup_method(self):
        """Set up test fixtures."""
        self.panel = ATRPanel()

    def teardown_method(self):
        """Clean up matplotlib figures."""
        plt.close('all')

    def test_renders_without_error(self):
        """Test that ATRPanel renders without raising exceptions."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'atr_percent': [2.5, 4.5, 7.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        # No exception means success

    def test_renders_correct_number_of_bars(self):
        """Test that the correct number of bars are rendered."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'atr_percent': [2.5, 4.5, 7.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        # Check that 3 bars were created
        bars = [p for p in ax.patches if hasattr(p, 'get_width')]
        assert len(bars) == 3

    def test_renders_with_nan_values(self):
        """Test that ATRPanel handles NaN values gracefully."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'atr_percent': [2.5, np.nan, 7.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        # No exception means success

    def test_renders_empty_dataframe(self):
        """Test that ATRPanel handles empty DataFrame."""
        df = pd.DataFrame({'symbol': [], 'atr_percent': []})
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        # Should show "No data available" text

    def test_title_is_set(self):
        """Test that the panel title is correctly set."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'atr_percent': [2.5]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        assert ax.get_title() == 'ATR (Volatility Risk)'


class TestATRPanelColorThresholds:
    """Tests for ATRPanel color coding thresholds."""

    def setup_method(self):
        """Set up test fixtures."""
        self.panel = ATRPanel()

    def teardown_method(self):
        """Clean up matplotlib figures."""
        plt.close('all')

    def test_low_volatility_green(self):
        """Test that ATR < 3% gets green color."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'atr_percent': [2.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        # Green color #4CAF50
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        # Verify it's green-ish (R < G)
        assert color[1] > color[0]  # Green > Red

    def test_medium_volatility_yellow(self):
        """Test that 3% <= ATR <= 6% gets yellow color."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'atr_percent': [4.5]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        # Yellow #FFC107 has high R and G, low B
        assert color[0] > 0.5  # Red component high
        assert color[1] > 0.5  # Green component high

    def test_high_volatility_red(self):
        """Test that ATR > 6% gets red color."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'atr_percent': [8.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        # Red #F44336 has high R, low G and B
        assert color[0] > color[1]  # Red > Green

    def test_boundary_3_percent_is_medium(self):
        """Test that exactly 3% is classified as medium (yellow)."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'atr_percent': [3.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        # Should be yellow (medium), not green (low)
        assert color[0] > 0.5  # High red (yellow has high R)

    def test_boundary_6_percent_is_medium(self):
        """Test that exactly 6% is classified as medium (yellow)."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'atr_percent': [6.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        # Should be yellow (medium), not red (high)
        assert color[1] > 0.5  # High green (yellow has high G)


class TestMA50PanelRendering:
    """Tests for MA50Panel rendering with valid data."""

    def setup_method(self):
        """Set up test fixtures."""
        self.panel = MA50Panel()

    def teardown_method(self):
        """Clean up matplotlib figures."""
        plt.close('all')

    def test_renders_without_error(self):
        """Test that MA50Panel renders without raising exceptions."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'distance_to_ma50': [5.2, -3.1, 12.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)

    def test_renders_correct_number_of_bars(self):
        """Test that the correct number of bars are rendered."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'distance_to_ma50': [5.2, -3.1, 12.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = [p for p in ax.patches if hasattr(p, 'get_width')]
        assert len(bars) == 3

    def test_renders_with_nan_values(self):
        """Test that MA50Panel handles NaN values gracefully."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT'],
            'distance_to_ma50': [5.2, np.nan]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)

    def test_renders_empty_dataframe(self):
        """Test that MA50Panel handles empty DataFrame."""
        df = pd.DataFrame({'symbol': [], 'distance_to_ma50': []})
        fig, ax = plt.subplots()
        self.panel.render(ax, df)

    def test_title_is_set(self):
        """Test that the panel title is correctly set."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'distance_to_ma50': [5.2]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        assert ax.get_title() == 'Distance to MA50 (Price Context)'

    def test_positive_distance_green(self):
        """Test that positive distance gets green color."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'distance_to_ma50': [5.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        assert color[1] > color[0]  # Green > Red

    def test_negative_distance_red(self):
        """Test that negative distance gets red color."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT'],
            'distance_to_ma50': [-5.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        bars = ax.patches
        assert len(bars) >= 1
        color = bars[0].get_facecolor()
        assert color[0] > color[1]  # Red > Green


class TestMA50PanelReferenceLine:
    """Tests for MA50Panel reference line at 0%."""

    def setup_method(self):
        """Set up test fixtures."""
        self.panel = MA50Panel()

    def teardown_method(self):
        """Clean up matplotlib figures."""
        plt.close('all')

    def test_reference_line_exists(self):
        """Test that a vertical reference line at 0% exists."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT', 'ETH/USDT'],
            'distance_to_ma50': [5.0, -3.0]
        })
        fig, ax = plt.subplots()
        self.panel.render(ax, df)
        # Check for vertical lines (axvline creates Line2D objects)
        lines = ax.get_lines()
        # Find line at x=0
        has_zero_line = any(
            line.get_xdata()[0] == 0 for line in lines
            if len(line.get_xdata()) > 0
        )
        assert has_zero_line


class TestPanelsMissingColumns:
    """Tests for panels with missing data columns."""

    def teardown_method(self):
        """Clean up matplotlib figures."""
        plt.close('all')

    def test_atr_panel_missing_atr_percent_raises(self):
        """Test that ATRPanel raises KeyError when atr_percent column is missing."""
        panel = ATRPanel()
        df = pd.DataFrame({'symbol': ['BTC/USDT'], 'other_col': [1.0]})
        fig, ax = plt.subplots()
        with pytest.raises(KeyError):
            panel.render(ax, df)

    def test_atr_panel_missing_symbol_raises(self):
        """Test that ATRPanel raises KeyError when symbol column is missing."""
        panel = ATRPanel()
        df = pd.DataFrame({'atr_percent': [2.5], 'other_col': [1.0]})
        fig, ax = plt.subplots()
        with pytest.raises(KeyError):
            panel.render(ax, df)

    def test_ma50_panel_missing_distance_raises(self):
        """Test that MA50Panel raises KeyError when distance_to_ma50 column is missing."""
        panel = MA50Panel()
        df = pd.DataFrame({'symbol': ['BTC/USDT'], 'other_col': [1.0]})
        fig, ax = plt.subplots()
        with pytest.raises(KeyError):
            panel.render(ax, df)

    def test_ma50_panel_missing_symbol_raises(self):
        """Test that MA50Panel raises KeyError when symbol column is missing."""
        panel = MA50Panel()
        df = pd.DataFrame({'distance_to_ma50': [5.0], 'other_col': [1.0]})
        fig, ax = plt.subplots()
        with pytest.raises(KeyError):
            panel.render(ax, df)
