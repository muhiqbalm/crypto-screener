#!/usr/bin/env python3
"""
Unit tests for DashboardBuilder class.

Tests the dashboard creation, panel coordination, and file saving functionality.
"""

import pytest
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for testing
import matplotlib.pyplot as plt
import os
from crypto_screener import DashboardBuilder


class TestDashboardBuilderInitialization:
    """Test DashboardBuilder initialization and validation."""
    
    def test_init_with_valid_dataframe(self):
        """Test initialization with valid DataFrame containing all required columns."""
        # Create valid DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [1.5, 0.8, -0.3],
            'tier': ['A', 'A', 'B'],
            'funding_rate': [0.01, -0.02, 0.03],
            'long_short_ratio': [1.2, 1.8, 0.9]
        })
        
        # Initialize DashboardBuilder
        builder = DashboardBuilder(df)
        
        # Verify initialization
        assert builder.df is not None
        assert len(builder.df) == 3
        assert builder.figure is None  # Figure not created yet
    
    def test_init_with_missing_columns(self):
        """Test initialization fails with missing required columns."""
        # Create DataFrame missing 'tier' column
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'multi_factor_score': [1.5, 0.8],
            'funding_rate': [0.01, -0.02],
            'long_short_ratio': [1.2, 1.8]
        })
        
        # Should raise KeyError for missing columns
        with pytest.raises(KeyError) as exc_info:
            DashboardBuilder(df)
        
        assert 'tier' in str(exc_info.value)
    
    def test_init_with_empty_dataframe(self):
        """Test initialization with empty DataFrame (valid but no data)."""
        # Create empty DataFrame with correct columns
        df = pd.DataFrame({
            'symbol': [],
            'multi_factor_score': [],
            'tier': [],
            'funding_rate': [],
            'long_short_ratio': []
        })
        
        # Should initialize successfully (empty data is valid)
        builder = DashboardBuilder(df)
        assert len(builder.df) == 0


