"""Bug Condition Exploration Test for Null Volume and Open Interest Bug.

This test is designed to FAIL on unfixed code to confirm the bug exists.
It tests that volume_24h and open_interest fields return null values
in both /api/v1/screener/summary and /api/v1/screener/assets/{symbol} endpoints.

**CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists.
**DO NOT attempt to fix the test or the code when it fails.**

The test assertions encode the EXPECTED BEHAVIOR (non-null values when data is available).
When the test fails, it proves the bug exists and provides counterexamples.

Feature: null-volume-open-interest-fix
Spec: d:\WORK\CRYPTO-SCREENER\crypto-screener\.kiro\specs\null-volume-open-interest-fix
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck


# ---------------------------------------------------------------------------
# Property 1: Bug Condition - Volume and Open Interest Return Null
# ---------------------------------------------------------------------------
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**


@pytest.mark.asyncio
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate valid symbols from the configured list
    symbol_index=st.integers(min_value=0, max_value=4)
)
async def test_property_bug_condition_volume_oi_null(async_client, mock_settings, symbol_index):
    """Property 1: Bug Condition - Volume and Open Interest Data Population.

    This test encodes the EXPECTED BEHAVIOR: when exchange provides data,
    volume_24h and open_interest should be non-null numeric values.

    **EXPECTED OUTCOME ON UNFIXED CODE**: This test will FAIL, proving the bug exists.
    The failures will show counterexamples where these fields are null despite
    the exchange providing the data.

    **After the fix is applied**: This test will PASS, confirming the bug is resolved.

    For any API request to /screener/summary or /screener/assets/{symbol},
    the response SHALL contain:
    - volume_24h as a non-null numeric value (when exchange provides data)
    - open_interest as a non-null numeric value (when exchange provides data)
    - total_volume in market_overview as a non-null numeric value (when at least one asset has volume)

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5**
    """
    # Get a valid symbol from the configured list
    symbols = mock_settings.symbols_list
    symbol = symbols[symbol_index]

    # Test 1: Summary endpoint - check all assets have non-null volume_24h and open_interest
    summary_response = await async_client.get("/api/v1/screener/summary")
    assert summary_response.status_code == 200, (
        f"Expected 200 for summary endpoint, got {summary_response.status_code}"
    )

    summary_data = summary_response.json()

    # Verify assets array exists and is not empty
    assert "assets" in summary_data, "Response missing 'assets' field"
    assert len(summary_data["assets"]) > 0, "Assets array should not be empty"

    # Check each asset for non-null volume_24h and open_interest
    for asset in summary_data["assets"]:
        asset_symbol = asset.get("symbol", "unknown")

        # EXPECTED BEHAVIOR: volume_24h should be non-null when exchange provides data
        # ON UNFIXED CODE: This assertion will FAIL because volume_24h is hardcoded to null
        assert asset.get("volume_24h") is not None, (
            f"COUNTEREXAMPLE FOUND: Asset {asset_symbol} has volume_24h=null in summary endpoint. "
            f"Expected non-null numeric value when exchange provides volume data. "
            f"This confirms the bug exists. Full asset data: {asset}"
        )

        # Verify volume_24h is a valid numeric value
        volume = asset.get("volume_24h")
        assert isinstance(volume, (int, float)), (
            f"volume_24h should be numeric, got {type(volume)} for {asset_symbol}"
        )
        assert volume >= 0, (
            f"volume_24h should be non-negative, got {volume} for {asset_symbol}"
        )

        # EXPECTED BEHAVIOR: open_interest should be non-null when exchange provides data
        # ON UNFIXED CODE: This assertion will FAIL because open_interest is hardcoded to null
        # Note: open_interest may legitimately be null if exchange doesn't provide it,
        # but for major pairs like BTC/USDT, it should be available
        if asset_symbol in ["BTC/USDT:USDT", "ETH/USDT:USDT"]:
            assert asset.get("open_interest") is not None, (
                f"COUNTEREXAMPLE FOUND: Asset {asset_symbol} has open_interest=null in summary endpoint. "
                f"Expected non-null numeric value for major trading pairs. "
                f"This confirms the bug exists. Full asset data: {asset}"
            )

            # Verify open_interest is a valid numeric value
            oi = asset.get("open_interest")
            assert isinstance(oi, (int, float)), (
                f"open_interest should be numeric, got {type(oi)} for {asset_symbol}"
            )
            assert oi >= 0, (
                f"open_interest should be non-negative, got {oi} for {asset_symbol}"
            )

    # Test 2: Check market_overview.total_volume is non-null
    assert "summary" in summary_data, "Response missing 'summary' field"
    assert "market_overview" in summary_data["summary"], "Summary missing 'market_overview' field"

    market_overview = summary_data["summary"]["market_overview"]

    # EXPECTED BEHAVIOR: total_volume should be non-null when at least one asset has volume
    # ON UNFIXED CODE: This assertion will FAIL because all volume_24h values are null
    assert market_overview.get("total_volume") is not None, (
        f"COUNTEREXAMPLE FOUND: market_overview.total_volume is null. "
        f"Expected non-null value when at least one asset has volume_24h. "
        f"This confirms the bug exists (all volume_24h values are null, so total_volume is null). "
        f"Market overview: {market_overview}"
    )

    # Verify total_volume is a valid numeric value
    total_volume = market_overview.get("total_volume")
    assert isinstance(total_volume, (int, float)), (
        f"total_volume should be numeric, got {type(total_volume)}"
    )
    assert total_volume >= 0, (
        f"total_volume should be non-negative, got {total_volume}"
    )

    # Test 3: Asset detail endpoint - check specific symbol has non-null volume_24h and open_interest
    detail_response = await async_client.get(f"/api/v1/screener/assets/{symbol}")
    assert detail_response.status_code == 200, (
        f"Expected 200 for asset detail endpoint, got {detail_response.status_code}"
    )

    detail_data = detail_response.json()

    # Verify asset field exists
    assert "asset" in detail_data, "Response missing 'asset' field"
    asset_detail = detail_data["asset"]

    # EXPECTED BEHAVIOR: volume_24h should be non-null in asset detail endpoint
    # ON UNFIXED CODE: This assertion will FAIL because volume_24h is hardcoded to null
    assert asset_detail.get("volume_24h") is not None, (
        f"COUNTEREXAMPLE FOUND: Asset {symbol} has volume_24h=null in detail endpoint. "
        f"Expected non-null numeric value when exchange provides volume data. "
        f"This confirms the bug exists. Full asset detail: {asset_detail}"
    )

    # Verify volume_24h is a valid numeric value
    detail_volume = asset_detail.get("volume_24h")
    assert isinstance(detail_volume, (int, float)), (
        f"volume_24h should be numeric, got {type(detail_volume)} for {symbol}"
    )
    assert detail_volume >= 0, (
        f"volume_24h should be non-negative, got {detail_volume} for {symbol}"
    )

    # EXPECTED BEHAVIOR: open_interest should be non-null for major pairs in detail endpoint
    # ON UNFIXED CODE: This assertion will FAIL because open_interest is hardcoded to null
    if symbol in ["BTC/USDT:USDT", "ETH/USDT:USDT"]:
        assert asset_detail.get("open_interest") is not None, (
            f"COUNTEREXAMPLE FOUND: Asset {symbol} has open_interest=null in detail endpoint. "
            f"Expected non-null numeric value for major trading pairs. "
            f"This confirms the bug exists. Full asset detail: {asset_detail}"
        )

        # Verify open_interest is a valid numeric value
        detail_oi = asset_detail.get("open_interest")
        assert isinstance(detail_oi, (int, float)), (
            f"open_interest should be numeric, got {type(detail_oi)} for {symbol}"
        )
        assert detail_oi >= 0, (
            f"open_interest should be non-negative, got {detail_oi} for {symbol}"
        )


@pytest.mark.asyncio
async def test_verify_root_cause_hardcoded_none():
    """Verify the root cause by inspecting the source code.

    This test reads the response_builder.py file to confirm that
    volume_24h and open_interest are hardcoded to None.

    This is a code inspection test that documents the root cause.
    """
    import os

    # Read the response_builder.py file
    response_builder_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "src", "services", "response_builder.py"
    )

    with open(response_builder_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify that volume_24h=None is hardcoded (around line 296)
    assert "volume_24h=None" in content, (
        "Expected to find 'volume_24h=None' hardcoded in response_builder.py. "
        "This confirms the root cause of the bug."
    )

    # Verify that open_interest=None is hardcoded (around line 298)
    assert "open_interest=None" in content, (
        "Expected to find 'open_interest=None' hardcoded in response_builder.py. "
        "This confirms the root cause of the bug."
    )

    # Verify the comment indicating these fields are not fetched
    assert "Not fetched in current implementation" in content, (
        "Expected to find comment 'Not fetched in current implementation' in response_builder.py. "
        "This confirms the root cause is intentional hardcoding, not an oversight."
    )

    print("\n" + "="*80)
    print("ROOT CAUSE VERIFICATION COMPLETE")
    print("="*80)
    print("✓ Confirmed: volume_24h=None is hardcoded in response_builder.py")
    print("✓ Confirmed: open_interest=None is hardcoded in response_builder.py")
    print("✓ Confirmed: Comment indicates 'Not fetched in current implementation'")
    print("\nRoot cause analysis is correct:")
    print("1. ResponseBuilder._build_asset() hardcodes these fields to None")
    print("2. MarketDataFetcher does not extract volume from CCXT ticker response")
    print("3. MarketDataFetcher does not fetch open interest data")
    print("="*80 + "\n")


@pytest.mark.asyncio
async def test_verify_fetcher_missing_volume_extraction():
    """Verify that the fetcher does not extract volume from ticker response.

    This test reads the fetcher.py file to confirm that the fetch_ticker_data()
    method does not extract volume from the CCXT ticker response.
    """
    import os

    # Read the fetcher.py file
    fetcher_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "src", "data", "fetcher.py"
    )

    with open(fetcher_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the fetch_ticker_data method
    assert "def fetch_ticker_data(self, symbol: str)" in content, (
        "Expected to find fetch_ticker_data method in fetcher.py"
    )

    # Verify that the method does NOT extract volume
    # Look for the method and check if it extracts 'quoteVolume' or 'baseVolume'
    method_start = content.find("def fetch_ticker_data(self, symbol: str)")
    method_end = content.find("\n    def ", method_start + 1)
    if method_end == -1:
        method_end = len(content)

    method_content = content[method_start:method_end]

    # Check if volume extraction is missing
    has_volume_extraction = (
        "quoteVolume" in method_content or
        "baseVolume" in method_content or
        "'volume'" in method_content
    )

    assert not has_volume_extraction, (
        "Expected fetch_ticker_data to NOT extract volume from ticker response. "
        "If volume extraction is present, the root cause analysis may be incorrect."
    )

    print("\n" + "="*80)
    print("FETCHER VERIFICATION COMPLETE")
    print("="*80)
    print("✓ Confirmed: fetch_ticker_data() does NOT extract volume from ticker")
    print("✓ Confirmed: No 'quoteVolume' or 'baseVolume' extraction in method")
    print("\nThis confirms the root cause:")
    print("- The fetcher only extracts 'price' and 'change_24h' from ticker")
    print("- Volume data is available in CCXT ticker but not extracted")
    print("="*80 + "\n")
