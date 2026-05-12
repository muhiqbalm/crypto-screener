"""
Integration tests for Phase 2 pipeline (5-panel and 7-panel dashboards).

Tests cover:
- Full pipeline with Phase 2a metrics (5-panel dashboard)
- Full pipeline with Phase 2b metrics (7-panel dashboard)
- Graceful degradation when API fails
- Dashboard output file generation
"""

import pytest
import pandas as pd
import numpy as np
import os
from unittest.mock import Mock, patch, MagicMock
from src.data.fetcher import MarketDataFetcher
from src.visualization.dashboard import DashboardBuilder
from src.scoring.multi_factor import MultiFactorScorer
from src.scoring.ic_weight import ICWeightCalculator
from src.ranking.engine import RankingEngine


class TestPhase2aPipeline:
    """Integration tests for Phase 2a (5-panel dashboard)."""
    
    @pytest.fixture
    def mock_exchange(self):
        """Create mock exchange with Phase 2a data."""
        exchange = Mock()
        
        # Mock ticker data
        exchange.fetch_ticker.return_value = {
            'last': 50000,
            'percentage': 5.0
        }
        
        # Mock funding rate
        exchange.fetch_funding_rate.return_value = 0.01
        
        # Mock long/short ratio
        exchange.fetch.return_value = {'longShortRatio': 1.2}
        
        # Mock OHLCV data for momentum, ATR, and MA50
        exchange.fetch_ohlcv.return_value = [
            [1000000 + i*86400000, 50000 + i*100, 50100 + i*100, 49900 + i*100, 50050 + i*100, 1000]
            for i in range(60)  # 60 days of data
        ]
        
        return exchange
    
    def test_full_pipeline_phase2a(self, mock_exchange, tmp_path):
        """Test complete pipeline with Phase 2a metrics (5 panels)."""
        # Create fetcher
        symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=mock_exchange, symbols=symbols)
        
        # Fetch all data
        market_data_df = fetcher.fetch_all_data()
        
        # Verify Phase 2a columns exist
        assert 'atr_percent' in market_data_df.columns
        assert 'distance_to_ma50' in market_data_df.columns
        
        # Verify data was fetched
        assert len(market_data_df) == len(symbols)
        assert market_data_df['price'].notna().sum() > 0
        
        # Add mock signals for scoring
        market_data_df['reversal_signal'] = [0.5, 0.3]
        market_data_df['momentum_signal'] = [0.6, 0.4]
        
        # Calculate scores
        ic_calculator = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calculator=ic_calculator)
        market_data_df['multi_factor_score'] = scorer.calculate_score(market_data_df)
        market_data_df['tier'] = scorer.classify_tiers(market_data_df['multi_factor_score'])
        
        # Rank assets
        ranking_engine = RankingEngine()
        ranked_df = ranking_engine.rank_assets(market_data_df)
        
        # Create dashboard
        dashboard_builder = DashboardBuilder(df=ranked_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify figure was created
        assert figure is not None
        
        # Verify 5 subplots (axes)
        assert len(figure.axes) == 5
        
        # Save dashboard
        output_path = tmp_path / "test_phase2a_dashboard.png"
        dashboard_builder.save_dashboard(str(output_path))
        
        # Verify file was created
        assert output_path.exists()
        assert output_path.stat().st_size > 0
    
    def test_phase2a_with_missing_atr(self, mock_exchange, tmp_path):
        """Test pipeline when ATR calculation fails."""
        symbols = ['BTC/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=mock_exchange, symbols=symbols)
        
        # Mock ATR calculation failure
        with patch.object(fetcher, 'calculate_atr', side_effect=Exception("ATR calculation failed")):
            market_data_df = fetcher.fetch_all_data()
        
        # Verify ATR is NaN but pipeline continues
        assert pd.isna(market_data_df['atr_percent'].iloc[0])
        
        # Add required columns for dashboard
        market_data_df['multi_factor_score'] = [0.5]
        market_data_df['tier'] = ['A']
        market_data_df['rank'] = [1]
        
        # Create dashboard (should handle missing ATR gracefully)
        dashboard_builder = DashboardBuilder(df=market_data_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify dashboard was created despite missing ATR
        assert figure is not None
    
    def test_phase2a_with_missing_ma50(self, mock_exchange, tmp_path):
        """Test pipeline when MA50 calculation fails."""
        symbols = ['BTC/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=mock_exchange, symbols=symbols)
        
        # Mock MA50 calculation failure
        with patch.object(fetcher, 'calculate_distance_to_ma50', side_effect=Exception("MA50 calculation failed")):
            market_data_df = fetcher.fetch_all_data()
        
        # Verify MA50 is NaN but pipeline continues
        assert pd.isna(market_data_df['distance_to_ma50'].iloc[0])
        
        # Add required columns for dashboard
        market_data_df['multi_factor_score'] = [0.5]
        market_data_df['tier'] = ['A']
        market_data_df['rank'] = [1]
        
        # Create dashboard (should handle missing MA50 gracefully)
        dashboard_builder = DashboardBuilder(df=market_data_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify dashboard was created despite missing MA50
        assert figure is not None


class TestPhase2bPipeline:
    """Integration tests for Phase 2b (7-panel dashboard)."""
    
    @pytest.fixture
    def mock_exchange_phase2b(self):
        """Create mock exchange with Phase 2b data."""
        exchange = Mock()
        
        # Mock ticker data
        exchange.fetch_ticker.return_value = {
            'last': 50000,
            'percentage': 5.0
        }
        
        # Mock funding rate
        exchange.fetch_funding_rate.return_value = 0.01
        
        # Mock long/short ratio
        def mock_fetch(endpoint, params=None):
            if 'longShortRatio' in endpoint or params and 'longShortRatio' in str(params):
                return {'longShortRatio': 1.2}
            elif 'openInterest' in endpoint:
                return {'openInterest': 120000, 'symbol': 'BTCUSDT'}
            elif 'openInterestHist' in endpoint:
                return [{'sumOpenInterest': 100000, 'timestamp': 1000000}]
            return {}
        
        exchange.fetch = Mock(side_effect=mock_fetch)
        
        # Mock OHLCV data for all metrics
        def mock_ohlcv(symbol, timeframe='1d', limit=30):
            if timeframe == '1h':
                # Hourly data for sparkline
                return [
                    [1000000 + i*3600000, 50000 + i*100, 50100 + i*100, 49900 + i*100, 50050 + i*100, 1000]
                    for i in range(24)
                ]
            else:
                # Daily data for other metrics
                return [
                    [1000000 + i*86400000, 50000 + i*100, 50100 + i*100, 49900 + i*100, 50050 + i*100, 1000]
                    for i in range(60)
                ]
        
        exchange.fetch_ohlcv = Mock(side_effect=mock_ohlcv)
        
        return exchange
    
    def test_full_pipeline_phase2b(self, mock_exchange_phase2b, tmp_path):
        """Test complete pipeline with Phase 2b metrics (7 panels)."""
        # Create fetcher
        symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=mock_exchange_phase2b, symbols=symbols)
        
        # Fetch all data
        market_data_df = fetcher.fetch_all_data()
        
        # Verify Phase 2b columns exist
        assert 'sparkline_data' in market_data_df.columns
        assert 'sparkline_trend' in market_data_df.columns
        assert 'oi_delta_percent' in market_data_df.columns
        assert 'oi_interpretation' in market_data_df.columns
        
        # Verify data was fetched
        assert len(market_data_df) == len(symbols)
        
        # Add mock signals for scoring
        market_data_df['reversal_signal'] = [0.5, 0.3]
        market_data_df['momentum_signal'] = [0.6, 0.4]
        
        # Calculate scores
        ic_calculator = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calculator=ic_calculator)
        market_data_df['multi_factor_score'] = scorer.calculate_score(market_data_df)
        market_data_df['tier'] = scorer.classify_tiers(market_data_df['multi_factor_score'])
        
        # Rank assets
        ranking_engine = RankingEngine()
        ranked_df = ranking_engine.rank_assets(market_data_df)
        
        # Create dashboard
        dashboard_builder = DashboardBuilder(df=ranked_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify figure was created
        assert figure is not None
        
        # Verify 7 subplots (axes)
        assert len(figure.axes) == 7
        
        # Save dashboard
        output_path = tmp_path / "test_phase2b_dashboard.png"
        dashboard_builder.save_dashboard(str(output_path))
        
        # Verify file was created
        assert output_path.exists()
        assert output_path.stat().st_size > 0
    
    def test_phase2b_with_missing_sparkline(self, mock_exchange_phase2b, tmp_path):
        """Test pipeline when sparkline fetch fails."""
        symbols = ['BTC/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=mock_exchange_phase2b, symbols=symbols)
        
        # Mock sparkline fetch failure
        with patch.object(fetcher, 'fetch_sparkline_data', side_effect=Exception("Sparkline fetch failed")):
            market_data_df = fetcher.fetch_all_data()
        
        # Verify sparkline is None but pipeline continues
        assert market_data_df['sparkline_data'].iloc[0] is None
        
        # Add required columns for dashboard
        market_data_df['multi_factor_score'] = [0.5]
        market_data_df['tier'] = ['A']
        market_data_df['rank'] = [1]
        
        # Create dashboard (should handle missing sparkline gracefully)
        dashboard_builder = DashboardBuilder(df=market_data_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify dashboard was created despite missing sparkline
        assert figure is not None
        assert len(figure.axes) == 7
    
    def test_phase2b_with_missing_oi_delta(self, mock_exchange_phase2b, tmp_path):
        """Test pipeline when OI delta calculation fails."""
        symbols = ['BTC/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=mock_exchange_phase2b, symbols=symbols)
        
        # Mock OI delta calculation failure
        with patch.object(fetcher, 'calculate_oi_delta', side_effect=Exception("OI delta calculation failed")):
            market_data_df = fetcher.fetch_all_data()
        
        # Verify OI delta is NaN but pipeline continues
        assert pd.isna(market_data_df['oi_delta_percent'].iloc[0])
        
        # Add required columns for dashboard
        market_data_df['multi_factor_score'] = [0.5]
        market_data_df['tier'] = ['A']
        market_data_df['rank'] = [1]
        
        # Create dashboard (should handle missing OI delta gracefully)
        dashboard_builder = DashboardBuilder(df=market_data_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify dashboard was created despite missing OI delta
        assert figure is not None
        assert len(figure.axes) == 7


class TestGracefulDegradation:
    """Test graceful degradation when APIs fail."""
    
    def test_all_phase2_metrics_fail(self, tmp_path):
        """Test pipeline when all Phase 2 metrics fail."""
        # Create mock exchange that fails for Phase 2 metrics
        exchange = Mock()
        exchange.fetch_ticker.return_value = {'last': 50000, 'percentage': 5.0}
        exchange.fetch_funding_rate.return_value = 0.01
        exchange.fetch.return_value = {'longShortRatio': 1.2}
        exchange.fetch_ohlcv.side_effect = Exception("OHLCV fetch failed")
        
        symbols = ['BTC/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=exchange, symbols=symbols)
        
        # Fetch data (Phase 2 metrics will fail)
        market_data_df = fetcher.fetch_all_data()
        
        # Verify core data exists but Phase 2 metrics are missing
        assert market_data_df['price'].notna().iloc[0]
        assert pd.isna(market_data_df['atr_percent'].iloc[0])
        assert pd.isna(market_data_df['distance_to_ma50'].iloc[0])
        
        # Add required columns for dashboard
        market_data_df['multi_factor_score'] = [0.5]
        market_data_df['tier'] = ['A']
        market_data_df['rank'] = [1]
        
        # Create dashboard (should show placeholders for Phase 2 panels)
        dashboard_builder = DashboardBuilder(df=market_data_df)
        figure = dashboard_builder.create_dashboard()
        
        # Verify dashboard was created with placeholders
        assert figure is not None
        assert len(figure.axes) == 7
    
    def test_partial_symbol_failure(self, tmp_path):
        """Test pipeline when some symbols fail to fetch."""
        exchange = Mock()
        
        # Mock different responses for different symbols
        call_count = [0]
        
        def mock_ticker(symbol):
            call_count[0] += 1
            if call_count[0] == 1:
                return {'last': 50000, 'percentage': 5.0}
            else:
                raise Exception("Symbol not found")
        
        exchange.fetch_ticker = Mock(side_effect=mock_ticker)
        exchange.fetch_funding_rate.return_value = 0.01
        exchange.fetch.return_value = {'longShortRatio': 1.2}
        exchange.fetch_ohlcv.return_value = [
            [1000000 + i*86400000, 50000, 50100, 49900, 50050, 1000]
            for i in range(60)
        ]
        
        symbols = ['BTC/USDT:USDT', 'INVALID/USDT:USDT']
        fetcher = MarketDataFetcher(exchange=exchange, symbols=symbols)
        
        # Fetch data (second symbol will fail)
        market_data_df = fetcher.fetch_all_data()
        
        # Verify partial success
        assert len(market_data_df) == 2
        assert market_data_df['price'].notna().sum() == 1  # Only first symbol succeeded
        assert pd.isna(market_data_df['price'].iloc[1])  # Second symbol failed


class TestDashboardOutputGeneration:
    """Test dashboard file generation."""
    
    def test_dashboard_file_formats(self, tmp_path):
        """Test dashboard can be saved in different formats."""
        # Create minimal DataFrame
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT'],
            'multi_factor_score': [0.5],
            'tier': ['A'],
            'funding_rate': [0.01],
            'long_short_ratio': [1.2],
            'atr_percent': [5.0],
            'distance_to_ma50': [2.5],
            'sparkline_data': [[50000 + i*100 for i in range(24)]],
            'sparkline_trend': ['uptrend'],
            'oi_delta_percent': [10.0]
        })
        
        dashboard_builder = DashboardBuilder(df=df)
        figure = dashboard_builder.create_dashboard()
        
        # Test PNG format
        png_path = tmp_path / "dashboard.png"
        dashboard_builder.save_dashboard(str(png_path))
        assert png_path.exists()
        
        # Test PDF format
        pdf_path = tmp_path / "dashboard.pdf"
        dashboard_builder.save_dashboard(str(pdf_path))
        assert pdf_path.exists()
    
    def test_dashboard_file_size(self, tmp_path):
        """Test dashboard file has reasonable size."""
        # Create DataFrame with multiple assets
        df = pd.DataFrame({
            'symbol': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
            'multi_factor_score': [0.8, 0.6, 0.4],
            'tier': ['A', 'A', 'B'],
            'funding_rate': [0.01, 0.02, -0.01],
            'long_short_ratio': [1.2, 1.5, 0.9],
            'atr_percent': [5.0, 6.5, 4.2],
            'distance_to_ma50': [2.5, -1.3, 3.8],
            'sparkline_data': [
                [50000 + i*100 for i in range(24)],
                [3000 - i*10 for i in range(24)],
                [150 for _ in range(24)]
            ],
            'sparkline_trend': ['uptrend', 'downtrend', 'neutral'],
            'oi_delta_percent': [10.0, -5.0, 0.5]
        })
        
        dashboard_builder = DashboardBuilder(df=df)
        figure = dashboard_builder.create_dashboard()
        
        output_path = tmp_path / "dashboard.png"
        dashboard_builder.save_dashboard(str(output_path))
        
        # Verify file size is reasonable (> 10KB, < 5MB)
        file_size = output_path.stat().st_size
        assert file_size > 10000  # > 10KB
        assert file_size < 5000000  # < 5MB


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
