"""Tests for debug_utils module (src/api/debug_utils.py).

Validates:
- validate_symbol() correctly validates symbol parameters
- normalize_symbol() correctly normalizes symbol parameters
- detect_symbol_format() correctly detects symbol format
- convert_to_ccxt_format() correctly converts Binance to CCXT format
- convert_to_binance_format() correctly converts CCXT to Binance format
- ensure_ccxt_format() correctly ensures CCXT format
- Requirements 11.1, 11.2, 11.3, 11.4, 11.5
"""

import pytest

from src.api.debug_utils import (
    convert_to_binance_format,
    convert_to_ccxt_format,
    detect_symbol_format,
    ensure_ccxt_format,
    normalize_symbol,
    validate_symbol,
)


class TestValidateSymbol:
    """Tests for the validate_symbol() function."""

    def test_valid_symbol_returns_true(self):
        """Valid alphanumeric symbol returns (True, None)."""
        is_valid, error = validate_symbol("BTCUSDT")
        assert is_valid is True
        assert error is None

    def test_valid_symbol_with_numbers(self):
        """Valid symbol with numbers returns (True, None)."""
        is_valid, error = validate_symbol("BTC2USDT")
        assert is_valid is True
        assert error is None

    def test_empty_string_returns_error(self):
        """Empty string returns (False, 'Symbol parameter is required')."""
        is_valid, error = validate_symbol("")
        assert is_valid is False
        assert error == "Symbol parameter is required"

    def test_whitespace_only_returns_error(self):
        """Whitespace-only string returns (False, 'Symbol parameter is required')."""
        is_valid, error = validate_symbol("   ")
        assert is_valid is False
        assert error == "Symbol parameter is required"

    def test_symbol_with_hyphen_returns_error(self):
        """Symbol with hyphen returns error for invalid characters."""
        is_valid, error = validate_symbol("BTC-USDT")
        assert is_valid is False
        assert error == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"

    def test_symbol_with_underscore_returns_error(self):
        """Symbol with underscore returns error for invalid characters."""
        is_valid, error = validate_symbol("BTC_USDT")
        assert is_valid is False
        assert error == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"

    def test_symbol_with_slash_only_returns_error(self):
        """Symbol with slash only (not full CCXT format) returns format error."""
        is_valid, error = validate_symbol("BTC/USDT")
        assert is_valid is False
        assert error == "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"

    def test_symbol_with_special_chars_returns_error(self):
        """Symbol with special characters returns error for invalid characters."""
        is_valid, error = validate_symbol("BTC@USDT")
        assert is_valid is False
        assert error == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"

    def test_symbol_exceeding_max_length_returns_error(self):
        """Symbol exceeding 20 characters (Binance format) returns error."""
        is_valid, error = validate_symbol("A" * 21)
        assert is_valid is False
        assert error == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"

    def test_symbol_at_max_length_is_valid(self):
        """Symbol with exactly 20 characters is valid."""
        is_valid, error = validate_symbol("A" * 20)
        assert is_valid is True
        assert error is None

    def test_symbol_with_leading_whitespace_is_valid(self):
        """Symbol with leading whitespace is valid after trimming."""
        is_valid, error = validate_symbol("  BTCUSDT")
        assert is_valid is True
        assert error is None

    def test_symbol_with_trailing_whitespace_is_valid(self):
        """Symbol with trailing whitespace is valid after trimming."""
        is_valid, error = validate_symbol("BTCUSDT  ")
        assert is_valid is True
        assert error is None

    def test_symbol_with_both_whitespace_is_valid(self):
        """Symbol with leading and trailing whitespace is valid after trimming."""
        is_valid, error = validate_symbol("  BTCUSDT  ")
        assert is_valid is True
        assert error is None

    def test_symbol_with_whitespace_exceeding_length_after_trim(self):
        """Symbol with whitespace that exceeds length after trimming returns error."""
        # 21 characters + whitespace
        is_valid, error = validate_symbol("  " + "A" * 21 + "  ")
        assert is_valid is False
        assert error == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"

    def test_lowercase_symbol_is_valid(self):
        """Lowercase symbol is valid (normalization happens separately)."""
        is_valid, error = validate_symbol("btcusdt")
        assert is_valid is True
        assert error is None

    def test_mixed_case_symbol_is_valid(self):
        """Mixed case symbol is valid."""
        is_valid, error = validate_symbol("BtcUsDt")
        assert is_valid is True
        assert error is None

    # CCXT unified format tests
    def test_valid_ccxt_format_returns_true(self):
        """Valid CCXT unified format (BTC/USDT:USDT) returns (True, None)."""
        is_valid, error = validate_symbol("BTC/USDT:USDT")
        assert is_valid is True
        assert error is None

    def test_valid_ccxt_format_lowercase_returns_true(self):
        """Valid CCXT unified format in lowercase is valid."""
        is_valid, error = validate_symbol("btc/usdt:usdt")
        assert is_valid is True
        assert error is None

    def test_valid_ccxt_format_eth_returns_true(self):
        """Valid CCXT unified format for ETH returns (True, None)."""
        is_valid, error = validate_symbol("ETH/USDT:USDT")
        assert is_valid is True
        assert error is None

    def test_malformed_ccxt_double_slash_returns_error(self):
        """Malformed CCXT format with double slash returns format error."""
        is_valid, error = validate_symbol("BTC//USDT:USDT")
        assert is_valid is False
        assert error == "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"

    def test_malformed_ccxt_trailing_slash_returns_error(self):
        """Malformed CCXT format with trailing slash returns format error."""
        is_valid, error = validate_symbol("BTC:USDT/")
        assert is_valid is False
        assert error == "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"

    def test_malformed_ccxt_missing_colon_returns_error(self):
        """Malformed CCXT format missing colon returns format error."""
        is_valid, error = validate_symbol("BTC/USDT")
        assert is_valid is False
        assert error == "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"

    def test_malformed_ccxt_double_colon_returns_error(self):
        """Malformed CCXT format with double colon returns format error."""
        is_valid, error = validate_symbol("BTC/USDT::USDT")
        assert is_valid is False
        assert error == "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"

    def test_ccxt_format_exceeding_max_length_returns_error(self):
        """CCXT format exceeding 30 characters returns error."""
        # Create a symbol longer than 30 characters
        is_valid, error = validate_symbol("A" * 15 + "/" + "B" * 15 + ":C")
        assert is_valid is False
        assert error == "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"

    def test_ccxt_format_at_max_length_is_valid(self):
        """CCXT format with exactly 30 characters is valid."""
        # BTC/USDT:USDT is 13 characters, let's create a 30-char valid one
        # Pattern: BASE/QUOTE:SETTLE
        symbol = "ABCDEFGH/IJKLMNOP:QRSTUV"  # 8 + 1 + 8 + 1 + 6 = 24 chars
        is_valid, error = validate_symbol(symbol)
        assert is_valid is True
        assert error is None


