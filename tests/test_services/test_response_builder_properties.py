"""Property-based tests for ResponseBuilder service.

Uses Hypothesis to verify universal correctness properties across
randomly generated inputs.

Feature: api-backend-transformation
"""

import json
import math
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st

from src.services.response_builder import ResponseBuilder


# Custom strategies for generating test data
@st.composite
def valid_float_strategy(draw):
    """Generate valid float values including edge cases."""
    return draw(
        st.one_of(
            st.floats(
                min_value=-1e10,
                max_value=1e10,
                allow_nan=False,
                allow_infinity=False,
            ),
            st.just(0.0),
            st.just(-0.0),
            st.floats(min_value=1e-10, max_value=1e-6),  # Very small positive
            st.floats(min_value=-1e-6, max_value=-1e-10),  # Very small negative
        )
    )


@st.composite
def invalid_numeric_strategy(draw):
    """Generate invalid numeric values (NaN, Inf, None)."""
    return draw(
        st.one_of(
            st.just(float("nan")),
            st.just(np.nan),
            st.just(float("inf")),
            st.just(float("-inf")),
            st.just(np.inf),
            st.just(-np.inf),
            st.just(None),
        )
    )


@st.composite
def mixed_numeric_strategy(draw):
    """Generate mix of valid and invalid numeric values."""
    return draw(st.one_of(valid_float_strategy(), invalid_numeric_strategy()))


@st.composite
def dataframe_with_mixed_values(draw):
    """Generate DataFrame with mix of valid numbers, NaN, None, and Inf values."""
    num_rows = draw(st.integers(min_value=1, max_value=10))
    
    symbols = [f"SYM{i}/USDT:USDT" for i in range(num_rows)]
    ranks = list(range(1, num_rows + 1))
    
    # Generate mixed values for each numeric column
    composite_scores = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    prices = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    changes = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    volumes = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    funding_rates = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    open_interests = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    long_short_ratios = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    rsis = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    volatilities = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    ic_weights = [draw(mixed_numeric_strategy()) for _ in range(num_rows)]
    
    # Signal can be string or None
    signals = [draw(st.one_of(st.sampled_from(["BULLISH", "BEARISH", "NEUTRAL"]), st.none())) for _ in range(num_rows)]
    macd_signals = [draw(st.one_of(st.sampled_from(["BUY", "SELL", "HOLD"]), st.none())) for _ in range(num_rows)]
    
    return pd.DataFrame({
        "symbol": symbols,
        "rank": ranks,
        "composite_score": composite_scores,
        "signal": signals,
        "price": prices,
        "change_24h": changes,
        "volume_24h": volumes,
        "funding_rate": funding_rates,
        "open_interest": open_interests,
        "long_short_ratio": long_short_ratios,
        "rsi": rsis,
        "macd_signal": macd_signals,
        "volatility": volatilities,
        "ic_weight": ic_weights,
    })


