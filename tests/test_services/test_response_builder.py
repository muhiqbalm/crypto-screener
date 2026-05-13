"""Unit tests for the ResponseBuilder service.

Tests cover:
- build_full_response: metadata, summary, and assets construction
- build_summary_only: omits assets array
- build_asset_detail: single asset response
- _sanitize_value: NaN/None to null, numeric precision
- Market overview aggregation logic
- Top 3 assets extraction
- Stale data warning threshold
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.api.models import (
    AssetDetail,
    AssetDetailResponse,
    AssetSummary,
    MarketOverview,
    ResponseMetadata,
    ScreenerResponse,
    SummaryData,
)
from src.services.response_builder import ResponseBuilder


@pytest.fixture
def builder():
    """Create a ResponseBuilder instance."""
    return ResponseBuilder()


@pytest.fixture
def sample_df():
    """Create a sample DataFrame with typical screener data."""
    return pd.DataFrame(
        {
            "symbol": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "DOGE/USDT:USDT"],
            "rank": [1, 2, 3, 4],
            "multi_factor_score": [0.85, 0.72, 0.05, -0.65],  # Used for composite_score and signal derivation
            "reversal_signal": [1.5, -0.5, 0.2, -1.8],  # Used for RSI calculation
            "momentum_signal": [0.8, 0.6, 0.1, -0.9],  # Used for MACD signal derivation
            "price": [67500.50, 3450.25, 145.80, 0.1234],
            "change_24h": [2.5, -1.2, 5.3, -3.1],
            "volume_24h": [1500000000.0, 800000000.0, 300000000.0, 150000000.0],
            "funding_rate": [0.0001, 0.0002, -0.0001, 0.0003],
            "open_interest": [25000000000.0, 12000000000.0, 5000000000.0, 2000000000.0],
            "long_short_ratio": [1.25, 0.98, 1.10, 0.85],
            "atr_percent": [0.025, 0.035, 0.045, 0.055],  # Maps to volatility
        }
    )


@pytest.fixture
def df_with_nans():
    """Create a DataFrame with NaN values in various columns."""
    return pd.DataFrame(
        {
            "symbol": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
            "rank": [1, 2],
            "multi_factor_score": [0.85, float("nan")],
            "reversal_signal": [1.5, float("nan")],
            "momentum_signal": [0.8, float("nan")],
            "price": [67500.50, float("nan")],
            "change_24h": [2.5, float("nan")],
            "volume_24h": [1500000000.0, float("nan")],
            "funding_rate": [0.0001, float("nan")],
            "open_interest": [25000000000.0, None],
            "long_short_ratio": [1.25, float("nan")],
            "atr_percent": [0.025, float("nan")],
        }
    )


class TestSanitizeValue:
    """Tests for _sanitize_value method."""

    def test_none_returns_none(self, builder):
        assert builder._sanitize_value(None) is None

    def test_nan_returns_none(self, builder):
        assert builder._sanitize_value(float("nan")) is None

    def test_inf_returns_none(self, builder):
        assert builder._sanitize_value(float("inf")) is None

    def test_negative_inf_returns_none(self, builder):
        assert builder._sanitize_value(float("-inf")) is None

    def test_numpy_nan_returns_none(self, builder):
        assert builder._sanitize_value(np.nan) is None

    def test_normal_float_rounds_to_2_decimals(self, builder):
        assert builder._sanitize_value(3.14159, decimals=2) == 3.14

    def test_normal_float_rounds_to_4_decimals(self, builder):
        assert builder._sanitize_value(0.000123456, decimals=4) == 0.0001

    def test_integer_value(self, builder):
        assert builder._sanitize_value(42, decimals=2) == 42.0

    def test_zero_value(self, builder):
        assert builder._sanitize_value(0.0, decimals=2) == 0.0

    def test_negative_value(self, builder):
        assert builder._sanitize_value(-5.678, decimals=2) == -5.68

    def test_string_returns_none(self, builder):
        assert builder._sanitize_value("not_a_number") is None

    def test_large_number(self, builder):
        assert builder._sanitize_value(1500000000.123, decimals=2) == 1500000000.12


class TestSanitizeInt:
    """Tests for _sanitize_int method."""

    def test_none_returns_none(self, builder):
        assert builder._sanitize_int(None) is None

    def test_nan_returns_none(self, builder):
        assert builder._sanitize_int(float("nan")) is None

    def test_normal_int(self, builder):
        assert builder._sanitize_int(3) == 3

    def test_float_to_int(self, builder):
        assert builder._sanitize_int(3.0) == 3

    def test_string_returns_none(self, builder):
        assert builder._sanitize_int("abc") is None


class TestBuildMetadata:
    """Tests for _build_metadata method."""

    def test_basic_metadata(self, builder, sample_df):
        metadata = builder._build_metadata(sample_df, cache_hit=True, data_age_seconds=30.0, errors=None)

        assert isinstance(metadata, ResponseMetadata)
        assert metadata.cache_hit is True
        assert metadata.data_age_seconds == 30.0
        assert metadata.symbols_count == 4
        assert metadata.errors_count == 0
        assert metadata.stale_data_warning is None

    def test_stale_data_warning_above_300(self, builder, sample_df):
        metadata = builder._build_metadata(sample_df, cache_hit=True, data_age_seconds=301.0, errors=None)

        assert metadata.stale_data_warning is True

    def test_no_stale_warning_at_300(self, builder, sample_df):
        metadata = builder._build_metadata(sample_df, cache_hit=True, data_age_seconds=300.0, errors=None)

        assert metadata.stale_data_warning is None

    def test_errors_count(self, builder, sample_df):
        errors = [{"symbol": "XRP", "error": "timeout"}, {"symbol": "ADA", "error": "rate limit"}]
        metadata = builder._build_metadata(sample_df, cache_hit=False, data_age_seconds=5.0, errors=errors)

        assert metadata.errors_count == 2

    def test_timestamp_is_set(self, builder, sample_df):
        metadata = builder._build_metadata(sample_df, cache_hit=False, data_age_seconds=0.0, errors=None)

        assert metadata.timestamp is not None


class TestBuildMarketOverview:
    """Tests for _build_market_overview method."""

    def test_basic_aggregation(self, builder, sample_df):
        overview = builder._build_market_overview(sample_df)

        assert isinstance(overview, MarketOverview)
        # avg_change_24h: mean of [2.5, -1.2, 5.3, -3.1] = 0.875
        assert overview.avg_change_24h == pytest.approx(0.875, abs=0.001)
        # avg_funding_rate: mean of [0.0001, 0.0002, -0.0001, 0.0003] = 0.000125
        assert overview.avg_funding_rate == pytest.approx(0.0001, abs=0.0001)
        # total_volume: sum of all volumes
        assert overview.total_volume == pytest.approx(2750000000.0, abs=1.0)
        # Signal counts derived from multi_factor_score:
        # [0.85, 0.72, 0.05, -0.65] -> [BULLISH, BULLISH, NEUTRAL, BEARISH]
        assert overview.bullish_count == 2
        assert overview.bearish_count == 1
        assert overview.neutral_count == 1

    def test_all_nan_columns(self, builder):
        df = pd.DataFrame(
            {
                "symbol": ["A", "B"],
                "change_24h": [float("nan"), float("nan")],
                "funding_rate": [float("nan"), float("nan")],
                "volume_24h": [float("nan"), float("nan")],
                "multi_factor_score": [float("nan"), float("nan")],
            }
        )
        overview = builder._build_market_overview(df)

        assert overview.avg_change_24h is None
        assert overview.avg_funding_rate is None
        assert overview.total_volume is None
        assert overview.bullish_count == 0
        assert overview.bearish_count == 0
        assert overview.neutral_count == 0

    def test_missing_columns(self, builder):
        df = pd.DataFrame({"symbol": ["A", "B"]})
        overview = builder._build_market_overview(df)

        assert overview.avg_change_24h is None
        assert overview.avg_funding_rate is None
        assert overview.total_volume is None


class TestBuildTop3Assets:
    """Tests for _build_top_3_assets method."""

    def test_returns_top_3(self, builder, sample_df):
        top_3 = builder._build_top_3_assets(sample_df)

        assert len(top_3) == 3
        assert all(isinstance(a, AssetSummary) for a in top_3)
        assert top_3[0].symbol == "BTC/USDT:USDT"
        assert top_3[1].symbol == "ETH/USDT:USDT"
        assert top_3[2].symbol == "SOL/USDT:USDT"

    def test_fewer_than_3_rows(self, builder):
        df = pd.DataFrame(
            {
                "symbol": ["BTC/USDT:USDT"],
                "rank": [1],
                "multi_factor_score": [0.9],
            }
        )
        top_3 = builder._build_top_3_assets(df)

        assert len(top_3) == 1
        assert top_3[0].symbol == "BTC/USDT:USDT"
        assert top_3[0].rank == 1

    def test_empty_dataframe(self, builder):
        df = pd.DataFrame(columns=["symbol", "rank", "multi_factor_score"])
        top_3 = builder._build_top_3_assets(df)

        assert len(top_3) == 0


class TestBuildAsset:
    """Tests for _build_asset method."""

    def test_full_asset_detail(self, builder, sample_df):
        row = sample_df.iloc[0]
        asset = builder._build_asset(row)

        assert isinstance(asset, AssetDetail)
        assert asset.symbol == "BTC/USDT:USDT"
        assert asset.rank == 1
        assert asset.composite_score == 0.85
        assert asset.signal == "BULLISH"  # Derived from multi_factor_score > 0.5
        assert asset.price == 67500.50
        assert asset.change_24h == pytest.approx(2.5, abs=0.0001)
        # RSI calculated from reversal_signal: 50 + (1.5 * 10) = 65.0
        assert asset.rsi == pytest.approx(65.0, abs=0.1)
        # MACD signal derived from momentum_signal > 0.5: BUY
        assert asset.macd_signal == "BUY"

    def test_nan_values_become_none(self, builder, df_with_nans):
        row = df_with_nans.iloc[1]
        asset = builder._build_asset(row)

        assert asset.symbol == "ETH/USDT:USDT"
        assert asset.composite_score is None
        assert asset.signal is None
        assert asset.price is None
        assert asset.change_24h is None
        assert asset.funding_rate is None
        assert asset.rsi is None
        assert asset.macd_signal is None
        assert asset.volatility is None


class TestBuildFullResponse:
    """Tests for build_full_response method."""

    def test_returns_screener_response(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=True, data_age_seconds=15.0, errors=None)

        assert isinstance(response, ScreenerResponse)
        assert response.metadata is not None
        assert response.summary is not None
        assert response.assets is not None

    def test_assets_included(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=False, data_age_seconds=0.0)

        assert len(response.assets) == 4
        assert response.assets[0].symbol == "BTC/USDT:USDT"

    def test_metadata_populated(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=True, data_age_seconds=45.5)

        assert response.metadata.cache_hit is True
        assert response.metadata.data_age_seconds == 45.5
        assert response.metadata.symbols_count == 4

    def test_summary_has_top_3(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=False, data_age_seconds=0.0)

        assert len(response.summary.top_3_assets) == 3

    def test_summary_has_market_overview(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=False, data_age_seconds=0.0)

        assert response.summary.market_overview is not None
        assert response.summary.market_overview.bullish_count == 2


class TestBuildSummaryOnly:
    """Tests for build_summary_only method."""

    def test_assets_is_none(self, builder, sample_df):
        response = builder.build_summary_only(sample_df, cache_hit=True, data_age_seconds=10.0)

        assert isinstance(response, ScreenerResponse)
        assert response.assets is None

    def test_metadata_present(self, builder, sample_df):
        response = builder.build_summary_only(sample_df, cache_hit=False, data_age_seconds=5.0)

        assert response.metadata is not None
        assert response.metadata.symbols_count == 4

    def test_summary_present(self, builder, sample_df):
        response = builder.build_summary_only(sample_df, cache_hit=True, data_age_seconds=20.0)

        assert response.summary is not None
        assert len(response.summary.top_3_assets) == 3


class TestBuildAssetDetail:
    """Tests for build_asset_detail method."""

    def test_returns_asset_detail_response(self, builder, sample_df):
        response = builder.build_asset_detail(
            sample_df, symbol="BTC/USDT:USDT", cache_hit=True, data_age_seconds=10.0
        )

        assert isinstance(response, AssetDetailResponse)
        assert response.asset.symbol == "BTC/USDT:USDT"
        assert response.asset.rank == 1

    def test_symbol_not_found_raises(self, builder, sample_df):
        with pytest.raises(ValueError, match="Symbol INVALID not found"):
            builder.build_asset_detail(sample_df, symbol="INVALID", cache_hit=False, data_age_seconds=0.0)

    def test_metadata_populated(self, builder, sample_df):
        response = builder.build_asset_detail(
            sample_df, symbol="ETH/USDT:USDT", cache_hit=True, data_age_seconds=55.0
        )

        assert response.metadata.cache_hit is True
        assert response.metadata.data_age_seconds == 55.0


class TestStaleDataWarning:
    """Tests for stale data warning threshold."""

    def test_warning_at_301_seconds(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=True, data_age_seconds=301.0)

        assert response.metadata.stale_data_warning is True

    def test_no_warning_at_300_seconds(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=True, data_age_seconds=300.0)

        assert response.metadata.stale_data_warning is None

    def test_no_warning_at_0_seconds(self, builder, sample_df):
        response = builder.build_full_response(sample_df, cache_hit=False, data_age_seconds=0.0)

        assert response.metadata.stale_data_warning is None


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_dataframe(self, builder):
        df = pd.DataFrame(
            columns=[
                "symbol", "rank", "multi_factor_score", "reversal_signal", "momentum_signal", "price",
                "change_24h", "volume_24h", "funding_rate", "open_interest",
                "long_short_ratio", "atr_percent",
            ]
        )
        response = builder.build_full_response(df, cache_hit=False, data_age_seconds=0.0)

        assert response.metadata.symbols_count == 0
        assert response.assets == []
        assert response.summary.top_3_assets == []

    def test_single_row_dataframe(self, builder):
        df = pd.DataFrame(
            {
                "symbol": ["BTC/USDT:USDT"],
                "rank": [1],
                "multi_factor_score": [0.9],  # > 0.5 -> BULLISH
                "reversal_signal": [0.5],  # RSI = 50 + (0.5 * 10) = 55.0
                "momentum_signal": [0.8],  # > 0.5 -> BUY
                "price": [67000.0],
                "change_24h": [1.5],
                "volume_24h": [1000000000.0],
                "funding_rate": [0.0001],
                "open_interest": [20000000000.0],
                "long_short_ratio": [1.1],
                "atr_percent": [0.03],
            }
        )
        response = builder.build_full_response(df, cache_hit=False, data_age_seconds=0.0)

        assert len(response.assets) == 1
        assert len(response.summary.top_3_assets) == 1
        assert response.summary.market_overview.bullish_count == 1
