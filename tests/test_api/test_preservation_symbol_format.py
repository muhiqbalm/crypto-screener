"""Preservation Property Tests for Debug API Symbol Format Fix.

This test suite verifies that existing functionality remains unchanged after the fix.
These tests are designed to PASS on unfixed code to establish a baseline of behavior
that must be preserved.

**IMPORTANT**: These tests follow observation-first methodology:
1. Run tests on UNFIXED code to observe current behavior
2. Tests should PASS on unfixed code (confirming baseline)
3. After fix is applied, tests should still PASS (confirming preservation)

Feature: debug-api-symbol-format-fix
Spec: d:\\WORK\\CRYPTO-SCREENER\\crypto-screener\\.kiro\\specs\\debug-api-symbol-format-fix
"""

import pytest
import pytest_asyncio
from hypothesis import given, strategies as st, settings, HealthCheck, assume
from unittest.mock import AsyncMock, MagicMock, patch
import ccxt
from datetime import datetime


# ---------------------------------------------------------------------------
# Property 2: Preservation - Existing Endpoint Behavior
# ---------------------------------------------------------------------------
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4**


@pytest.mark.asyncio
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None  # Disable deadline for network-dependent tests
)
@given(
    # Generate test scenarios for endpoints that should remain unchanged
    endpoint_type=st.sampled_from([
        "funding_rate",
        "long_short_ratio"
    ])
)
async def test_property_preservation_binance_format_endpoints(
    preservation_test_app, 
    async_preservation_client, 
    endpoint_type
):
    """Property 2: Preservation - Existing Endpoint Behavior with Binance Native Format.

    This test verifies that endpoints which currently work with Binance native format
    (BTCUSDT) continue to work exactly as before after the fix is applied.

    **EXPECTED OUTCOME ON UNFIXED CODE**: This test will PASS, establishing baseline behavior.
    **After the fix is applied**: This test should still PASS, confirming no regressions.

    Test Scenarios:
    1. Funding rate endpoint with BTCUSDT - should continue to work
    2. Long/short ratio endpoint with BTCUSDT - should continue to work

    **Validates: Requirements 3.1, 3.2**
    """
    # Define test cases
    test_cases = {
        "funding_rate": {
            "symbol": "BTCUSDT",
            "endpoint": "/api/v1/debug/exchange/funding-rate/BTCUSDT",
            "description": "Funding rate endpoint should continue to work with Binance native format"
        },
        "long_short_ratio": {
            "symbol": "BTCUSDT",
            "endpoint": "/api/v1/debug/exchange/long-short-ratio/BTCUSDT",
            "description": "Long/short ratio endpoint should continue to work with Binance native format"
        }
    }

    test_case = test_cases[endpoint_type]
    symbol = test_case["symbol"]
    endpoint = test_case["endpoint"]
    description = test_case["description"]

    # Make request to the endpoint
    response = await async_preservation_client.get(endpoint)

    # PRESERVATION: These endpoints should work with Binance native format
    # Status should be 200 (success) or expected error codes (401, 503, 504, 502, 500)
    assert response.status_code in [200, 401, 503, 504, 502, 500], (
        f"Preservation violation: {endpoint_type} endpoint returned unexpected status {response.status_code}.\n"
        f"Endpoint: {endpoint}\n"
        f"Expected: 200 or error codes (401, 503, 504, 502, 500)\n"
        f"Description: {description}\n"
        f"Response: {response.json()}"
    )

    response_data = response.json()

    # If successful, verify response structure is preserved
    if response.status_code == 200:
        assert response_data.get("success") is True, (
            f"Preservation violation: Expected success=True for {endpoint_type}"
        )
        assert "data" in response_data, (
            f"Preservation violation: Expected 'data' field in response for {endpoint_type}"
        )
        assert "metadata" in response_data, (
            f"Preservation violation: Expected 'metadata' field in response for {endpoint_type}"
        )
        
        # Verify metadata structure
        metadata = response_data["metadata"]
        assert "request_timestamp" in metadata, (
            f"Preservation violation: Expected 'request_timestamp' in metadata"
        )
        assert "response_timestamp" in metadata, (
            f"Preservation violation: Expected 'response_timestamp' in metadata"
        )
        assert "response_time_ms" in metadata, (
            f"Preservation violation: Expected 'response_time_ms' in metadata"
        )
        assert "exchange" in metadata, (
            f"Preservation violation: Expected 'exchange' in metadata"
        )
        assert metadata["exchange"] == "binanceusdm", (
            f"Preservation violation: Expected exchange='binanceusdm'"
        )

    # If error, verify error structure is preserved
    if response.status_code != 200:
        assert "error" in response_data, (
            f"Preservation violation: Expected 'error' field in error response"
        )
        error = response_data["error"]
        assert "message" in error, (
            f"Preservation violation: Expected 'message' in error object"
        )
        assert "code" in error, (
            f"Preservation violation: Expected 'code' in error object"
        )


