"""Preservation Property Tests for Null Volume and Open Interest Bugfix.

This test file verifies that all non-volume/OI fields remain unchanged
when the bugfix is applied. These tests follow the observation-first methodology:
1. Observe behavior on UNFIXED code
2. Write property-based tests capturing that behavior
3. Run tests on UNFIXED code - they should PASS
4. After fix is applied, re-run tests - they should still PASS (no regressions)

**EXPECTED OUTCOME ON UNFIXED CODE**: All tests PASS (confirms baseline behavior)
**EXPECTED OUTCOME AFTER FIX**: All tests still PASS (confirms no regressions)

Feature: null-volume-open-interest-fix
Spec: d:\WORK\CRYPTO-SCREENER\crypto-screener\.kiro\specs\null-volume-open-interest-fix
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck


# ---------------------------------------------------------------------------
# Property 2: Preservation - Non-Volume/OI Field Behavior
# ---------------------------------------------------------------------------
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**


@pytest.mark.asyncio
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate valid symbols from the configured list
    symbol_index=st.integers(min_value=0, max_value=4)
)
async def test_property_preservation_non_volume_oi_fields(async_client, mock_settings, symbol_index):
    """Property 2: Preservation - Non-Volume/OI Field Behavior.

    This test verifies that all non-volume/open-interest fields produce
    correct values on UNFIXED code and remain unchanged after the fix.

    For any API request to /screener/summary or /screener/assets/{symbol},
    the response SHALL contain correct values for:
    - price, change_24h, funding_rate, long_short_ratio
    - rsi, macd_signal, volatility, ic_weight
    - composite_score, rank, signal
    - market_overview aggregations (avg_change_24h, avg_funding_rate, sentiment counts)

    **EXPECTED OUTCOME ON UNFIXED CODE**: Tests PASS (confirms baseline behavior)
    **EXPECTED OUTCOME AFTER FIX**: Tests still PASS (confirms no regressions)

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
    """
    # Get a valid symbol from the configured list
    symbols = mock_settings.symbols_list
    symbol = symbols[symbol_index]

    # Test 1: Summary endpoint - verify all non-volume/OI fields
    summary_response = await async_client.get("/api/v1/screener/summary")
    assert summary_response.status_code == 200, (
        f"Expected 200 for summary endpoint, got {summary_response.status_code}"
    )

    summary_data = summary_response.json()

    # Verify assets array exists and is not empty
    assert "assets" in summary_data, "Response missing 'assets' field"
    assert len(summary_data["assets"]) > 0, "Assets array should not be empty"

    # Check each asset for correct non-volume/OI field values
    for asset in summary_data["assets"]:
        asset_symbol = asset.get("symbol", "unknown")

        # Verify price field
        assert "price" in asset, f"Asset {asset_symbol} missing 'price' field"
        price = asset.get("price")
        if price is not None:
            assert isinstance(price, (int, float)), (
                f"price should be numeric, got {type(price)} for {asset_symbol}"
            )
            assert price > 0, (
                f"price should be positive, got {price} for {asset_symbol}"
            )

        # Verify change_24h field
        assert "change_24h" in asset, f"Asset {asset_symbol} missing 'change_24h' field"
        change_24h = asset.get("change_24h")
        if change_24h is not None:
            assert isinstance(change_24h, (int, float)), (
                f"change_24h should be numeric, got {type(change_24h)} for {asset_symbol}"
            )

        # Verify funding_rate field
        assert "funding_rate" in asset, f"Asset {asset_symbol} missing 'funding_rate' field"
        funding_rate = asset.get("funding_rate")
        if funding_rate is not None:
            assert isinstance(funding_rate, (int, float)), (
                f"funding_rate should be numeric, got {type(funding_rate)} for {asset_symbol}"
            )

        # Verify long_short_ratio field
        assert "long_short_ratio" in asset, f"Asset {asset_symbol} missing 'long_short_ratio' field"
        long_short_ratio = asset.get("long_short_ratio")
        if long_short_ratio is not None:
            assert isinstance(long_short_ratio, (int, float)), (
                f"long_short_ratio should be numeric, got {type(long_short_ratio)} for {asset_symbol}"
            )
            assert long_short_ratio > 0, (
                f"long_short_ratio should be positive, got {long_short_ratio} for {asset_symbol}"
            )

        # Verify rsi field
        assert "rsi" in asset, f"Asset {asset_symbol} missing 'rsi' field"
        rsi = asset.get("rsi")
        if rsi is not None:
            assert isinstance(rsi, (int, float)), (
                f"rsi should be numeric, got {type(rsi)} for {asset_symbol}"
            )
            assert 0 <= rsi <= 100, (
                f"rsi should be between 0 and 100, got {rsi} for {asset_symbol}"
            )

        # Verify macd_signal field
        assert "macd_signal" in asset, f"Asset {asset_symbol} missing 'macd_signal' field"
        macd_signal = asset.get("macd_signal")
        if macd_signal is not None:
            assert macd_signal in ["BUY", "SELL", "HOLD"], (
                f"macd_signal should be BUY/SELL/HOLD, got {macd_signal} for {asset_symbol}"
            )

        # Verify volatility field
        assert "volatility" in asset, f"Asset {asset_symbol} missing 'volatility' field"
        volatility = asset.get("volatility")
        if volatility is not None:
            assert isinstance(volatility, (int, float)), (
                f"volatility should be numeric, got {type(volatility)} for {asset_symbol}"
            )
            assert volatility >= 0, (
                f"volatility should be non-negative, got {volatility} for {asset_symbol}"
            )

        # Verify ic_weight field
        assert "ic_weight" in asset, f"Asset {asset_symbol} missing 'ic_weight' field"
        ic_weight = asset.get("ic_weight")
        if ic_weight is not None:
            assert isinstance(ic_weight, (int, float)), (
                f"ic_weight should be numeric, got {type(ic_weight)} for {asset_symbol}"
            )

        # Verify composite_score field
        assert "composite_score" in asset, f"Asset {asset_symbol} missing 'composite_score' field"
        composite_score = asset.get("composite_score")
        if composite_score is not None:
            assert isinstance(composite_score, (int, float)), (
                f"composite_score should be numeric, got {type(composite_score)} for {asset_symbol}"
            )
            assert 0 <= composite_score <= 1, (
                f"composite_score should be between 0 and 1, got {composite_score} for {asset_symbol}"
            )

        # Verify rank field
        assert "rank" in asset, f"Asset {asset_symbol} missing 'rank' field"
        rank = asset.get("rank")
        if rank is not None:
            assert isinstance(rank, int), (
                f"rank should be integer, got {type(rank)} for {asset_symbol}"
            )
            assert rank > 0, (
                f"rank should be positive, got {rank} for {asset_symbol}"
            )

        # Verify signal field
        assert "signal" in asset, f"Asset {asset_symbol} missing 'signal' field"
        signal = asset.get("signal")
        if signal is not None:
            assert signal in ["BULLISH", "BEARISH", "NEUTRAL"], (
                f"signal should be BULLISH/BEARISH/NEUTRAL, got {signal} for {asset_symbol}"
            )

    # Test 2: Asset detail endpoint - verify all non-volume/OI fields
    detail_response = await async_client.get(f"/api/v1/screener/assets/{symbol}")
    assert detail_response.status_code == 200, (
        f"Expected 200 for asset detail endpoint, got {detail_response.status_code}"
    )

    detail_data = detail_response.json()

    # Verify asset field exists
    assert "asset" in detail_data, "Response missing 'asset' field"
    asset_detail = detail_data["asset"]

    # Verify all non-volume/OI fields in asset detail
    assert "price" in asset_detail, f"Asset detail missing 'price' field"
    assert "change_24h" in asset_detail, f"Asset detail missing 'change_24h' field"
    assert "funding_rate" in asset_detail, f"Asset detail missing 'funding_rate' field"
    assert "long_short_ratio" in asset_detail, f"Asset detail missing 'long_short_ratio' field"
    assert "rsi" in asset_detail, f"Asset detail missing 'rsi' field"
    assert "macd_signal" in asset_detail, f"Asset detail missing 'macd_signal' field"
    assert "volatility" in asset_detail, f"Asset detail missing 'volatility' field"
    assert "ic_weight" in asset_detail, f"Asset detail missing 'ic_weight' field"
    assert "composite_score" in asset_detail, f"Asset detail missing 'composite_score' field"
    assert "rank" in asset_detail, f"Asset detail missing 'rank' field"
    assert "signal" in asset_detail, f"Asset detail missing 'signal' field"

    # Verify field types and ranges
    if asset_detail.get("price") is not None:
        assert isinstance(asset_detail["price"], (int, float))
        assert asset_detail["price"] > 0

    if asset_detail.get("rsi") is not None:
        assert isinstance(asset_detail["rsi"], (int, float))
        assert 0 <= asset_detail["rsi"] <= 100

    if asset_detail.get("signal") is not None:
        assert asset_detail["signal"] in ["BULLISH", "BEARISH", "NEUTRAL"]

    if asset_detail.get("macd_signal") is not None:
        assert asset_detail["macd_signal"] in ["BUY", "SELL", "HOLD"]


@pytest.mark.asyncio
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate valid symbols from the configured list
    symbol_index=st.integers(min_value=0, max_value=4)
)
async def test_property_preservation_market_overview(async_client, mock_settings, symbol_index):
    """Property 2: Preservation - Market Overview Aggregations.

    This test verifies that market_overview aggregations (avg_change_24h,
    avg_funding_rate, bullish_count, bearish_count, neutral_count) work
    correctly on UNFIXED code and remain unchanged after the fix.

    **EXPECTED OUTCOME ON UNFIXED CODE**: Tests PASS (confirms baseline behavior)
    **EXPECTED OUTCOME AFTER FIX**: Tests still PASS (confirms no regressions)

    **Validates: Requirements 3.4, 3.5**
    """
    # Test: Summary endpoint - verify market_overview aggregations
    summary_response = await async_client.get("/api/v1/screener/summary")
    assert summary_response.status_code == 200, (
        f"Expected 200 for summary endpoint, got {summary_response.status_code}"
    )

    summary_data = summary_response.json()

    # Verify summary and market_overview exist
    assert "summary" in summary_data, "Response missing 'summary' field"
    assert "market_overview" in summary_data["summary"], "Summary missing 'market_overview' field"

    market_overview = summary_data["summary"]["market_overview"]

    # Verify avg_change_24h field
    assert "avg_change_24h" in market_overview, "Market overview missing 'avg_change_24h' field"
    avg_change_24h = market_overview.get("avg_change_24h")
    if avg_change_24h is not None:
        assert isinstance(avg_change_24h, (int, float)), (
            f"avg_change_24h should be numeric, got {type(avg_change_24h)}"
        )

    # Verify avg_funding_rate field
    assert "avg_funding_rate" in market_overview, "Market overview missing 'avg_funding_rate' field"
    avg_funding_rate = market_overview.get("avg_funding_rate")
    if avg_funding_rate is not None:
        assert isinstance(avg_funding_rate, (int, float)), (
            f"avg_funding_rate should be numeric, got {type(avg_funding_rate)}"
        )

    # Verify sentiment counts
    assert "bullish_count" in market_overview, "Market overview missing 'bullish_count' field"
    assert "bearish_count" in market_overview, "Market overview missing 'bearish_count' field"
    assert "neutral_count" in market_overview, "Market overview missing 'neutral_count' field"

    bullish_count = market_overview.get("bullish_count")
    bearish_count = market_overview.get("bearish_count")
    neutral_count = market_overview.get("neutral_count")

    assert isinstance(bullish_count, int), (
        f"bullish_count should be integer, got {type(bullish_count)}"
    )
    assert isinstance(bearish_count, int), (
        f"bearish_count should be integer, got {type(bearish_count)}"
    )
    assert isinstance(neutral_count, int), (
        f"neutral_count should be integer, got {type(neutral_count)}"
    )

    assert bullish_count >= 0, f"bullish_count should be non-negative, got {bullish_count}"
    assert bearish_count >= 0, f"bearish_count should be non-negative, got {bearish_count}"
    assert neutral_count >= 0, f"neutral_count should be non-negative, got {neutral_count}"

    # Verify sentiment counts sum to total assets
    total_assets = len(summary_data.get("assets", []))
    sentiment_sum = bullish_count + bearish_count + neutral_count
    assert sentiment_sum == total_assets, (
        f"Sentiment counts should sum to total assets. "
        f"Expected {total_assets}, got {sentiment_sum} "
        f"(bullish={bullish_count}, bearish={bearish_count}, neutral={neutral_count})"
    )

    # Verify top_3_assets exist and have correct structure
    assert "top_3_assets" in summary_data["summary"], "Summary missing 'top_3_assets' field"
    top_3_assets = summary_data["summary"]["top_3_assets"]

    assert isinstance(top_3_assets, list), (
        f"top_3_assets should be a list, got {type(top_3_assets)}"
    )
    assert len(top_3_assets) <= 3, (
        f"top_3_assets should have at most 3 items, got {len(top_3_assets)}"
    )

    # Verify each top asset has required fields
    for top_asset in top_3_assets:
        assert "symbol" in top_asset, "Top asset missing 'symbol' field"
        assert "rank" in top_asset, "Top asset missing 'rank' field"
        assert "composite_score" in top_asset, "Top asset missing 'composite_score' field"
        assert "signal" in top_asset, "Top asset missing 'signal' field"


@pytest.mark.asyncio
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate valid symbols from the configured list
    symbol_index=st.integers(min_value=0, max_value=4)
)
async def test_property_preservation_cache_behavior(async_client, mock_settings, symbol_index):
    """Property 2: Preservation - Cache Behavior.

    This test verifies that cache behavior (cache_hit, data_age_seconds,
    stale_data_warning) works correctly on UNFIXED code and remains
    unchanged after the fix.

    **EXPECTED OUTCOME ON UNFIXED CODE**: Tests PASS (confirms baseline behavior)
    **EXPECTED OUTCOME AFTER FIX**: Tests still PASS (confirms no regressions)

    **Validates: Requirements 3.7**
    """
    # Get a valid symbol from the configured list
    symbols = mock_settings.symbols_list
    symbol = symbols[symbol_index]

    # Test 1: Summary endpoint - verify cache metadata
    summary_response = await async_client.get("/api/v1/screener/summary")
    assert summary_response.status_code == 200, (
        f"Expected 200 for summary endpoint, got {summary_response.status_code}"
    )

    summary_data = summary_response.json()

    # Verify metadata exists
    assert "metadata" in summary_data, "Response missing 'metadata' field"
    metadata = summary_data["metadata"]

    # Verify cache_hit field
    assert "cache_hit" in metadata, "Metadata missing 'cache_hit' field"
    cache_hit = metadata.get("cache_hit")
    assert isinstance(cache_hit, bool), (
        f"cache_hit should be boolean, got {type(cache_hit)}"
    )

    # Verify data_age_seconds field
    assert "data_age_seconds" in metadata, "Metadata missing 'data_age_seconds' field"
    data_age_seconds = metadata.get("data_age_seconds")
    if data_age_seconds is not None:
        assert isinstance(data_age_seconds, (int, float)), (
            f"data_age_seconds should be numeric, got {type(data_age_seconds)}"
        )
        assert data_age_seconds >= 0, (
            f"data_age_seconds should be non-negative, got {data_age_seconds}"
        )

    # Verify stale_data_warning field
    assert "stale_data_warning" in metadata, "Metadata missing 'stale_data_warning' field"
    stale_data_warning = metadata.get("stale_data_warning")
    if stale_data_warning is not None:
        assert isinstance(stale_data_warning, bool), (
            f"stale_data_warning should be boolean, got {type(stale_data_warning)}"
        )

    # Verify timestamp field
    assert "timestamp" in metadata, "Metadata missing 'timestamp' field"
    timestamp = metadata.get("timestamp")
    assert timestamp is not None, "timestamp should not be null"

    # Verify symbols_count field
    assert "symbols_count" in metadata, "Metadata missing 'symbols_count' field"
    symbols_count = metadata.get("symbols_count")
    assert isinstance(symbols_count, int), (
        f"symbols_count should be integer, got {type(symbols_count)}"
    )
    assert symbols_count >= 0, (
        f"symbols_count should be non-negative, got {symbols_count}"
    )

    # Verify errors_count field
    assert "errors_count" in metadata, "Metadata missing 'errors_count' field"
    errors_count = metadata.get("errors_count")
    assert isinstance(errors_count, int), (
        f"errors_count should be integer, got {type(errors_count)}"
    )
    assert errors_count >= 0, (
        f"errors_count should be non-negative, got {errors_count}"
    )

    # Test 2: Asset detail endpoint - verify cache metadata
    detail_response = await async_client.get(f"/api/v1/screener/assets/{symbol}")
    assert detail_response.status_code == 200, (
        f"Expected 200 for asset detail endpoint, got {detail_response.status_code}"
    )

    detail_data = detail_response.json()

    # Verify metadata exists in asset detail response
    assert "metadata" in detail_data, "Asset detail response missing 'metadata' field"
    detail_metadata = detail_data["metadata"]

    # Verify cache_hit field in asset detail
    assert "cache_hit" in detail_metadata, "Asset detail metadata missing 'cache_hit' field"
    assert isinstance(detail_metadata["cache_hit"], bool)

    # Verify data_age_seconds field in asset detail
    assert "data_age_seconds" in detail_metadata, "Asset detail metadata missing 'data_age_seconds' field"
    if detail_metadata.get("data_age_seconds") is not None:
        assert isinstance(detail_metadata["data_age_seconds"], (int, float))
        assert detail_metadata["data_age_seconds"] >= 0


@pytest.mark.asyncio
async def test_property_preservation_error_handling(async_client, mock_settings):
    """Property 2: Preservation - Error Handling.

    This test verifies that error handling (404, 500, 503) works correctly
    on UNFIXED code and remains unchanged after the fix.

    **EXPECTED OUTCOME ON UNFIXED CODE**: Tests PASS (confirms baseline behavior)
    **EXPECTED OUTCOME AFTER FIX**: Tests still PASS (confirms no regressions)

    **Validates: Requirements 3.8, 3.9**
    """
    # Test 1: 404 for invalid symbol
    # Request with invalid symbol
    response = await async_client.get("/api/v1/screener/assets/INVALID_SYMBOL")

    # Verify 404 status
    assert response.status_code == 404, (
        f"Expected 404 for invalid symbol, got {response.status_code}"
    )

    # Verify error response structure
    error_data = response.json()
    assert "error" in error_data, "Error response missing 'error' field"
    assert "message" in error_data, "Error response missing 'message' field"
    assert "available_symbols" in error_data, "Error response missing 'available_symbols' field"
    assert "timestamp" in error_data, "Error response missing 'timestamp' field"

    # Verify error field value
    assert error_data["error"] == "Not Found", (
        f"Expected error='Not Found', got '{error_data['error']}'"
    )

    # Verify available_symbols is a list
    assert isinstance(error_data["available_symbols"], list), (
        f"available_symbols should be a list, got {type(error_data['available_symbols'])}"
    )


@pytest.mark.asyncio
async def test_property_preservation_health_endpoint(async_client, mock_settings):
    """Property 2: Preservation - Health Endpoint.

    This test verifies that the /api/v1/health endpoint works correctly
    on UNFIXED code and remains unchanged after the fix.

    **EXPECTED OUTCOME ON UNFIXED CODE**: Tests PASS (confirms baseline behavior)
    **EXPECTED OUTCOME AFTER FIX**: Tests still PASS (confirms no regressions)

    **Validates: Requirements 3.10**
    """
    # Request health endpoint
    response = await async_client.get("/api/v1/health")

    # Verify 200 status
    assert response.status_code == 200, (
        f"Expected 200 for health endpoint, got {response.status_code}"
    )

    # Verify health response structure
    health_data = response.json()
    assert "status" in health_data, "Health response missing 'status' field"
    assert "uptime_seconds" in health_data, "Health response missing 'uptime_seconds' field"
    assert "cache_status" in health_data, "Health response missing 'cache_status' field"
    assert "version" in health_data, "Health response missing 'version' field"

    # Verify status field value
    assert health_data["status"] == "healthy", (
        f"Expected status='healthy', got '{health_data['status']}'"
    )

    # Verify uptime_seconds is numeric and non-negative
    uptime_seconds = health_data.get("uptime_seconds")
    assert isinstance(uptime_seconds, (int, float)), (
        f"uptime_seconds should be numeric, got {type(uptime_seconds)}"
    )
    assert uptime_seconds >= 0, (
        f"uptime_seconds should be non-negative, got {uptime_seconds}"
    )

    # Verify cache_status structure
    cache_status = health_data.get("cache_status")
    assert isinstance(cache_status, dict), (
        f"cache_status should be a dict, got {type(cache_status)}"
    )
    assert "data_age_seconds" in cache_status, "cache_status missing 'data_age_seconds' field"
    assert "is_stale" in cache_status, "cache_status missing 'is_stale' field"

    # Verify is_stale is boolean
    is_stale = cache_status.get("is_stale")
    assert isinstance(is_stale, bool), (
        f"is_stale should be boolean, got {type(is_stale)}"
    )

    # Verify version field
    version = health_data.get("version")
    assert isinstance(version, str), (
        f"version should be string, got {type(version)}"
    )
    assert len(version) > 0, "version should not be empty"