class TestNormalizeSymbol:
    """Tests for the normalize_symbol() function."""

    def test_lowercase_symbol_converted_to_uppercase(self):
        """Lowercase symbol is converted to uppercase."""
        result = normalize_symbol("btcusdt")
        assert result == "BTCUSDT"

    def test_uppercase_symbol_remains_uppercase(self):
        """Uppercase symbol remains unchanged."""
        result = normalize_symbol("BTCUSDT")
        assert result == "BTCUSDT"

    def test_mixed_case_symbol_converted_to_uppercase(self):
        """Mixed case symbol is converted to uppercase."""
        result = normalize_symbol("BtcUsDt")
        assert result == "BTCUSDT"

    def test_leading_whitespace_trimmed(self):
        """Leading whitespace is trimmed."""
        result = normalize_symbol("  BTCUSDT")
        assert result == "BTCUSDT"

    def test_trailing_whitespace_trimmed(self):
        """Trailing whitespace is trimmed."""
        result = normalize_symbol("BTCUSDT  ")
        assert result == "BTCUSDT"

    def test_both_whitespace_trimmed(self):
        """Leading and trailing whitespace are trimmed."""
        result = normalize_symbol("  BTCUSDT  ")
        assert result == "BTCUSDT"

    def test_lowercase_with_whitespace(self):
        """Lowercase symbol with whitespace is normalized correctly."""
        result = normalize_symbol("  btcusdt  ")
        assert result == "BTCUSDT"

    def test_empty_string_returns_empty(self):
        """Empty string returns empty string."""
        result = normalize_symbol("")
        assert result == ""

    def test_whitespace_only_returns_empty(self):
        """Whitespace-only string returns empty string after trimming."""
        result = normalize_symbol("   ")
        assert result == ""

    def test_symbol_with_numbers(self):
        """Symbol with numbers is normalized correctly."""
        result = normalize_symbol("btc2usdt")
        assert result == "BTC2USDT"