class TestProperty3ValueSanitization:
    """Property 3: Value Sanitization
    
    **Validates: Requirements 3.5, 3.6**
    
    For any numeric value in the processed DataFrame, the ResponseBuilder SHALL
    format it with 2-4 decimal places in the JSON output, and for any NaN or None
    value, the output SHALL be JSON null.
    """

    @given(value=valid_float_strategy(), decimals=st.integers(min_value=2, max_value=4))
    def test_valid_floats_are_properly_rounded(self, value, decimals):
        """Valid numeric values should be rounded to specified decimal places."""
        builder = ResponseBuilder()
        result = builder._sanitize_value(value, decimals=decimals)
        
        # Result should not be None
        assert result is not None, f"Valid float {value} should not become None"
        
        # Result should be a float
        assert isinstance(result, float), f"Result should be float, got {type(result)}"
        
        # Result should not be NaN or Inf
        assert not math.isnan(result), "Result should not be NaN"
        assert not math.isinf(result), "Result should not be Inf"
        
        # Result should be rounded to correct decimal places
        # Check by converting to string and counting decimals
        result_str = f"{result:.{decimals}f}"
        expected_str = f"{round(value, decimals):.{decimals}f}"
        assert result_str == expected_str, f"Expected {expected_str}, got {result_str}"

    @given(value=invalid_numeric_strategy())
    def test_invalid_values_become_none(self, value):
        """NaN, Inf, and None values should always become None."""
        builder = ResponseBuilder()
        result = builder._sanitize_value(value, decimals=2)
        
        assert result is None, f"Invalid value {value} should become None, got {result}"

    @given(df=dataframe_with_mixed_values())
    def test_full_response_contains_no_nan_or_inf(self, df):
        """Full response JSON should never contain NaN or Inf values."""
        builder = ResponseBuilder()
        
        # Build full response
        response = builder.build_full_response(
            df,
            cache_hit=False,
            data_age_seconds=10.0,
            errors=None
        )
        
        # Convert to JSON string (this is what gets sent over HTTP)
        response_dict = response.model_dump(mode='json')
        json_str = json.dumps(response_dict)
        
        # JSON should not contain NaN or Infinity strings
        assert "NaN" not in json_str, "JSON output contains NaN"
        assert "Infinity" not in json_str, "JSON output contains Infinity"
        assert "-Infinity" not in json_str, "JSON output contains -Infinity"
        
        # Verify all numeric fields in assets are either valid floats or None
        if response.assets:
            for asset in response.assets:
                numeric_fields = [
                    asset.composite_score,
                    asset.price,
                    asset.change_24h,
                    asset.volume_24h,
                    asset.funding_rate,
                    asset.open_interest,
                    asset.long_short_ratio,
                    asset.rsi,
                    asset.volatility,
                    asset.ic_weight,
                ]
                
                for field_value in numeric_fields:
                    if field_value is not None:
                        assert isinstance(field_value, (int, float)), \
                            f"Field should be numeric or None, got {type(field_value)}"
                        assert not math.isnan(field_value), \
                            f"Field contains NaN: {field_value}"
                        assert not math.isinf(field_value), \
                            f"Field contains Inf: {field_value}"

    @given(df=dataframe_with_mixed_values())
    def test_summary_response_contains_no_nan_or_inf(self, df):
        """Summary response JSON should never contain NaN or Inf values."""
        builder = ResponseBuilder()
        
        # Build summary-only response
        response = builder.build_summary_only(
            df,
            cache_hit=True,
            data_age_seconds=5.0,
            errors=None
        )
        
        # Convert to JSON
        response_dict = response.model_dump(mode='json')
        json_str = json.dumps(response_dict)
        
        # JSON should not contain NaN or Infinity strings
        assert "NaN" not in json_str, "JSON output contains NaN"
        assert "Infinity" not in json_str, "JSON output contains Infinity"
        assert "-Infinity" not in json_str, "JSON output contains -Infinity"
        
        # Verify top_3_assets numeric fields
        for asset in response.summary.top_3_assets:
            if asset.composite_score is not None:
                assert not math.isnan(asset.composite_score)
                assert not math.isinf(asset.composite_score)
        
        # Verify market_overview numeric fields
        overview = response.summary.market_overview
        if overview.avg_change_24h is not None:
            assert not math.isnan(overview.avg_change_24h)
            assert not math.isinf(overview.avg_change_24h)
        if overview.avg_funding_rate is not None:
            assert not math.isnan(overview.avg_funding_rate)
            assert not math.isinf(overview.avg_funding_rate)
        if overview.total_volume is not None:
            assert not math.isnan(overview.total_volume)
            assert not math.isinf(overview.total_volume)

    @given(df=dataframe_with_mixed_values(), symbol_index=st.integers(min_value=0, max_value=9))
    def test_asset_detail_response_contains_no_nan_or_inf(self, df, symbol_index):
        """Asset detail response JSON should never contain NaN or Inf values."""
        # Ensure symbol_index is within bounds
        if symbol_index >= len(df):
            symbol_index = 0
        
        builder = ResponseBuilder()
        symbol = df.iloc[symbol_index]["symbol"]
        
        # Build asset detail response
        response = builder.build_asset_detail(
            df,
            symbol=symbol,
            cache_hit=False,
            data_age_seconds=15.0
        )
        
        # Convert to JSON
        response_dict = response.model_dump(mode='json')
        json_str = json.dumps(response_dict)
        
        # JSON should not contain NaN or Infinity strings
        assert "NaN" not in json_str, "JSON output contains NaN"
        assert "Infinity" not in json_str, "JSON output contains Infinity"
        assert "-Infinity" not in json_str, "JSON output contains -Infinity"
        
        # Verify all numeric fields
        asset = response.asset
        numeric_fields = [
            asset.composite_score,
            asset.price,
            asset.change_24h,
            asset.volume_24h,
            asset.funding_rate,
            asset.open_interest,
            asset.long_short_ratio,
            asset.rsi,
            asset.volatility,
            asset.ic_weight,
        ]
        
        for field_value in numeric_fields:
            if field_value is not None:
                assert isinstance(field_value, (int, float))
                assert not math.isnan(field_value)
                assert not math.isinf(field_value)

    @given(
        value=valid_float_strategy(),
        decimals=st.integers(min_value=2, max_value=4)
    )
    def test_decimal_precision_is_exact(self, value, decimals):
        """Rounded values should have exactly the specified decimal precision."""
        builder = ResponseBuilder()
        result = builder._sanitize_value(value, decimals=decimals)
        
        if result is not None:
            # Convert to string and check decimal places
            result_str = str(result)
            if '.' in result_str:
                decimal_part = result_str.split('.')[1]
                # The actual decimal places might be less if trailing zeros are removed
                # But the value should match what we'd get with round()
                expected = round(value, decimals)
                assert result == expected, \
                    f"Expected {expected} with {decimals} decimals, got {result}"

    @given(df=dataframe_with_mixed_values())
    def test_all_numeric_fields_have_correct_precision(self, df):
        """All numeric fields in response should have 2-4 decimal places."""
        builder = ResponseBuilder()
        response = builder.build_full_response(
            df,
            cache_hit=False,
            data_age_seconds=0.0,
            errors=None
        )
        
        # Check assets
        if response.assets:
            for asset in response.assets:
                # Fields with 4 decimals
                for field in [asset.composite_score, asset.change_24h, 
                             asset.funding_rate, asset.long_short_ratio,
                             asset.volatility, asset.ic_weight]:
                    if field is not None:
                        # Should be rounded to at most 4 decimals
                        assert field == round(field, 4), \
                            f"Field {field} should be rounded to 4 decimals"
                
                # Fields with 2 decimals
                for field in [asset.price, asset.volume_24h, 
                             asset.open_interest, asset.rsi]:
                    if field is not None:
                        # Should be rounded to at most 2 decimals
                        assert field == round(field, 2), \
                            f"Field {field} should be rounded to 2 decimals"
