"""Symbol normalization utilities for the crypto screener API.

Handles conversion of various symbol formats to canonical CCXT futures format.
Supported input formats:
- BTCUSDT (concatenated)
- BTC/USDT (spot format)
- BTC/USDT:USDT (full futures format)
- btcusdt (case-insensitive)
"""

from typing import Optional


def normalize_symbol(symbol: str, configured_symbols: list[str]) -> Optional[str]:
    """Normalize a symbol string to canonical CCXT futures format.

    Attempts to match the input symbol against the configured symbols list
    using multiple format transformations.

    Args:
        symbol: Input symbol in any accepted format.
        configured_symbols: List of valid symbols in canonical format (e.g., "BTC/USDT:USDT").

    Returns:
        The canonical CCXT futures format string if matched, or None if not found.
    """
    if not symbol or not configured_symbols:
        return None

    # Step 1: Strip whitespace and convert to uppercase
    cleaned = symbol.strip().upper()

    if not cleaned:
        return None

    # Step 2: If already in configured list, return as-is
    if cleaned in configured_symbols:
        return cleaned

    # Step 3: Try adding "/USDT:USDT" suffix (handles "BTC" → "BTC/USDT:USDT")
    candidate = f"{cleaned}/USDT:USDT"
    if candidate in configured_symbols:
        return candidate

    # Step 4: Try adding ":USDT" suffix (handles "BTC/USDT" → "BTC/USDT:USDT")
    candidate = f"{cleaned}:USDT"
    if candidate in configured_symbols:
        return candidate

    # Step 5: Try parsing concatenated format (handles "BTCUSDT" → "BTC/USDT:USDT")
    if cleaned.endswith("USDT") and "/" not in cleaned and ":" not in cleaned:
        base = cleaned[:-4]  # Remove "USDT" suffix
        if base:
            candidate = f"{base}/USDT:USDT"
            if candidate in configured_symbols:
                return candidate

    # Step 6: No match found
    return None


def get_base_symbol(canonical: str) -> str:
    """Extract the base asset symbol from a canonical CCXT futures format string.

    Args:
        canonical: Symbol in canonical format (e.g., "BTC/USDT:USDT").

    Returns:
        The base asset symbol (e.g., "BTC").
    """
    if "/" in canonical:
        return canonical.split("/")[0]
    return canonical