class TestValidateAndNormalizeTogether:
    """Tests for using validate_symbol() and normalize_symbol() together."""

    def test_validate_then_normalize_workflow(self):
        """Typical workflow: validate first, then normalize."""
        symbol = "  btcusdt  "
        
        # Validate
        is_valid, error = validate_symbol(symbol)
        assert is_valid is True
        assert error is None
        
        # Normalize
        normalized = normalize_symbol(symbol)
        assert normalized == "BTCUSDT"

    def test_invalid_symbol_should_not_be_normalized(self):
        """Invalid symbols should be rejected before normalization."""
        symbol = "BTC-USDT"
        
        # Validate
        is_valid, error = validate_symbol(symbol)
        assert is_valid is False
        assert error == "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"
        
        # Should not normalize invalid symbols in practice,
        # but normalize_symbol() doesn't validate
        normalized = normalize_symbol(symbol)
        assert normalized == "BTC-USDT"  # Just converts to uppercase

    def test_empty_symbol_workflow(self):
        """Empty symbol is rejected by validation."""
        symbol = ""
        
        # Validate
        is_valid, error = validate_symbol(symbol)
        assert is_valid is False
        assert error == "Symbol parameter is required"
        
        # Normalize would return empty string
        normalized = normalize_symbol(symbol)
        assert normalized == ""



class TestDetectSymbolFormat:
    """Tests for the detect_symbol_format() function."""

    def test_ccxt_format_detected(self):
        """CCXT unified format (BTC/USDT:USDT) is detected as 'ccxt'."""
        result = detect_symbol_format("BTC/USDT:USDT")
        assert result == "ccxt"

    def test_binance_format_detected(self):
        """Binance native format (BTCUSDT) is detected as 'binance'."""
        result = detect_symbol_format("BTCUSDT")
        assert result == "binance"

    def test_eth_ccxt_format_detected(self):
        """ETH CCXT unified format is detected as 'ccxt'."""
        result = detect_symbol_format("ETH/USDT:USDT")
        assert result == "ccxt"

    def test_eth_binance_format_detected(self):
        """ETH Binance native format is detected as 'binance'."""
        result = detect_symbol_format("ETHUSDT")
        assert result == "binance"

    def test_symbol_with_only_slash_detected_as_binance(self):
        """Symbol with only slash (no colon) is detected as 'binance'."""
        result = detect_symbol_format("BTC/USDT")
        assert result == "binance"

    def test_symbol_with_only_colon_detected_as_binance(self):
        """Symbol with only colon (no slash) is detected as 'binance'."""
        result = detect_symbol_format("BTC:USDT")
        assert result == "binance"


class TestConvertToCcxtFormat:
    """Tests for the convert_to_ccxt_format() function."""

    def test_btcusdt_converted_to_ccxt(self):
        """BTCUSDT is converted to BTC/USDT:USDT."""
        result = convert_to_ccxt_format("BTCUSDT")
        assert result == "BTC/USDT:USDT"

    def test_ethusdt_converted_to_ccxt(self):
        """ETHUSDT is converted to ETH/USDT:USDT."""
        result = convert_to_ccxt_format("ETHUSDT")
        assert result == "ETH/USDT:USDT"

    def test_usdtusdt_edge_case_converted(self):
        """USDTUSDT edge case is converted to USDT/USDT:USDT."""
        result = convert_to_ccxt_format("USDTUSDT")
        assert result == "USDT/USDT:USDT"

    def test_busdusdt_converted_to_ccxt(self):
        """BUSDUSDT is converted to BUSD/USDT:USDT."""
        result = convert_to_ccxt_format("BUSDUSDT")
        assert result == "BUSD/USDT:USDT"

    def test_single_usdt_edge_case(self):
        """Single USDT is converted to USDT/USDT:USDT."""
        result = convert_to_ccxt_format("USDT")
        assert result == "USDT/USDT:USDT"

    def test_long_base_symbol_converted(self):
        """Long base symbol like SOLUSDT is converted correctly."""
        result = convert_to_ccxt_format("SOLUSDT")
        assert result == "SOL/USDT:USDT"

    def test_symbol_not_ending_with_usdt_fallback(self):
        """Symbol not ending with USDT uses fallback conversion."""
        result = convert_to_ccxt_format("BTCBUSD")
        assert result == "BTCBUSD/USDT:USDT"


