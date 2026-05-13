"""Tests for debug_utils module (src/api/debug_utils.py).

Validates:
- validate_symbol() correctly validates symbol parameters
- normalize_symbol() correctly normalizes symbol parameters
- Requirements 11.1, 11.2, 11.3, 11.4, 11.5
"""

import pytest

from src.api.debug_utils import normalize_symbol, validate_symbol


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
        """Symbol with hyphen returns (False, 'Symbol must contain only alphanumeric characters')."""
        is_valid, error = validate_symbol("BTC-USDT")
        assert is_valid is False
        assert error == "Symbol must contain only alphanumeric characters"

    def test_symbol_with_underscore_returns_error(self):
        """Symbol with underscore returns (False, 'Symbol must contain only alphanumeric characters')."""
        is_valid, error = validate_symbol("BTC_USDT")
        assert is_valid is False
        assert error == "Symbol must contain only alphanumeric characters"

    def test_symbol_with_slash_returns_error(self):
        """Symbol with slash returns (False, 'Symbol must contain only alphanumeric characters')."""
        is_valid, error = validate_symbol("BTC/USDT")
        assert is_valid is False
        assert error == "Symbol must contain only alphanumeric characters"

    def test_symbol_with_special_chars_returns_error(self):
        """Symbol with special characters returns (False, 'Symbol must contain only alphanumeric characters')."""
        is_valid, error = validate_symbol("BTC@USDT")
        assert is_valid is False
        assert error == "Symbol must contain only alphanumeric characters"

    def test_symbol_exceeding_max_length_returns_error(self):
        """Symbol exceeding 20 characters returns (False, 'Symbol parameter exceeds maximum length')."""
        is_valid, error = validate_symbol("A" * 21)
        assert is_valid is False
        assert error == "Symbol parameter exceeds maximum length"

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
        assert error == "Symbol parameter exceeds maximum length"

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
        assert error == "Symbol must contain only alphanumeric characters"
        
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
