"""Unit tests for symbol normalization utilities."""

import pytest

from src.services.symbol_utils import normalize_symbol, get_base_symbol


# Default configured symbols list for testing
CONFIGURED_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "AAVE/USDT:USDT",
    "LINK/USDT:USDT",
    "AVAX/USDT:USDT",
    "DOGE/USDT:USDT",
]


class TestNormalizeSymbol:
    """Tests for normalize_symbol function."""

    def test_canonical_format_returned_as_is(self):
        """Already canonical format should be returned unchanged."""
        assert normalize_symbol("BTC/USDT:USDT", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"
        assert normalize_symbol("ETH/USDT:USDT", CONFIGURED_SYMBOLS) == "ETH/USDT:USDT"

    def test_spot_format_normalized(self):
        """Spot format (BTC/USDT) should be normalized to futures format."""
        assert normalize_symbol("BTC/USDT", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"
        assert normalize_symbol("ETH/USDT", CONFIGURED_SYMBOLS) == "ETH/USDT:USDT"

    def test_concatenated_format_normalized(self):
        """Concatenated format (BTCUSDT) should be normalized to futures format."""
        assert normalize_symbol("BTCUSDT", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"
        assert normalize_symbol("ETHUSDT", CONFIGURED_SYMBOLS) == "ETH/USDT:USDT"
        assert normalize_symbol("SOLUSDT", CONFIGURED_SYMBOLS) == "SOL/USDT:USDT"

    def test_case_insensitive(self):
        """Lowercase input should be normalized correctly."""
        assert normalize_symbol("btcusdt", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"
        assert normalize_symbol("eth/usdt", CONFIGURED_SYMBOLS) == "ETH/USDT:USDT"
        assert normalize_symbol("sol/usdt:usdt", CONFIGURED_SYMBOLS) == "SOL/USDT:USDT"

    def test_base_symbol_only(self):
        """Base symbol (BTC) should be normalized to futures format."""
        assert normalize_symbol("BTC", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"
        assert normalize_symbol("ETH", CONFIGURED_SYMBOLS) == "ETH/USDT:USDT"
        assert normalize_symbol("DOGE", CONFIGURED_SYMBOLS) == "DOGE/USDT:USDT"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped."""
        assert normalize_symbol("  BTC/USDT:USDT  ", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"
        assert normalize_symbol(" BTCUSDT ", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"

    def test_unknown_symbol_returns_none(self):
        """Symbols not in configured list should return None."""
        assert normalize_symbol("XRP/USDT:USDT", CONFIGURED_SYMBOLS) is None
        assert normalize_symbol("XRPUSDT", CONFIGURED_SYMBOLS) is None
        assert normalize_symbol("UNKNOWN", CONFIGURED_SYMBOLS) is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        assert normalize_symbol("", CONFIGURED_SYMBOLS) is None
        assert normalize_symbol("   ", CONFIGURED_SYMBOLS) is None

    def test_empty_configured_list_returns_none(self):
        """Empty configured symbols list should always return None."""
        assert normalize_symbol("BTC/USDT:USDT", []) is None

    def test_none_like_input(self):
        """Edge case inputs should return None gracefully."""
        assert normalize_symbol("", CONFIGURED_SYMBOLS) is None

    def test_mixed_case_canonical(self):
        """Mixed case canonical format should be normalized."""
        assert normalize_symbol("Btc/Usdt:Usdt", CONFIGURED_SYMBOLS) == "BTC/USDT:USDT"

    def test_all_configured_symbols_match(self):
        """Every configured symbol should normalize to itself."""
        for sym in CONFIGURED_SYMBOLS:
            assert normalize_symbol(sym, CONFIGURED_SYMBOLS) == sym


class TestGetBaseSymbol:
    """Tests for get_base_symbol function."""

    def test_extracts_base_from_futures_format(self):
        """Should extract base symbol from canonical futures format."""
        assert get_base_symbol("BTC/USDT:USDT") == "BTC"
        assert get_base_symbol("ETH/USDT:USDT") == "ETH"
        assert get_base_symbol("DOGE/USDT:USDT") == "DOGE"

    def test_extracts_base_from_spot_format(self):
        """Should extract base symbol from spot format."""
        assert get_base_symbol("BTC/USDT") == "BTC"
        assert get_base_symbol("SOL/USDT") == "SOL"

    def test_returns_input_when_no_slash(self):
        """Should return input unchanged when no slash present."""
        assert get_base_symbol("BTC") == "BTC"
        assert get_base_symbol("BTCUSDT") == "BTCUSDT"