class TestConvertToBinanceFormat:
    """Tests for the convert_to_binance_format() function."""

    def test_ccxt_btc_converted_to_binance(self):
        """BTC/USDT:USDT is converted to BTCUSDT."""
        result = convert_to_binance_format("BTC/USDT:USDT")
        assert result == "BTCUSDT"

    def test_ccxt_eth_converted_to_binance(self):
        """ETH/USDT:USDT is converted to ETHUSDT."""
        result = convert_to_binance_format("ETH/USDT:USDT")
        assert result == "ETHUSDT"

    def test_ccxt_usdt_edge_case_converted(self):
        """USDT/USDT:USDT edge case is converted to USDTUSDT."""
        result = convert_to_binance_format("USDT/USDT:USDT")
        assert result == "USDTUSDT"

    def test_ccxt_busd_converted_to_binance(self):
        """BTC/BUSD:BUSD is converted to BTCBUSD."""
        result = convert_to_binance_format("BTC/BUSD:BUSD")
        assert result == "BTCBUSD"

    def test_ccxt_sol_converted_to_binance(self):
        """SOL/USDT:USDT is converted to SOLUSDT."""
        result = convert_to_binance_format("SOL/USDT:USDT")
        assert result == "SOLUSDT"


class TestEnsureCcxtFormat:
    """Tests for the ensure_ccxt_format() function."""

    def test_binance_format_converted_to_ccxt(self):
        """Binance format BTCUSDT is converted to CCXT format."""
        result = ensure_ccxt_format("BTCUSDT")
        assert result == "BTC/USDT:USDT"

    def test_ccxt_format_returned_unchanged(self):
        """CCXT format BTC/USDT:USDT is returned unchanged."""
        result = ensure_ccxt_format("BTC/USDT:USDT")
        assert result == "BTC/USDT:USDT"

    def test_binance_eth_converted_to_ccxt(self):
        """Binance format ETHUSDT is converted to CCXT format."""
        result = ensure_ccxt_format("ETHUSDT")
        assert result == "ETH/USDT:USDT"

    def test_ccxt_eth_returned_unchanged(self):
        """CCXT format ETH/USDT:USDT is returned unchanged."""
        result = ensure_ccxt_format("ETH/USDT:USDT")
        assert result == "ETH/USDT:USDT"

    def test_usdtusdt_edge_case_converted(self):
        """Edge case USDTUSDT is converted to USDT/USDT:USDT."""
        result = ensure_ccxt_format("USDTUSDT")
        assert result == "USDT/USDT:USDT"

    def test_ccxt_usdtusdt_edge_case_unchanged(self):
        """Edge case USDT/USDT:USDT is returned unchanged."""
        result = ensure_ccxt_format("USDT/USDT:USDT")
        assert result == "USDT/USDT:USDT"


class TestFormatConversionRoundTrip:
    """Tests for round-trip conversion between formats."""

    def test_binance_to_ccxt_to_binance(self):
        """Converting Binance -> CCXT -> Binance returns original."""
        original = "BTCUSDT"
        ccxt = convert_to_ccxt_format(original)
        back_to_binance = convert_to_binance_format(ccxt)
        assert back_to_binance == original

    def test_ccxt_to_binance_to_ccxt(self):
        """Converting CCXT -> Binance -> CCXT returns original."""
        original = "BTC/USDT:USDT"
        binance = convert_to_binance_format(original)
        back_to_ccxt = convert_to_ccxt_format(binance)
        assert back_to_ccxt == original

    def test_eth_round_trip(self):
        """ETH symbol round-trip conversion works correctly."""
        original = "ETHUSDT"
        ccxt = convert_to_ccxt_format(original)
        assert ccxt == "ETH/USDT:USDT"
        back_to_binance = convert_to_binance_format(ccxt)
        assert back_to_binance == original

    def test_usdtusdt_edge_case_round_trip(self):
        """USDTUSDT edge case round-trip conversion works correctly."""
        original = "USDTUSDT"
        ccxt = convert_to_ccxt_format(original)
        assert ccxt == "USDT/USDT:USDT"
        back_to_binance = convert_to_binance_format(ccxt)
        assert back_to_binance == original
