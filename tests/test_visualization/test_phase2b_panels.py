"""
Unit tests for Phase 2b visualization panels (Sparkline and OI Delta).

Tests cover:
- SparklinePanel rendering with valid data
- SparklinePanel color coding
- OIDeltaPanel rendering with valid data
- OIDeltaPanel reference line at 0%
"""

import pytest
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from src.visualization.panels import SparklinePanel, OIDeltaPanel


class TestSparklinePanel:
    """Test suite for SparklinePanel class."""
    
    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame with sparkline data."""
        return pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [0.85, 0.72, 0.60],
            'sparkline_data': [
                [50000 + i*100 for i in range(24)],  # Uptrend
                [3000 - i*10 for i in range(24)],    # Downtrend
                [150 for _ in range(24)]              # Neutral (flat)
            ],
            'sparkline_trend': ['uptrend', 'downtrend', 'neutral']
        })
    
    @pytest.fixture
    def ax(self):
        """Create matplotlib axes for testing."""
        fig, ax = plt.subplots(figsize=(10, 6))
        return ax
    
    def test_sparkline_panel_rendering_basic(self, sample_df, ax):
        """Test basic SparklinePanel rendering with valid data."""
        panel = SparklinePanel()
        
        # Should not raise any exceptions
        panel.render(ax, sample_df)
        
        # Verify panel title
        assert ax.get_title() == '24h Price Trend (Sparkline)'
        
        # Verify Y-axis has correct number of ticks (one per asset)
        assert len(ax.get_yticks()) == len(sample_df)
        
        # Verify Y-axis labels match symbols (reversed order)
        y_labels = [label.get_text() for label in ax.get_yticklabels()]
        expected_labels = sample_df['symbol'].values[::-1].tolist()
        assert y_labels == expected_labels
    
    def test_sparkline_color_coding_uptrend(self, ax):
        """Test color coding for uptrend sparklines."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'sparkline_data': [[50000 + i*100 for i in range(24)]],
            'sparkline_trend': ['uptrend']
        })
        
        panel = SparklinePanel()
        panel.render(ax, df)
        
        # Check that lines were plotted
        lines = ax.get_lines()
        assert len(lines) > 0
        
        # Verify green color for uptrend (#4CAF50)
        line_color = lines[0].get_color()
        # Color can be in different formats, check if it's greenish
        assert line_color == '#4CAF50' or line_color == (0.298, 0.686, 0.314, 0.8)
    
    def test_sparkline_color_coding_downtrend(self, ax):
        """Test color coding for downtrend sparklines."""
        df = pd.DataFrame({
            'symbol': ['ETH/USDT:USDT'],
            'sparkline_data': [[3000 - i*10 for i in range(24)]],
            'sparkline_trend': ['downtrend']
        })
        
        panel = SparklinePanel()
        panel.render(ax, df)
        
        # Check that lines were plotted
        lines = ax.get_lines()
        assert len(lines) > 0
        
        # Verify red color for downtrend (#F44336)
        line_color = lines[0].get_color()
        # Color can be in different formats, check if it's reddish
        assert line_color == '#F44336' or line_color == (0.957, 0.263, 0.212, 0.8)
    
    def test_sparkline_color_coding_neutral(self, ax):
        """Test color coding for neutral sparklines."""
        df = pd.DataFrame({
            'symbol': ['SOL/USDT:USDT'],
            'sparkline_data': [[150 for _ in range(24)]],
            'sparkline_trend': ['neutral']
        })
        
        panel = SparklinePanel()
        panel.render(ax, df)
        
        # Check that lines were plotted
        lines = ax.get_lines()
        assert len(lines) > 0
        
        # Verify gray color for neutral (#9E9E9E)
        line_color = lines[0].get_color()
        # Color can be in different formats, check if it's grayish
        assert line_color == '#9E9E9E' or line_color == (0.620, 0.620, 0.620, 0.8)
    
    def test_sparkline_missing_data_handling(self, ax):
        """Test handling of missing sparkline data."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'sparkline_data': [None, np.nan],
            'sparkline_trend': ['neutral', 'neutral']
        })
        
        panel = SparklinePanel()
        
        # Should not raise exceptions
        panel.render(ax, df)
        
        # Verify "No data" text is displayed
        texts = [text.get_text() for text in ax.texts]
        assert 'No data' in texts or len(texts) >= 2
    
    def test_sparkline_empty_dataframe(self, ax):
        """Test handling of empty DataFrame."""
        df = pd.DataFrame({
            'symbol': [],
            'sparkline_data': [],
            'sparkline_trend': []
        })
        
        panel = SparklinePanel()
        
        # Should not raise exceptions
        panel.render(ax, df)
        
        # Verify "No data available" message
        texts = [text.get_text() for text in ax.texts]
        assert 'No data available' in texts
    
    def test_sparkline_missing_columns(self, ax):
        """Test error handling for missing required columns."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT']
            # Missing sparkline_data and sparkline_trend columns
        })
        
        panel = SparklinePanel()
        
        # Should raise KeyError for missing columns
        with pytest.raises(KeyError):
            panel.render(ax, df)
    
    def test_sparkline_normalization(self, ax):
        """Test min-max normalization of sparkline data."""
        # Create data with known min/max
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'sparkline_data': [[100, 200, 150, 300, 250]],  # Min=100, Max=300
            'sparkline_trend': ['uptrend']
        })
        
        panel = SparklinePanel()
        panel.render(ax, df)
        
        # Verify lines were plotted
        lines = ax.get_lines()
        assert len(lines) > 0
        
        # Verify Y-axis range is normalized (should be within row space)
        y_data = lines[0].get_ydata()
        assert y_data.min() >= -0.5  # Should be within plot bounds
        assert y_data.max() <= 0.5
    
    def test_sparkline_single_price_point(self, ax):
        """Test handling of single price point (insufficient data)."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'sparkline_data': [[50000]],  # Only one price
            'sparkline_trend': ['neutral']
        })
        
        panel = SparklinePanel()
        
        # Should handle gracefully (may show "No data" or skip)
        panel.render(ax, df)
        
        # Should not crash
        assert True


class TestOIDeltaPanel:
    """Test suite for OIDeltaPanel class."""
    
    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame with OI delta data."""
        return pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [0.85, 0.72, 0.60],
            'oi_delta_percent': [15.5, -8.3, 0.5]
        })
    
    @pytest.fixture
    def ax(self):
        """Create matplotlib axes for testing."""
        fig, ax = plt.subplots(figsize=(10, 6))
        return ax
    
    def test_oi_delta_panel_rendering_basic(self, sample_df, ax):
        """Test basic OIDeltaPanel rendering with valid data."""
        panel = OIDeltaPanel()
        
        # Should not raise any exceptions
        panel.render(ax, sample_df)
        
        # Verify panel title
        assert ax.get_title() == 'OI Delta 24h (Market Context)'
        
        # Verify X-axis label
        assert ax.get_xlabel() == 'OI Delta (%)'
        
        # Verify Y-axis label
        assert ax.get_ylabel() == 'Asset Symbol'
        
        # Verify bars were created (one per asset)
        bars = [patch for patch in ax.patches if patch.get_height() > 0]
        assert len(bars) == len(sample_df)
    
    def test_oi_delta_reference_line_at_zero(self, sample_df, ax):
        """Test that reference line is drawn at 0%."""
        panel = OIDeltaPanel()
        panel.render(ax, sample_df)
        
        # Check for vertical line at x=0
        vertical_lines = [line for line in ax.get_lines() if line.get_xdata()[0] == 0]
        assert len(vertical_lines) > 0
        
        # Verify line properties
        ref_line = vertical_lines[0]
        assert ref_line.get_linestyle() == '-'
        assert ref_line.get_color() == 'black'
    
    def test_oi_delta_color_coding_positive(self, ax):
        """Test color coding for positive OI delta (blue)."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'oi_delta_percent': [15.5]
        })
        
        panel = OIDeltaPanel()
        panel.render(ax, df)
        
        # Get bar colors
        bars = ax.patches
        assert len(bars) > 0
        
        # Verify blue color for positive delta (#2196F3)
        bar_color = bars[0].get_facecolor()
        # Check if color is blueish
        assert bar_color[2] > 0.8  # High blue component
    
    def test_oi_delta_color_coding_negative(self, ax):
        """Test color coding for negative OI delta (orange)."""
        df = pd.DataFrame({
            'symbol': ['ETH/USDT:USDT'],
            'oi_delta_percent': [-8.3]
        })
        
        panel = OIDeltaPanel()
        panel.render(ax, df)
        
        # Get bar colors
        bars = ax.patches
        assert len(bars) > 0
        
        # Verify orange color for negative delta (#FF9800)
        bar_color = bars[0].get_facecolor()
        # Check if color is orangeish (high red, medium green, low blue)
        assert bar_color[0] > 0.8  # High red component
    
    def test_oi_delta_color_coding_near_zero(self, ax):
        """Test color coding for near-zero OI delta (gray)."""
        df = pd.DataFrame({
            'symbol': ['SOL/USDT:USDT'],
            'oi_delta_percent': [0.1]  # Very small change
        })
        
        panel = OIDeltaPanel()
        panel.render(ax, df)
        
        # Get bar colors
        bars = ax.patches
        assert len(bars) > 0
        
        # Near-zero should use gray color (#9E9E9E)
        bar_color = bars[0].get_facecolor()
        # Gray has equal RGB components
        assert abs(bar_color[0] - bar_color[1]) < 0.1
        assert abs(bar_color[1] - bar_color[2]) < 0.1
    
    def test_oi_delta_missing_data_handling(self, ax):
        """Test handling of missing OI delta data."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'oi_delta_percent': [np.nan, None]
        })
        
        panel = OIDeltaPanel()
        
        # Should not raise exceptions
        panel.render(ax, df)
        
        # Verify placeholder text is displayed
        texts = [text.get_text() for text in ax.texts]
        assert 'N/A' in texts or len(texts) >= 2
    
    def test_oi_delta_empty_dataframe(self, ax):
        """Test handling of empty DataFrame."""
        df = pd.DataFrame({
            'symbol': [],
            'oi_delta_percent': []
        })
        
        panel = OIDeltaPanel()
        
        # Should not raise exceptions
        panel.render(ax, df)
        
        # Verify "No data available" message
        texts = [text.get_text() for text in ax.texts]
        assert 'No data available' in texts
    
    def test_oi_delta_missing_columns(self, ax):
        """Test error handling for missing required columns."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT']
            # Missing oi_delta_percent column
        })
        
        panel = OIDeltaPanel()
        
        # Should raise KeyError for missing columns
        with pytest.raises(KeyError):
            panel.render(ax, df)
    
    def test_oi_delta_label_formatting(self, sample_df, ax):
        """Test that OI delta labels are formatted to 1 decimal place."""
        panel = OIDeltaPanel()
        panel.render(ax, sample_df)
        
        # Check text labels on bars
        texts = [text.get_text() for text in ax.texts]
        
        # Filter for percentage labels (should contain '%')
        percent_labels = [text for text in texts if '%' in text]
        
        # Verify at least some labels exist
        assert len(percent_labels) > 0
        
        # Verify format (should have 1 decimal place)
        for label in percent_labels:
            if label != 'N/A':
                # Extract number part
                num_str = label.replace('%', '').strip()
                # Should have format like "15.5" or "-8.3"
                assert '.' in num_str
                decimal_part = num_str.split('.')[1]
                assert len(decimal_part) == 1  # 1 decimal place
    
    def test_oi_delta_extreme_values(self, ax):
        """Test handling of extreme OI delta values."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'oi_delta_percent': [150.0, -95.0]  # Extreme values
        })
        
        panel = OIDeltaPanel()
        
        # Should handle gracefully without crashing
        panel.render(ax, df)
        
        # Verify bars were created
        bars = ax.patches
        assert len(bars) >= 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