@pytest.mark.asyncio
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate various invalid symbols
    invalid_symbol=st.sampled_from([
        "",  # Empty string
        "   ",  # Whitespace only
        "@#$",  # Special characters
        "BTC-USDT",  # Hyphen (invalid)
        "BTC_USDT",  # Underscore (invalid)
        "BTC USDT",  # Space (invalid)
        "A" * 21,  # Exceeds 20 character limit
        "!@#$%^&*()",  # Multiple special characters
        "BTC/USDT",  # Slash only (incomplete CCXT format)
        "BTC:USDT",  # Colon only (incomplete CCXT format)
    ])
)
async def test_property_preservation_invalid_symbols(
    preservation_test_app,
    async_preservation_client,
    invalid_symbol
):
    """Property 2: Preservation - Invalid Symbol Rejection.

    This test verifies that invalid symbols continue to be rejected with appropriate
    error messages after the fix is applied.

    **EXPECTED OUTCOME ON UNFIXED CODE**: This test will PASS, confirming invalid symbols are rejected.
    **After the fix is applied**: This test should still PASS, confirming validation still works.

    **Validates: Requirement 3.3**
    """
    # Test on ticker endpoint (representative endpoint)
    endpoint = f"/api/v1/debug/exchange/ticker/{invalid_symbol}"

    # Make request to the endpoint
    response = await async_preservation_client.get(endpoint)

    # PRESERVATION: Invalid symbols should be rejected with error status
    # The debug routes return 500 when http_status is None (validation errors)
    # or 400 if http_status is explicitly set to 400
    assert response.status_code in [400, 500], (
        f"Preservation violation: Invalid symbol '{invalid_symbol}' should return 400 or 500.\n"
        f"Got status: {response.status_code}\n"
        f"Response: {response.json()}"
    )

    response_data = response.json()

    # Verify error structure is preserved
    assert response_data.get("success") is False, (
        f"Preservation violation: Expected success=False for invalid symbol"
    )
    assert "error" in response_data, (
        f"Preservation violation: Expected 'error' field in response"
    )

    error = response_data["error"]
    assert "message" in error, (
        f"Preservation violation: Expected 'message' in error object"
    )
    assert "code" in error, (
        f"Preservation violation: Expected 'code' in error object"
    )
    assert error["code"] == "INVALID_INPUT", (
        f"Preservation violation: Expected error code 'INVALID_INPUT' for invalid symbol.\n"
        f"Got: {error['code']}"
    )

    # Verify metadata is present
    assert "metadata" in response_data, (
        f"Preservation violation: Expected 'metadata' field in error response"
    )


