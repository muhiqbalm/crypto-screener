"""
Utility functions for Exchange Debug API.

This module provides validation and normalization functions for symbol parameters
used in debug API endpoints.
"""

import re
from typing import Optional, Tuple


def validate_symbol(symbol: str) -> Tuple[bool, Optional[str]]:
    """
    Validate symbol parameter for debug API endpoints.
    
    Validates that the symbol:
    - Is not empty or whitespace-only
    - Contains only alphanumeric characters, forward slash (/), and colon (:)
    - Matches either Binance native format (BTCUSDT) or CCXT unified format (BTC/USDT:USDT)
    - Does not exceed maximum length (20 chars for Binance format, 30 chars for CCXT format)
    
    Args:
        symbol: The trading pair symbol to validate
                Binance format: "BTCUSDT", "ETHUSDT"
                CCXT format: "BTC/USDT:USDT", "ETH/USDT:USDT"
    
    Returns:
        tuple: (is_valid, error_message)
            - is_valid (bool): True if symbol is valid, False otherwise
            - error_message (str | None): Descriptive error message if invalid, None if valid
    
    Examples:
        >>> validate_symbol("BTCUSDT")
        (True, None)
        
        >>> validate_symbol("BTC/USDT:USDT")
        (True, None)
        
        >>> validate_symbol("")
        (False, "Symbol parameter is required")
        
        >>> validate_symbol("BTC-USDT")
        (False, "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed")
        
        >>> validate_symbol("BTC//USDT")
        (False, "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)")
        
        >>> validate_symbol("A" * 21)
        (False, "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)")
    """
    # Check for empty or whitespace-only symbol
    if not symbol or symbol.strip() == "":
        return False, "Symbol parameter is required"
    
    # Trim whitespace for further validation
    symbol = symbol.strip()
    
    # Check maximum length (20 for Binance format, 30 for CCXT format)
    if len(symbol) > 30:
        return False, "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"
    
    # Check for allowed characters only (alphanumeric, /, :)
    if not re.match(r'^[A-Za-z0-9/:]+$', symbol):
        return False, "Symbol contains invalid characters. Only alphanumeric, '/', and ':' are allowed"
    
    # Normalize to uppercase for format validation
    symbol_upper = symbol.upper()
    
    # Define format patterns
    binance_pattern = r'^[A-Z0-9]+$'
    ccxt_pattern = r'^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$'
    
    # Check if symbol matches Binance native format
    if re.match(binance_pattern, symbol_upper):
        # Binance format has 20 character limit
        if len(symbol_upper) > 20:
            return False, "Symbol parameter exceeds maximum length (20 characters for Binance format, 30 for CCXT format)"
        return True, None
    
    # Check if symbol matches CCXT unified format
    if re.match(ccxt_pattern, symbol_upper):
        return True, None
    
    # Symbol contains / or : but doesn't match valid format (e.g., BTC//USDT, BTC:USDT/)
    return False, "Symbol format is invalid. Expected Binance format (BTCUSDT) or CCXT format (BTC/USDT:USDT)"


