"""Property-based tests for API routes using Hypothesis.

Tests universal correctness properties across randomly generated inputs.
Each property test runs minimum 100 iterations.

Feature: api-backend-transformation
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from src.services.symbol_utils import normalize_symbol


# ---------------------------------------------------------------------------
# Property 4: Invalid Symbol Rejection
# ---------------------------------------------------------------------------
# **Validates: Requirements 4.5, 14.1, 14.2, 14.3**


@pytest.mark.asyncio
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    invalid_symbol=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),  # Uppercase, lowercase, digits
            whitelist_characters="/:-_",
        ),
        min_size=1,
        max_size=20,
    ).filter(lambda s: _is_invalid_symbol(s))
)
async def test_property_invalid_symbol_rejection(async_client, mock_settings, invalid_symbol):
    """Property 4: Invalid Symbol Rejection.

    For any string that is not in the configured SYMBOLS list (after normalization),
    a request to /api/v1/screener/assets/{symbol} SHALL return HTTP 404 with:
    - Response body containing an "error" field
    - Response body containing a "message" field mentioning the symbol
    - Response body containing an "available_symbols" field with the list of valid symbols
    - Response body containing a "timestamp" field

    **Validates: Requirements 4.5, 14.1, 14.2, 14.3**
    """
    # Make request to the asset detail endpoint with invalid symbol
    response = await async_client.get(f"/api/v1/screener/assets/{invalid_symbol}")

    # Verify HTTP 404 status
    assert response.status_code == 404, (
        f"Expected 404 for invalid symbol '{invalid_symbol}', got {response.status_code}"
    )

    # Parse response body
    body = response.json()

    # Verify "error" field is present
    assert "error" in body, f"Response missing 'error' field for symbol '{invalid_symbol}'"
    assert body["error"] == "Not Found", (
        f"Expected error='Not Found', got '{body['error']}'"
    )

    # Verify "message" field is present and mentions the symbol
    assert "message" in body, f"Response missing 'message' field for symbol '{invalid_symbol}'"
    assert invalid_symbol in body["message"] or "not found" in body["message"].lower(), (
        f"Message should mention the symbol or 'not found': {body['message']}"
    )

    # Verify "available_symbols" field is present and is a list
    assert "available_symbols" in body, (
        f"Response missing 'available_symbols' field for symbol '{invalid_symbol}'"
    )
    assert isinstance(body["available_symbols"], list), (
        f"'available_symbols' should be a list, got {type(body['available_symbols'])}"
    )
    assert len(body["available_symbols"]) > 0, (
        "'available_symbols' list should not be empty"
    )

    # Verify all available symbols are valid
    expected_symbols = mock_settings.symbols_list
    assert body["available_symbols"] == expected_symbols, (
        f"Expected available_symbols={expected_symbols}, got {body['available_symbols']}"
    )

    # Verify "timestamp" field is present
    assert "timestamp" in body, f"Response missing 'timestamp' field for symbol '{invalid_symbol}'"


def _is_invalid_symbol(symbol: str) -> bool:
    """Filter function to ensure generated symbol is NOT in the configured list.

    Args:
        symbol: The generated symbol string.

    Returns:
        True if the symbol is invalid (not in configured list), False otherwise.
    """
    # Use the same configured symbols as in mock_settings fixture
    configured_symbols = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "AAVE/USDT:USDT",
        "LINK/USDT:USDT",
    ]

    # Normalize the symbol using the same logic as the API
    normalized = normalize_symbol(symbol, configured_symbols)

    # Return True if normalization fails (symbol is invalid)
    return normalized is None