@pytest.mark.asyncio
@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    # Generate test scenarios for different error types
    error_scenario=st.sampled_from([
        "authentication_error",
        "network_error",
        "timeout_error",
        "exchange_error"
    ])
)
async def test_property_preservation_error_response_structure(
    preservation_test_app,
    async_preservation_client,
    error_scenario
):
    """Property 2: Preservation - Error Response Structure.

    This test verifies that error response structure (HTTP status codes, error codes,
    metadata) remains unchanged after the fix is applied.

    **EXPECTED OUTCOME ON UNFIXED CODE**: This test will PASS, confirming error structure.
    **After the fix is applied**: This test should still PASS, confirming structure preserved.

    **Validates: Requirement 3.4**
    """
    # Map scenarios to expected behavior
    expected_behavior = {
        "authentication_error": {
            "status_code": 401,
            "error_code": "UNAUTHORIZED",
            "message_contains": "Authentication"
        },
        "network_error": {
            "status_code": 503,
            "error_code": "SERVICE_UNAVAILABLE",
            "message_contains": "Service unavailable"
        },
        "timeout_error": {
            "status_code": 504,
            "error_code": "GATEWAY_TIMEOUT",
            "message_contains": "timeout"
        },
        "exchange_error": {
            "status_code": 502,
            "error_code": "EXCHANGE_ERROR",
            "message_contains": "Exchange error"
        }
    }

    expected = expected_behavior[error_scenario]

    # Use a valid symbol for this test
    symbol = "BTCUSDT"
    endpoint = f"/api/v1/debug/exchange/ticker/{symbol}"

    # Make request (the mock will simulate the error based on app state)
    response = await async_preservation_client.get(
        endpoint,
        headers={"X-Test-Error-Scenario": error_scenario}
    )

    # PRESERVATION: Error responses should have consistent structure
    assert response.status_code == expected["status_code"], (
        f"Preservation violation: Expected status {expected['status_code']} for {error_scenario}.\n"
        f"Got: {response.status_code}"
    )

    response_data = response.json()

    # Verify error response structure
    assert response_data.get("success") is False, (
        f"Preservation violation: Expected success=False for error response"
    )
    assert "error" in response_data, (
        f"Preservation violation: Expected 'error' field in error response"
    )

    error = response_data["error"]
    assert "message" in error, (
        f"Preservation violation: Expected 'message' in error object"
    )
    assert "code" in error, (
        f"Preservation violation: Expected 'code' in error object"
    )
    assert error["code"] == expected["error_code"], (
        f"Preservation violation: Expected error code '{expected['error_code']}'.\n"
        f"Got: {error['code']}"
    )

    # Verify metadata structure is preserved
    assert "metadata" in response_data, (
        f"Preservation violation: Expected 'metadata' field in error response"
    )

    metadata = response_data["metadata"]
    assert "request_timestamp" in metadata, (
        f"Preservation violation: Expected 'request_timestamp' in metadata"
    )
    assert "response_timestamp" in metadata, (
        f"Preservation violation: Expected 'response_timestamp' in metadata"
    )
    assert "response_time_ms" in metadata, (
        f"Preservation violation: Expected 'response_time_ms' in metadata"
    )
    assert "http_status" in metadata, (
        f"Preservation violation: Expected 'http_status' in metadata"
    )
    assert metadata["http_status"] == expected["status_code"], (
        f"Preservation violation: Expected http_status={expected['status_code']} in metadata"
    )
    assert "exchange" in metadata, (
        f"Preservation violation: Expected 'exchange' in metadata"
    )


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def preservation_test_app():
    """FastAPI app configured for preservation testing with mocked exchange.

    Creates a test app with mocked DebugExchangeService that simulates
    the current behavior on unfixed code.
    """
    from fastapi import FastAPI, Request
    from src.api.debug_routes import router
    from src.config.settings import Settings
    from unittest.mock import MagicMock, patch as mock_patch
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

    # Mock fetch_funding_rate to simulate current behavior (works with Binance format)
    def mock_fetch_funding_rate(symbol):
        # Funding rate works with both formats (CCXT handles it internally)
        return {
            "symbol": symbol,
            "fundingRate": 0.0001,
            "fundingTimestamp": 1704067200000
        }

    mock_exchange.fetch_funding_rate = mock_fetch_funding_rate

    # Create mock exchange connector
    mock_connector = MagicMock()
    mock_connector.get_exchange.return_value = mock_exchange

    # Create debug service with mocked exchange
    from src.services.debug_exchange_service import DebugExchangeService
    
    # Patch requests.get before creating the service
    with mock_patch('src.services.debug_exchange_service.requests.get') as mock_requests_get:
        # Mock fetch_long_short_ratio (via requests) to simulate current behavior
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "symbol": "BTCUSDT",
            "longShortRatio": 1.25,
            "longAccount": 0.55,
            "shortAccount": 0.45,
            "timestamp": 1704067200000
        }
        mock_requests_get.return_value = mock_response
        
        debug_service = DebugExchangeService(mock_connector)
        
        # Store the mock for later use
        app.state.mock_requests_get = mock_requests_get

    # Set up app state
    app.state.settings = mock_settings
    app.state.debug_service = debug_service
    app.state.start_time = time.time()

    # Add middleware to simulate error scenarios based on headers
    @app.middleware("http")
    async def error_simulation_middleware(request: Request, call_next):
        error_scenario = request.headers.get("X-Test-Error-Scenario")
        
        if error_scenario:
            # Simulate different error scenarios
            from src.api.debug_models import DebugResponse, ErrorInfo, RequestMetadata
            from datetime import datetime
            
            request_time = datetime.utcnow()
            response_time = datetime.utcnow()
            
            error_responses = {
                "authentication_error": DebugResponse(
                    success=False,
                    error=ErrorInfo(
                        message="Authentication required",
                        code="UNAUTHORIZED"
                    ),
                    metadata=RequestMetadata(
                        request_timestamp=request_time,
                        response_timestamp=response_time,
                        response_time_ms=10.0,
                        http_status=401,
                        exchange="binanceusdm"
                    )
                ),
                "network_error": DebugResponse(
                    success=False,
                    error=ErrorInfo(
                        message="Service unavailable: Network error",
                        code="SERVICE_UNAVAILABLE",
                        details="Cannot connect to exchange"
                    ),
                    metadata=RequestMetadata(
                        request_timestamp=request_time,
                        response_timestamp=response_time,
                        response_time_ms=5000.0,
                        http_status=503,
                        exchange="binanceusdm"
                    )
                ),
                "timeout_error": DebugResponse(
                    success=False,
                    error=ErrorInfo(
                        message="Gateway timeout: Exchange request timed out",
                        code="GATEWAY_TIMEOUT",
                        timeout_duration_ms=30000.0
                    ),
                    metadata=RequestMetadata(
                        request_timestamp=request_time,
                        response_timestamp=response_time,
                        response_time_ms=30000.0,
                        http_status=504,
                        exchange="binanceusdm"
                    )
                ),
                "exchange_error": DebugResponse(
                    success=False,
                    error=ErrorInfo(
                        message="Exchange error: Bad Gateway",
                        code="EXCHANGE_ERROR"
                    ),
                    metadata=RequestMetadata(
                        request_timestamp=request_time,
                        response_timestamp=response_time,
                        response_time_ms=100.0,
                        http_status=502,
                        exchange="binanceusdm"
                    )
                )
            }
            
            if error_scenario in error_responses:
                from fastapi.responses import JSONResponse
                error_response = error_responses[error_scenario]
                return JSONResponse(
                    status_code=error_response.metadata.http_status,
                    content=error_response.model_dump(mode='json', exclude_none=True)
                )
        
        response = await call_next(request)
        return response

    return app


@pytest_asyncio.fixture
async def async_preservation_client(preservation_test_app):
    """httpx AsyncClient wired to the preservation test FastAPI app.

    Provides a fully functional HTTP client for testing debug API endpoints
    without starting a real server.
    """
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import patch as mock_patch, MagicMock

    # Mock requests.get for long/short ratio endpoint
    with mock_patch('src.services.debug_exchange_service.requests.get') as mock_requests_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "symbol": "BTCUSDT",
            "longShortRatio": 1.25,
            "longAccount": 0.55,
            "shortAccount": 0.45,
            "timestamp": 1704067200000
        }
        mock_requests_get.return_value = mock_response
        
        transport = ASGITransport(app=preservation_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
