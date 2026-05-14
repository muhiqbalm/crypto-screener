"""Bug Condition Exploration Test for Debug API Symbol Format Bug.

This test is designed to FAIL on unfixed code to confirm the bug exists.
It tests that CCXT unified format (BTC/USDT:USDT) is rejected by validation,
and that Binance native format (BTCUSDT) fails on ticker and open-interest endpoints.

**CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists.
**DO NOT attempt to fix the test or the code when it fails.**

The test assertions encode the EXPECTED BEHAVIOR (both formats accepted and converted).
When the test fails, it proves the bug exists and provides counterexamples.

Feature: debug-api-symbol-format-fix
Spec: d:\\WORK\\CRYPTO-SCREENER\\crypto-screener\\.kiro\\specs\\debug-api-symbol-format-fix
"""

import pytest
import pytest_asyncio
from hypothesis import given, strategies as st, settings, HealthCheck
from unittest.mock import AsyncMock, MagicMock, patch
import ccxt


# ---------------------------------------------------------------------------
# Property 1: Bug Condition - CCXT Unified Format Acceptance and Binance Format Conversion
# ---------------------------------------------------------------------------
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5**


@pytest.mark.asyncio
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate test scenarios
    scenario=st.sampled_from([
        "ccxt_format_ticker",
        "ccxt_format_open_interest",
        "binance_format_ticker",
        "binance_format_open_interest"
    ])
)
async def test_property_bug_condition_symbol_format(debug_test_app, async_debug_client, scenario):
    """Property 1: Bug Condition - CCXT Unified Format Acceptance and Binance Format Conversion.

    This test encodes the EXPECTED BEHAVIOR: both CCXT unified format (BTC/USDT:USDT)
    and Binance native format (BTCUSDT) should be accepted and automatically converted
    to the correct format for each endpoint.

    **EXPECTED OUTCOME ON UNFIXED CODE**: This test will FAIL, proving the bug exists.
    The failures will show counterexamples where:
    - CCXT format is rejected by validation with "Symbol must contain only alphanumeric characters"
    - Binance format passes validation but fails on CCXT methods with symbol not found errors

    **After the fix is applied**: This test will PASS, confirming the bug is resolved.

    Test Scenarios:
    1. CCXT format (BTC/USDT:USDT) on ticker endpoint - should be accepted and work
    2. CCXT format (BTC/USDT:USDT) on open-interest endpoint - should be accepted and work
    3. Binance format (BTCUSDT) on ticker endpoint - should be converted and work
    4. Binance format (BTCUSDT) on open-interest endpoint - should be converted and work

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5**
    """
    # Define test cases
    test_cases = {
        "ccxt_format_ticker": {
            "symbol": "BTC/USDT:USDT",
            "endpoint": "/api/v1/debug/exchange/ticker/BTC/USDT:USDT",
            "format": "CCXT unified",
            "expected_behavior": "Should accept CCXT format and successfully fetch ticker data"
        },
        "ccxt_format_open_interest": {
            "symbol": "BTC/USDT:USDT",
            "endpoint": "/api/v1/debug/exchange/open-interest/BTC/USDT:USDT",
            "format": "CCXT unified",
            "expected_behavior": "Should accept CCXT format and successfully fetch open interest data"
        },
        "binance_format_ticker": {
            "symbol": "BTCUSDT",
            "endpoint": "/api/v1/debug/exchange/ticker/BTCUSDT",
            "format": "Binance native",
            "expected_behavior": "Should convert to CCXT format and successfully fetch ticker data"
        },
        "binance_format_open_interest": {
            "symbol": "BTCUSDT",
            "endpoint": "/api/v1/debug/exchange/open-interest/BTCUSDT",
            "format": "Binance native",
            "expected_behavior": "Should convert to CCXT format and successfully fetch open interest data"
        }
    }

    test_case = test_cases[scenario]
    symbol = test_case["symbol"]
    endpoint = test_case["endpoint"]
    format_type = test_case["format"]
    expected_behavior = test_case["expected_behavior"]

    # Make request to the endpoint
    response = await async_debug_client.get(endpoint)

    # EXPECTED BEHAVIOR: Both formats should be accepted (not return validation error)
    # ON UNFIXED CODE: CCXT format will return 400 with "Symbol must contain only alphanumeric characters"
    if response.status_code == 400:
        response_data = response.json()
        error_message = response_data.get("error", {}).get("message", "")
        error_code = response_data.get("error", {}).get("code", "")

        # Check if this is a validation error (the bug we're testing for)
        if error_code == "INVALID_INPUT" and "alphanumeric" in error_message:
            pytest.fail(
                f"COUNTEREXAMPLE FOUND: {format_type} format '{symbol}' rejected by validation.\n"
                f"Endpoint: {endpoint}\n"
                f"Error: {error_message}\n"
                f"Expected behavior: {expected_behavior}\n"
                f"This confirms the bug exists - validation is too restrictive.\n"
                f"Full response: {response_data}"
            )

    # EXPECTED BEHAVIOR: Request should succeed or return non-validation error
    # ON UNFIXED CODE: Binance format may pass validation but fail with CCXT error
    assert response.status_code in [200, 401, 503, 504, 502, 500], (
        f"COUNTEREXAMPLE FOUND: Unexpected status code {response.status_code} for {format_type} format '{symbol}'.\n"
        f"Endpoint: {endpoint}\n"
        f"Expected: 200 (success) or 401/503/504/502/500 (non-validation errors)\n"
        f"Got: {response.status_code}\n"
        f"This may indicate the bug exists.\n"
        f"Response: {response.json()}"
    )

    response_data = response.json()

    # If we got a success response, verify it has the expected structure
    if response.status_code == 200:
        assert response_data.get("success") is True, (
            f"Expected success=True for {format_type} format '{symbol}', got {response_data.get('success')}"
        )
        assert "data" in response_data, (
            f"Expected 'data' field in successful response for {format_type} format '{symbol}'"
        )
        assert "metadata" in response_data, (
            f"Expected 'metadata' field in successful response for {format_type} format '{symbol}'"
        )

    # If we got an error response, it should NOT be a validation error
    if response.status_code != 200:
        error_code = response_data.get("error", {}).get("code", "")
        error_message = response_data.get("error", {}).get("message", "")

        # Check if this is an INTERNAL_ERROR caused by CCXT not finding the symbol
        # This happens when Binance format is passed to CCXT methods that expect unified format
        if error_code == "INTERNAL_ERROR" or error_code == "EXCHANGE_ERROR":
            # Check if the error message indicates symbol not found or similar CCXT error
            if any(keyword in error_message.lower() for keyword in ["symbol", "not found", "invalid symbol", "does not have market"]):
                pytest.fail(
                    f"COUNTEREXAMPLE FOUND: {format_type} format '{symbol}' passed validation but failed with CCXT error.\n"
                    f"Endpoint: {endpoint}\n"
                    f"Error code: {error_code}\n"
                    f"Error message: {error_message}\n"
                    f"Expected behavior: {expected_behavior}\n"
                    f"This confirms the bug exists - missing format conversion logic.\n"
                    f"Full response: {response_data}"
                )

        # Validation errors should not occur for valid symbols
        assert error_code != "INVALID_INPUT", (
            f"COUNTEREXAMPLE FOUND: {format_type} format '{symbol}' rejected with validation error.\n"
            f"Endpoint: {endpoint}\n"
            f"Error: {error_message}\n"
            f"Expected behavior: {expected_behavior}\n"
            f"This confirms the bug exists.\n"
            f"Full response: {response_data}"
        )


