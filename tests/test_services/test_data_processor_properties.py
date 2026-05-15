"""Property-based tests for DataProcessor service.

Uses Hypothesis to verify universal correctness properties across
randomly generated inputs.

Feature: api-backend-transformation
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st, settings

from src.config.settings import Settings
from src.services.data_processor import DataProcessor


# Custom strategies for generating test data
@st.composite
def symbol_subset_strategy(draw):
    """Generate a random subset of symbols to fail (1-3 out of 5)."""
    all_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", 
                   "AAVE/USDT:USDT", "LINK/USDT:USDT"]
    num_failures = draw(st.integers(min_value=1, max_value=3))
    failed_symbols = draw(st.lists(
        st.sampled_from(all_symbols),
        min_size=num_failures,
        max_size=num_failures,
        unique=True
    ))
    return all_symbols, failed_symbols


class TestProperty6PartialFailureIsolation:
    """Property 6: Partial Failure Isolation
    
    **Validates: Requirements 7.1, 7.2**
    
    For any subset of symbols that fail during data fetching, the DataProcessor
    SHALL still return valid processed data for all remaining symbols, and the
    ResponseBuilder SHALL set all metric fields to null for the failed symbols
    while preserving correct values for successful symbols.
    """

    @pytest.mark.asyncio
    @settings(max_examples=30, deadline=None)
    @given(data=symbol_subset_strategy())
    async def test_partial_failure_returns_valid_data_for_successful_symbols(self, data):
        """When some symbols fail, successful symbols should have valid data."""
        all_symbols, failed_symbols = data
        successful_symbols = [s for s in all_symbols if s not in failed_symbols]
        
        # Create settings with all symbols
        settings_obj = Settings(
            mock_mode=False,
            symbols=",".join(all_symbols)
        )
        
        dp = DataProcessor(settings_obj)
        
        # Mock _fetch_with_error_isolation to fail for specific symbols
        async def mock_fetch(fetcher, symbol):
            if symbol in failed_symbols:
                # Simulate failure
                return (None, {"symbol": symbol, "error": "Simulated fetch failure"})
            else:
                # Simulate success with valid data
                return ({
                    "symbol": symbol,
                    "price": 50000.0,
                    "change_24h": 2.5,
                    "funding_rate": 0.01,
                    "long_short_ratio": 1.5,
                    "momentum_30d": 10.0,
                    "atr_percent": 3.5,
                    "distance_to_ma50": 5.0,
                    "sparkline_data": [1, 2, 3],
                    "sparkline_trend": "bullish",
                    "oi_delta_percent": 2.0,
                    "oi_interpretation": "bullish",
                }, None)
        
        # Mock the exchange connector and related components
        with patch("src.exchange.connector.ExchangeConnector") as MockConnector, \
             patch("src.data.fetcher.MarketDataFetcher"), \
             patch("src.signals.generator.SignalGenerator") as MockSignalGen, \
             patch("src.signals.ic_weights.ICWeightCalculator"), \
             patch("src.signals.scorer.MultiFactorScorer") as MockScorer, \
             patch("src.ranking.engine.RankingEngine") as MockRanker, \
             patch.object(dp, "_fetch_with_error_isolation", side_effect=mock_fetch):
            
            # Setup mock connector
            mock_conn_instance = MagicMock()
            mock_conn_instance.exchange = MagicMock()
            mock_conn_instance.exchange.close = MagicMock()
            mock_conn_instance.get_exchange.return_value = MagicMock()
            mock_conn_instance.connect = MagicMock(return_value=True)
            MockConnector.return_value = mock_conn_instance
            
            # Setup mock signal generator
            mock_signal_gen = MagicMock()
            mock_signal_gen.calculate_reversal_signal.return_value = pd.Series([0.5] * len(successful_symbols))
            mock_signal_gen.calculate_momentum_signal.return_value = pd.Series([0.3] * len(successful_symbols))
            mock_signal_gen.normalize_signal.side_effect = lambda x: x
            MockSignalGen.return_value = mock_signal_gen
            
            # Setup mock scorer
            mock_scorer = MagicMock()
            mock_scorer.calculate_score.return_value = pd.Series([0.7] * len(successful_symbols))
            mock_scorer.classify_tiers.return_value = pd.Series(["A"] * len(successful_symbols))
            MockScorer.return_value = mock_scorer
            mock_scorer.calculate_risk_adjusted_score.side_effect = lambda df: df
            mock_scorer.calculate_position_sizing.side_effect = lambda df: df
            
            # Setup mock ranker
            mock_ranker = MagicMock()
            def mock_rank(df, sort_by=None):
                df["rank"] = range(1, len(df) + 1)
                return df
            mock_ranker.rank_assets.side_effect = mock_rank
            MockRanker.return_value = mock_ranker
            
            # Execute the pipeline
            result = await dp.process_all()
        
        # Verify: successful symbols should have valid data
        assert len(result.data) == len(successful_symbols), \
            f"Expected {len(successful_symbols)} successful symbols, got {len(result.data)}"
        
        # Verify: all successful symbols are in the result
        result_symbols = set(result.data["symbol"].tolist())
        expected_symbols = set(successful_symbols)
        assert result_symbols == expected_symbols, \
            f"Expected symbols {expected_symbols}, got {result_symbols}"
        
        # Verify: successful symbols have non-NaN values for key metrics
        for _, row in result.data.iterrows():
            assert row["symbol"] in successful_symbols
            assert not pd.isna(row["price"]), f"Price should not be NaN for {row['symbol']}"
            assert not pd.isna(row["change_24h"]), f"change_24h should not be NaN for {row['symbol']}"
            assert not pd.isna(row["funding_rate"]), f"funding_rate should not be NaN for {row['symbol']}"
        
        # Verify: errors list contains all failed symbols
        assert len(result.errors) == len(failed_symbols), \
            f"Expected {len(failed_symbols)} errors, got {len(result.errors)}"
        
        error_symbols = {err["symbol"] for err in result.errors}
        assert error_symbols == set(failed_symbols), \
            f"Expected errors for {set(failed_symbols)}, got {error_symbols}"

    @pytest.mark.asyncio
    @settings(max_examples=30, deadline=None)
    @given(data=symbol_subset_strategy())
    async def test_failed_symbols_are_in_errors_list(self, data):
        """Failed symbols should appear in the errors list."""
        all_symbols, failed_symbols = data
        
        settings_obj = Settings(
            mock_mode=False,
            symbols=",".join(all_symbols)
        )
        
        dp = DataProcessor(settings_obj)
        
        # Mock _fetch_with_error_isolation to fail for specific symbols
        async def mock_fetch(fetcher, symbol):
            if symbol in failed_symbols:
                return (None, {"symbol": symbol, "error": f"Failed to fetch {symbol}"})
            else:
                return ({
                    "symbol": symbol,
                    "price": 50000.0,
                    "change_24h": 2.5,
                    "funding_rate": 0.01,
                    "long_short_ratio": 1.5,
                    "momentum_30d": 10.0,
                    "atr_percent": 3.5,
                    "distance_to_ma50": 5.0,
                    "sparkline_data": [1, 2, 3],
                    "sparkline_trend": "bullish",
                    "oi_delta_percent": 2.0,
                    "oi_interpretation": "bullish",
                }, None)
        
        with patch("src.exchange.connector.ExchangeConnector") as MockConnector, \
             patch("src.data.fetcher.MarketDataFetcher"), \
             patch("src.signals.generator.SignalGenerator") as MockSignalGen, \
             patch("src.signals.ic_weights.ICWeightCalculator"), \
             patch("src.signals.scorer.MultiFactorScorer") as MockScorer, \
             patch("src.ranking.engine.RankingEngine") as MockRanker, \
             patch.object(dp, "_fetch_with_error_isolation", side_effect=mock_fetch):
            
            # Setup mocks (same as above)
            mock_conn_instance = MagicMock()
            mock_conn_instance.exchange = MagicMock()
            mock_conn_instance.exchange.close = MagicMock()
            mock_conn_instance.get_exchange.return_value = MagicMock()
            mock_conn_instance.connect = MagicMock(return_value=True)
            MockConnector.return_value = mock_conn_instance
            
            successful_symbols = [s for s in all_symbols if s not in failed_symbols]
            
            mock_signal_gen = MagicMock()
            mock_signal_gen.calculate_reversal_signal.return_value = pd.Series([0.5] * len(successful_symbols))
            mock_signal_gen.calculate_momentum_signal.return_value = pd.Series([0.3] * len(successful_symbols))
            mock_signal_gen.normalize_signal.side_effect = lambda x: x
            MockSignalGen.return_value = mock_signal_gen
            
            mock_scorer = MagicMock()
            mock_scorer.calculate_score.return_value = pd.Series([0.7] * len(successful_symbols))
            mock_scorer.classify_tiers.return_value = pd.Series(["A"] * len(successful_symbols))
            MockScorer.return_value = mock_scorer
            mock_scorer.calculate_risk_adjusted_score.side_effect = lambda df: df
            mock_scorer.calculate_position_sizing.side_effect = lambda df: df
            
            mock_ranker = MagicMock()
            def mock_rank(df, sort_by=None):
                df["rank"] = range(1, len(df) + 1)
                return df
            mock_ranker.rank_assets.side_effect = mock_rank
            MockRanker.return_value = mock_ranker
            
            result = await dp.process_all()
        
        # Verify: each failed symbol has an error entry
        error_symbols = [err["symbol"] for err in result.errors]
        for failed_symbol in failed_symbols:
            assert failed_symbol in error_symbols, \
                f"Failed symbol {failed_symbol} should be in errors list"
        
        # Verify: each error has the expected structure
        for error in result.errors:
            assert "symbol" in error, "Error should have 'symbol' field"
            assert "error" in error, "Error should have 'error' field"
            assert error["symbol"] in failed_symbols, \
                f"Error symbol {error['symbol']} should be in failed_symbols"

    @pytest.mark.asyncio
    @settings(max_examples=30, deadline=None)
    @given(data=symbol_subset_strategy())
    async def test_pipeline_completes_despite_partial_failures(self, data):
        """Pipeline should complete successfully even when some symbols fail."""
        all_symbols, failed_symbols = data
        
        settings_obj = Settings(
            mock_mode=False,
            symbols=",".join(all_symbols)
        )
        
        dp = DataProcessor(settings_obj)
        
        async def mock_fetch(fetcher, symbol):
            if symbol in failed_symbols:
                return (None, {"symbol": symbol, "error": "Fetch failed"})
            else:
                return ({
                    "symbol": symbol,
                    "price": 50000.0,
                    "change_24h": 2.5,
                    "funding_rate": 0.01,
                    "long_short_ratio": 1.5,
                    "momentum_30d": 10.0,
                    "atr_percent": 3.5,
                    "distance_to_ma50": 5.0,
                    "sparkline_data": [1, 2, 3],
                    "sparkline_trend": "bullish",
                    "oi_delta_percent": 2.0,
                    "oi_interpretation": "bullish",
                }, None)
        
        with patch("src.exchange.connector.ExchangeConnector") as MockConnector, \
             patch("src.data.fetcher.MarketDataFetcher"), \
             patch("src.signals.generator.SignalGenerator") as MockSignalGen, \
             patch("src.signals.ic_weights.ICWeightCalculator"), \
             patch("src.signals.scorer.MultiFactorScorer") as MockScorer, \
             patch("src.ranking.engine.RankingEngine") as MockRanker, \
             patch.object(dp, "_fetch_with_error_isolation", side_effect=mock_fetch):
            
            mock_conn_instance = MagicMock()
            mock_conn_instance.exchange = MagicMock()
            mock_conn_instance.exchange.close = MagicMock()
            mock_conn_instance.get_exchange.return_value = MagicMock()
            mock_conn_instance.connect = MagicMock(return_value=True)
            MockConnector.return_value = mock_conn_instance
            
            successful_symbols = [s for s in all_symbols if s not in failed_symbols]
            
            mock_signal_gen = MagicMock()
            mock_signal_gen.calculate_reversal_signal.return_value = pd.Series([0.5] * len(successful_symbols))
            mock_signal_gen.calculate_momentum_signal.return_value = pd.Series([0.3] * len(successful_symbols))
            mock_signal_gen.normalize_signal.side_effect = lambda x: x
            MockSignalGen.return_value = mock_signal_gen
            
            mock_scorer = MagicMock()
            mock_scorer.calculate_score.return_value = pd.Series([0.7] * len(successful_symbols))
            mock_scorer.classify_tiers.return_value = pd.Series(["A"] * len(successful_symbols))
            MockScorer.return_value = mock_scorer
            mock_scorer.calculate_risk_adjusted_score.side_effect = lambda df: df
            mock_scorer.calculate_position_sizing.side_effect = lambda df: df
            
            mock_ranker = MagicMock()
            def mock_rank(df, sort_by=None):
                df["rank"] = range(1, len(df) + 1)
                return df
            mock_ranker.rank_assets.side_effect = mock_rank
            MockRanker.return_value = mock_ranker
            
            # This should not raise an exception
            result = await dp.process_all()
        
        # Verify: result is returned (pipeline completed)
        assert result is not None, "Pipeline should return a result"
        
        # Verify: result has data for successful symbols
        assert len(result.data) > 0, "Result should have data for successful symbols"
        
        # Verify: result has errors for failed symbols
        assert len(result.errors) == len(failed_symbols), \
            f"Expected {len(failed_symbols)} errors"
        
        # Verify: no exceptions were raised (implicit - test passes)

    @pytest.mark.asyncio
    @settings(max_examples=30, deadline=None)
    @given(data=symbol_subset_strategy())
    async def test_successful_symbols_have_non_nan_metrics(self, data):
        """Successful symbols should have valid (non-NaN) metric values."""
        all_symbols, failed_symbols = data
        successful_symbols = [s for s in all_symbols if s not in failed_symbols]
        
        settings_obj = Settings(
            mock_mode=False,
            symbols=",".join(all_symbols)
        )
        
        dp = DataProcessor(settings_obj)
        
        async def mock_fetch(fetcher, symbol):
            if symbol in failed_symbols:
                return (None, {"symbol": symbol, "error": "Fetch failed"})
            else:
                return ({
                    "symbol": symbol,
                    "price": 50000.0,
                    "change_24h": 2.5,
                    "funding_rate": 0.01,
                    "long_short_ratio": 1.5,
                    "momentum_30d": 10.0,
                    "atr_percent": 3.5,
                    "distance_to_ma50": 5.0,
                    "sparkline_data": [1, 2, 3],
                    "sparkline_trend": "bullish",
                    "oi_delta_percent": 2.0,
                    "oi_interpretation": "bullish",
                }, None)
        
        with patch("src.exchange.connector.ExchangeConnector") as MockConnector, \
             patch("src.data.fetcher.MarketDataFetcher"), \
             patch("src.signals.generator.SignalGenerator") as MockSignalGen, \
             patch("src.signals.ic_weights.ICWeightCalculator"), \
             patch("src.signals.scorer.MultiFactorScorer") as MockScorer, \
             patch("src.ranking.engine.RankingEngine") as MockRanker, \
             patch.object(dp, "_fetch_with_error_isolation", side_effect=mock_fetch):
            
            mock_conn_instance = MagicMock()
            mock_conn_instance.exchange = MagicMock()
            mock_conn_instance.exchange.close = MagicMock()
            mock_conn_instance.get_exchange.return_value = MagicMock()
            mock_conn_instance.connect = MagicMock(return_value=True)
            MockConnector.return_value = mock_conn_instance
            
            mock_signal_gen = MagicMock()
            mock_signal_gen.calculate_reversal_signal.return_value = pd.Series([0.5] * len(successful_symbols))
            mock_signal_gen.calculate_momentum_signal.return_value = pd.Series([0.3] * len(successful_symbols))
            mock_signal_gen.normalize_signal.side_effect = lambda x: x
            MockSignalGen.return_value = mock_signal_gen
            
            mock_scorer = MagicMock()
            mock_scorer.calculate_score.return_value = pd.Series([0.7] * len(successful_symbols))
            mock_scorer.classify_tiers.return_value = pd.Series(["A"] * len(successful_symbols))
            MockScorer.return_value = mock_scorer
            mock_scorer.calculate_risk_adjusted_score.side_effect = lambda df: df
            mock_scorer.calculate_position_sizing.side_effect = lambda df: df
            
            mock_ranker = MagicMock()
            def mock_rank(df, sort_by=None):
                df["rank"] = range(1, len(df) + 1)
                return df
            mock_ranker.rank_assets.side_effect = mock_rank
            MockRanker.return_value = mock_ranker
            
            result = await dp.process_all()
        
        # Verify: all successful symbols have valid metric values
        for _, row in result.data.iterrows():
            # Check key metrics are not NaN
            assert not pd.isna(row["price"]), \
                f"Price should not be NaN for successful symbol {row['symbol']}"
            assert not pd.isna(row["change_24h"]), \
                f"change_24h should not be NaN for successful symbol {row['symbol']}"
            assert not pd.isna(row["funding_rate"]), \
                f"funding_rate should not be NaN for successful symbol {row['symbol']}"
            assert not pd.isna(row["long_short_ratio"]), \
                f"long_short_ratio should not be NaN for successful symbol {row['symbol']}"
            assert not pd.isna(row["momentum_30d"]), \
                f"momentum_30d should not be NaN for successful symbol {row['symbol']}"
            
            # Check that values are reasonable (not infinity)
            assert np.isfinite(row["price"]), \
                f"Price should be finite for {row['symbol']}"
            assert np.isfinite(row["change_24h"]), \
                f"change_24h should be finite for {row['symbol']}"