def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol parameter for exchange API requests.
    
    Normalization includes:
    - Trimming leading and trailing whitespace
    - Converting to uppercase
    
    Args:
        symbol: The trading pair symbol to normalize (e.g., "btcusdt", " ETHUSDT ")
    
    Returns:
        str: Normalized symbol in uppercase with whitespace trimmed
    
    Examples:
        >>> normalize_symbol("btcusdt")
        'BTCUSDT'
        
        >>> normalize_symbol(" ETHUSDT ")
        'ETHUSDT'
        
        >>> normalize_symbol("  btc usdt  ")
        'BTC USDT'
    
    Note:
        This function does not validate the symbol. Use validate_symbol() first
        to ensure the symbol meets all requirements.
    """
    return symbol.strip().upper()


def detect_symbol_format(symbol: str) -> str:
    """
    Detect the format of a trading symbol.
    
    Determines whether a symbol is in CCXT unified format or Binance native format
    based on the presence of format-specific characters.
    
    Args:
        symbol: The trading pair symbol to analyze
    
    Returns:
        str: "ccxt" if symbol contains '/' and ':', otherwise "binance"
    
    Examples:
        >>> detect_symbol_format("BTC/USDT:USDT")
        'ccxt'
        
        >>> detect_symbol_format("BTCUSDT")
        'binance'
        
        >>> detect_symbol_format("ETH/USDT:USDT")
        'ccxt'
        
        >>> detect_symbol_format("ETHUSDT")
        'binance'
    
    Note:
        This function assumes the symbol has already been validated.
        It does not perform format validation, only detection.
    """
    if '/' in symbol and ':' in symbol:
        return "ccxt"
    return "binance"


def convert_to_ccxt_format(symbol: str) -> str:
    """
    Convert Binance native format symbol to CCXT unified format.
    
    Converts symbols from Binance native format (BTCUSDT) to CCXT unified format
    (BTC/USDT:USDT) for futures contracts. The conversion assumes USDT-margined
    perpetual futures.
    
    Args:
        symbol: Symbol in Binance native format (e.g., "BTCUSDT", "ETHUSDT")
    
    Returns:
        str: Symbol in CCXT unified format (e.g., "BTC/USDT:USDT", "ETH/USDT:USDT")
    
    Examples:
        >>> convert_to_ccxt_format("BTCUSDT")
        'BTC/USDT:USDT'
        
        >>> convert_to_ccxt_format("ETHUSDT")
        'ETH/USDT:USDT'
        
        >>> convert_to_ccxt_format("USDTUSDT")
        'USDT/USDT:USDT'
        
        >>> convert_to_ccxt_format("BUSDUSDT")
        'BUSD/USDT:USDT'
    
    Note:
        This function assumes the symbol ends with "USDT" and is in Binance native format.
        It should be called after format detection confirms Binance format.
    """
    # Handle edge case where symbol is exactly "USDT" (shouldn't happen in practice)
    if symbol == "USDT":
        return "USDT/USDT:USDT"
    
    # Find the last occurrence of "USDT" to handle edge cases like USDTUSDT
    if symbol.endswith("USDT"):
        # Split at the last USDT occurrence
        base = symbol[:-4]  # Remove the last 4 characters (USDT)
        if base == "":
            # Edge case: symbol is exactly "USDT"
            base = "USDT"
        return f"{base}/USDT:USDT"
    
    # If symbol doesn't end with USDT, return as-is with USDT quote/settle
    # (This shouldn't happen with validated symbols, but provides fallback)
    return f"{symbol}/USDT:USDT"


def convert_to_binance_format(symbol: str) -> str:
    """
    Convert CCXT unified format symbol to Binance native format.
    
    Converts symbols from CCXT unified format (BTC/USDT:USDT) to Binance native
    format (BTCUSDT) by removing the slash and everything after the colon.
    
    Args:
        symbol: Symbol in CCXT unified format (e.g., "BTC/USDT:USDT", "ETH/USDT:USDT")
    
    Returns:
        str: Symbol in Binance native format (e.g., "BTCUSDT", "ETHUSDT")
    
    Examples:
        >>> convert_to_binance_format("BTC/USDT:USDT")
        'BTCUSDT'
        
        >>> convert_to_binance_format("ETH/USDT:USDT")
        'ETHUSDT'
        
        >>> convert_to_binance_format("USDT/USDT:USDT")
        'USDTUSDT'
        
        >>> convert_to_binance_format("BTC/BUSD:BUSD")
        'BTCBUSD'
    
    Note:
        This function assumes the symbol is in valid CCXT unified format.
        It should be called after format detection confirms CCXT format.
    """
    # Split on colon to remove settlement currency
    base_quote = symbol.split(':')[0]
    
    # Remove the slash to get Binance format
    binance_symbol = base_quote.replace('/', '')
    
    return binance_symbol


def ensure_ccxt_format(symbol: str) -> str:
    """
    Ensure a symbol is in CCXT unified format, converting if necessary.
    
    This is a convenience function that detects the current format and converts
    to CCXT unified format if needed. If the symbol is already in CCXT format,
    it returns it unchanged.
    
    Args:
        symbol: Symbol in either Binance native or CCXT unified format
    
    Returns:
        str: Symbol in CCXT unified format
    
    Examples:
        >>> ensure_ccxt_format("BTCUSDT")
        'BTC/USDT:USDT'
        
        >>> ensure_ccxt_format("BTC/USDT:USDT")
        'BTC/USDT:USDT'
        
        >>> ensure_ccxt_format("ETHUSDT")
        'ETH/USDT:USDT'
        
        >>> ensure_ccxt_format("ETH/USDT:USDT")
        'ETH/USDT:USDT'
    
    Note:
        This function is typically used before calling CCXT methods that require
        unified format (e.g., fetch_ticker, fetch_open_interest).
    """
    format_type = detect_symbol_format(symbol)
    
    if format_type == "ccxt":
        return symbol
    else:
        return convert_to_ccxt_format(symbol)
