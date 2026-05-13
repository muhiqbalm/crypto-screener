"""
Utility functions for Exchange Debug API.

This module provides validation and normalization functions for symbol parameters
used in debug API endpoints.
"""

from typing import Optional, Tuple


def validate_symbol(symbol: str) -> Tuple[bool, Optional[str]]:
    """
    Validate symbol parameter for debug API endpoints.
    
    Validates that the symbol:
    - Is not empty or whitespace-only
    - Contains only alphanumeric characters
    - Does not exceed 20 characters in length
    
    Args:
        symbol: The trading pair symbol to validate (e.g., "BTCUSDT", "ETHUSDT")
    
    Returns:
        tuple: (is_valid, error_message)
            - is_valid (bool): True if symbol is valid, False otherwise
            - error_message (str | None): Descriptive error message if invalid, None if valid
    
    Examples:
        >>> validate_symbol("BTCUSDT")
        (True, None)
        
        >>> validate_symbol("")
        (False, "Symbol parameter is required")
        
        >>> validate_symbol("BTC-USDT")
        (False, "Symbol must contain only alphanumeric characters")
        
        >>> validate_symbol("A" * 21)
        (False, "Symbol parameter exceeds maximum length")
    """
    # Check for empty or whitespace-only symbol
    if not symbol or symbol.strip() == "":
        return False, "Symbol parameter is required"
    
    # Trim whitespace for further validation
    symbol = symbol.strip()
    
    # Check maximum length (20 characters)
    if len(symbol) > 20:
        return False, "Symbol parameter exceeds maximum length"
    
    # Check for alphanumeric characters only
    if not symbol.isalnum():
        return False, "Symbol must contain only alphanumeric characters"
    
    return True, None


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