class TestDashboardCreation:
    """Test dashboard creation and panel rendering."""
    
    def test_create_dashboard_basic(self):
        """Test basic dashboard creation with valid data."""
        # Create sample DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [1.5, 0.8, -0.3],
            'tier': ['A', 'A', 'B'],
            'funding_rate': [0.01, -0.02, 0.03],
            'long_short_ratio': [1.2, 1.8, 0.9]
        })
        
        # Create dashboard
        builder = DashboardBuilder(df)
        fig = builder.create_dashboard()
        
        # Verify figure was created
        assert fig is not None
        assert builder.figure is not None
        assert isinstance(fig, plt.Figure)
        
        # Verify figure has 3 subplots (axes)
        axes = fig.get_axes()
        assert len(axes) == 3
        
        # Clean up
        plt.close(fig)
    
    def test_create_dashboard_returns_figure(self):
        """Test that create_dashboard returns the figure object."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df)
        fig = builder.create_dashboard()
        
        # Verify return value is the same as stored figure
        assert fig is builder.figure
        
        # Clean up
        plt.close(fig)
    
    def test_create_dashboard_with_empty_data(self):
        """Test dashboard creation with empty DataFrame."""
        df = pd.DataFrame({
            'symbol': [],
            'multi_factor_score': [],
            'tier': [],
            'funding_rate': [],
            'long_short_ratio': []
        })
        
        builder = DashboardBuilder(df)
        fig = builder.create_dashboard()
        
        # Should create figure even with empty data
        assert fig is not None
        assert len(fig.get_axes()) == 3
        
        # Clean up
        plt.close(fig)


class TestDashboardSaving:
    """Test dashboard saving functionality."""
    
    def test_save_dashboard_png(self, tmp_path):
        """Test saving dashboard to PNG file."""
        # Create sample DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'multi_factor_score': [1.5, 0.8],
            'tier': ['A', 'A'],
            'funding_rate': [0.01, -0.02],
            'long_short_ratio': [1.2, 1.8]
        })
        
        # Create dashboard
        builder = DashboardBuilder(df)
        builder.create_dashboard()
        
        # Save to temporary file
        filepath = tmp_path / "test_dashboard.png"
        builder.save_dashboard(str(filepath))
        
        # Verify file was created
        assert filepath.exists()
        assert filepath.stat().st_size > 0  # File has content
        
        # Clean up
        plt.close(builder.figure)
    
    def test_save_dashboard_before_creation(self):
        """Test that saving fails if dashboard not created yet."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df)
        
        # Should raise RuntimeError if create_dashboard() not called
        with pytest.raises(RuntimeError) as exc_info:
            builder.save_dashboard("test.png")
        
        assert "not created yet" in str(exc_info.value).lower()
    
    def test_save_dashboard_multiple_formats(self, tmp_path):
        """Test saving dashboard in different formats (PNG, PDF)."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df)
        builder.create_dashboard()
        
        # Test PNG format
        png_path = tmp_path / "dashboard.png"
        builder.save_dashboard(str(png_path))
        assert png_path.exists()
        
        # Test PDF format
        pdf_path = tmp_path / "dashboard.pdf"
        builder.save_dashboard(str(pdf_path))
        assert pdf_path.exists()
        
        # Clean up
        plt.close(builder.figure)


class TestDashboardLayout:
    """Test dashboard layout and structure."""
    
    def test_dashboard_has_three_panels(self):
        """Test that dashboard has exactly 3 panels."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'multi_factor_score': [1.5, 0.8],
            'tier': ['A', 'A'],
            'funding_rate': [0.01, -0.02],
            'long_short_ratio': [1.2, 1.8]
        })
        
        builder = DashboardBuilder(df)
        fig = builder.create_dashboard()
        
        # Verify 3 axes (panels)
        axes = fig.get_axes()
        assert len(axes) == 3
        
        # Clean up
        plt.close(fig)
    
    def test_dashboard_panels_have_titles(self):
        """Test that all panels have descriptive titles."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df)
        fig = builder.create_dashboard()
        
        axes = fig.get_axes()
        
        # Check that each panel has a title
        for ax in axes:
            title = ax.get_title()
            assert title is not None
            assert len(title) > 0
        
        # Verify specific panel titles contain expected keywords
        titles = [ax.get_title() for ax in axes]
        assert any('Multi-Factor' in title or 'Score' in title for title in titles)
        assert any('Funding' in title for title in titles)
        assert any('Long' in title or 'Short' in title for title in titles)
        
        # Clean up
        plt.close(fig)
    
    def test_dashboard_figure_size(self):
        """Test that dashboard has appropriate figure size."""
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [1.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2]
        })
        
        builder = DashboardBuilder(df)
        fig = builder.create_dashboard()
        
        # Verify figure size (should be 12x10 inches)
        width, height = fig.get_size_inches()
        assert width == 12
        assert height == 10
        
        # Clean up
        plt.close(fig)


class TestDashboardIntegration:
    """Integration tests for complete dashboard workflow."""
    
    def test_complete_workflow(self, tmp_path):
        """Test complete workflow: init -> create -> save."""
        # Create realistic sample data
        df = pd.DataFrame({
            'symbol': ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 
                      'AAVE/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [1.8, 1.2, 0.5, -0.3, -0.8],
            'tier': ['A', 'A', 'A', 'B', 'B'],
            'funding_rate': [0.015, -0.008, 0.022, -0.012, 0.005],
            'long_short_ratio': [1.3, 1.7, 1.1, 0.9, 1.6]
        })
        
        # Initialize builder
        builder = DashboardBuilder(df)
        
        # Create dashboard
        fig = builder.create_dashboard()
        assert fig is not None
        
        # Save dashboard
        filepath = tmp_path / "complete_dashboard.png"
        builder.save_dashboard(str(filepath))
        assert filepath.exists()
        
        # Clean up
        plt.close(fig)
    
    def test_multiple_dashboards(self, tmp_path):
        """Test creating multiple dashboards with different data."""
        # Create first dashboard
        df1 = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
            'multi_factor_score': [1.5, 0.8],
            'tier': ['A', 'A'],
            'funding_rate': [0.01, -0.02],
            'long_short_ratio': [1.2, 1.8]
        })
        
        builder1 = DashboardBuilder(df1)
        fig1 = builder1.create_dashboard()
        filepath1 = tmp_path / "dashboard1.png"
        builder1.save_dashboard(str(filepath1))
        
        # Create second dashboard
        df2 = pd.DataFrame({
            'symbol': ['SOL/USDT:USDT', 'AAVE/USDT:USDT'],
            'multi_factor_score': [0.5, -0.3],
            'tier': ['A', 'B'],
            'funding_rate': [0.03, -0.01],
            'long_short_ratio': [1.1, 0.9]
        })
        
        builder2 = DashboardBuilder(df2)
        fig2 = builder2.create_dashboard()
        filepath2 = tmp_path / "dashboard2.png"
        builder2.save_dashboard(str(filepath2))
        
        # Verify both files exist
        assert filepath1.exists()
        assert filepath2.exists()
        
        # Clean up
        plt.close(fig1)
        plt.close(fig2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