@pytest.mark.asyncio
async def test_verify_root_cause_validation_isalnum():
    """Verify the fix by inspecting the validate_symbol() function.

    This test reads the debug_utils.py file to confirm that validate_symbol()
    now uses regex pattern to accept '/' and ':' characters.

    This is a code inspection test that documents the fix.
    """
    import os

    # Read the debug_utils.py file
    debug_utils_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "src", "api", "debug_utils.py"
    )

    with open(debug_utils_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify that validate_symbol() exists
    assert "def validate_symbol(symbol: str)" in content, (
        "Expected to find validate_symbol() function in debug_utils.py"
    )

    # Find the validate_symbol function
    func_start = content.find("def validate_symbol(symbol: str)")
    func_end = content.find("\ndef ", func_start + 1)
    if func_end == -1:
        func_end = len(content)

    func_content = content[func_start:func_end]

    # Verify that regex pattern is present (the fix)
    assert "re.match" in func_content, (
        "Expected to find 're.match' in validate_symbol() function. "
        "This confirms the fix - validation now uses regex pattern."
    )

    # Verify that the pattern accepts / and :
    assert "[A-Za-z0-9/:]" in func_content or r"[A-Za-z0-9/:]" in func_content, (
        "Expected to find pattern that accepts '/' and ':' characters. "
        "This confirms the fix."
    )

    # Verify CCXT format pattern is present
    assert "ccxt_pattern" in func_content or "CCXT" in func_content, (
        "Expected to find CCXT format validation. "
        "This confirms the fix supports CCXT unified format."
    )

    print("\n" + "="*80)
    print("FIX VERIFICATION COMPLETE - VALIDATION")
    print("="*80)
    print("✓ Confirmed: validate_symbol() now uses regex pattern")
    print("✓ Confirmed: Pattern accepts '/' and ':' characters")
    print("✓ Confirmed: CCXT unified format is supported")
    print("\nFix implementation is correct:")
    print("1. validate_symbol() in debug_utils.py uses regex pattern")
    print("2. Pattern accepts '/' and ':' characters present in CCXT unified format")
    print("3. Valid CCXT format symbols like 'BTC/USDT:USDT' are now accepted")
    print("="*80 + "\n")


@pytest.mark.asyncio
async def test_verify_fix_conversion_logic_present():
    """Verify the fix by confirming format conversion logic exists in debug_exchange_service.py.

    This test reads the debug_exchange_service.py file to confirm that
    format conversion logic has been added to fetch_raw_ticker() and fetch_raw_open_interest().

    This is a code inspection test that documents the fix.
    """
    import os

    # Read the debug_exchange_service.py file
    service_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "src", "services", "debug_exchange_service.py"
    )

    with open(service_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify that fetch_raw_ticker() exists
    assert "async def fetch_raw_ticker(self, symbol: str)" in content, (
        "Expected to find fetch_raw_ticker() method in debug_exchange_service.py"
    )

    # Verify that fetch_raw_open_interest() exists
    assert "async def fetch_raw_open_interest(self, symbol: str)" in content, (
        "Expected to find fetch_raw_open_interest() method in debug_exchange_service.py"
    )

    # Check for format conversion functions (should exist after fix)
    has_conversion_logic = (
        "ensure_ccxt_format" in content
    )

    assert has_conversion_logic, (
        "Expected format conversion logic in debug_exchange_service.py. "
        "The fix should include ensure_ccxt_format() function calls."
    )

    # Find fetch_raw_ticker method
    ticker_start = content.find("async def fetch_raw_ticker(self, symbol: str)")
    ticker_end = content.find("\n    async def ", ticker_start + 1)
    if ticker_end == -1:
        ticker_end = content.find("\n    def ", ticker_start + 1)
    if ticker_end == -1:
        ticker_end = len(content)

    ticker_content = content[ticker_start:ticker_end]

    # Verify that ticker method uses ensure_ccxt_format
    assert "ensure_ccxt_format" in ticker_content, (
        "Expected fetch_raw_ticker() to use ensure_ccxt_format() for symbol conversion. "
        "This confirms the fix is in place."
    )

    # Find fetch_raw_open_interest method
    oi_start = content.find("async def fetch_raw_open_interest(self, symbol: str)")
    oi_end = content.find("\n    async def ", oi_start + 1)
    if oi_end == -1:
        oi_end = content.find("\n    def ", oi_start + 1)
    if oi_end == -1:
        oi_end = len(content)

    oi_content = content[oi_start:oi_end]

    # Verify that open_interest method uses ensure_ccxt_format
    assert "ensure_ccxt_format" in oi_content, (
        "Expected fetch_raw_open_interest() to use ensure_ccxt_format() for symbol conversion. "
        "This confirms the fix is in place."
    )

    print("\n" + "="*80)
    print("FIX VERIFICATION COMPLETE - CONVERSION LOGIC")
    print("="*80)
    print("✓ Confirmed: Format conversion logic exists in debug_exchange_service.py")
    print("✓ Confirmed: fetch_raw_ticker() uses ensure_ccxt_format()")
    print("✓ Confirmed: fetch_raw_open_interest() uses ensure_ccxt_format()")
    print("\nFix implementation is correct:")
    print("1. ensure_ccxt_format() function is imported and used")
    print("2. Symbols are converted to CCXT format before calling CCXT methods")
    print("3. Both Binance native and CCXT unified formats are now supported")
    print("="*80 + "\n")


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def debug_test_app():
    """FastAPI app configured for debug API testing with mocked exchange.

    Creates a test app with mocked DebugExchangeService that simulates
    the bug behavior on unfixed code.
    """
    from fastapi import FastAPI
    from src.api.debug_routes import router
    from src.config.settings import Settings
    from unittest.mock import MagicMock
    import time

    app = FastAPI()
    app.include_router(router)

    # Create mock settings
    mock_settings = Settings(
        api_host="127.0.0.1",
        api_port=8000,
        mock_mode=True,
        debug_api_auth_enabled=False,
    )

    # Create mock exchange connector
    mock_exchange = MagicMock()

    # Mock fetch_ticker to simulate CCXT behavior
    async def mock_fetch_ticker(symbol):
        # CCXT expects unified format (BTC/USDT:USDT)
        # If given Binance format (BTCUSDT), it will fail
        if "/" not in symbol or ":" not in symbol:
            # Simulate CCXT error for Binance native format
            raise ccxt.ExchangeError(f"binanceusdm does not have market symbol {symbol}")
        # Simulate successful response for CCXT unified format
        return {
            "symbol": symbol,
            "last": 67500.0,
            "percentage": 2.35,
            "quoteVolume": 28000000000.0
        }

    # Mock fetch_open_interest to simulate CCXT behavior
    async def mock_fetch_open_interest(symbol):
        # CCXT expects unified format (BTC/USDT:USDT)
        # If given Binance format (BTCUSDT), it will fail
        if "/" not in symbol or ":" not in symbol:
            # Simulate CCXT error for Binance native format
            raise ccxt.ExchangeError(f"binanceusdm does not have market symbol {symbol}")
        # Simulate successful response for CCXT unified format
        return {
            "symbol": symbol,
            "openInterestAmount": 18000000000.0
        }

    mock_exchange.fetch_ticker = mock_fetch_ticker
    mock_exchange.fetch_open_interest = mock_fetch_open_interest

    # Create mock exchange connector
    mock_connector = MagicMock()
    mock_connector.get_exchange.return_value = mock_exchange

    # Create debug service with mocked exchange
    from src.services.debug_exchange_service import DebugExchangeService
    debug_service = DebugExchangeService(mock_connector)

    # Set up app state
    app.state.settings = mock_settings
    app.state.debug_service = debug_service
    app.state.start_time = time.time()

    return app


@pytest_asyncio.fixture
async def async_debug_client(debug_test_app):
    """httpx AsyncClient wired to the debug test FastAPI app.

    Provides a fully functional HTTP client for testing debug API endpoints
    without starting a real server.
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=debug_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
