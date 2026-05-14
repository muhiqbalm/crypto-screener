"""
Debug Exchange Service Module

Provides diagnostic and debugging capabilities for monitoring raw responses
from the Binance Futures exchange API.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Union, List
import ccxt
import requests
from src.exchange.connector import ExchangeConnector
from src.api.debug_models import (
    DebugResponse, 
    RequestMetadata, 
    ErrorInfo, 
    AggregatedDebugResponse, 
    DataTypeResult,
    HealthCheckResponse
)
from src.api.debug_utils import validate_symbol, normalize_symbol, ensure_ccxt_format

logger = logging.getLogger(__name__)

# Sensitive field names that should be filtered from responses
SENSITIVE_FIELDS = {
    'apikey', 'api_key',
    'secret', 'apisecret', 'api_secret',
    'password', 'pass', 'pwd',
    'privatekey', 'private_key',
    'token', 'authorization',
    'accesstoken', 'access_token',
    'refreshtoken', 'refresh_token',
    'bearer', 'credential'
}


def sanitize_response_data(data: Any) -> Any:
    """
    Recursively sanitize response data to remove sensitive fields.
    
    This function removes API keys, secrets, passwords, tokens, and other
    sensitive credentials from response data to prevent accidental exposure.
    
    Args:
        data: Response data to sanitize (dict, list, or primitive type)
    
    Returns:
        Sanitized data with sensitive fields removed
    """
    if data is None:
        return None
    
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            # Check if key name indicates sensitive data (case-insensitive)
            key_lower = key.lower().replace('-', '').replace('_', '')
            if key_lower in SENSITIVE_FIELDS:
                # Replace sensitive value with redacted marker
                sanitized[key] = "[REDACTED]"
                logger.debug(f"Redacted sensitive field: {key}")
            else:
                # Recursively sanitize nested structures
                sanitized[key] = sanitize_response_data(value)
        return sanitized
    
    elif isinstance(data, list):
        # Recursively sanitize list items
        return [sanitize_response_data(item) for item in data]
    
    else:
        # Primitive types (str, int, float, bool, None) are returned as-is
        return data


def _extract_network_error_details(error: Exception) -> str:
    """
    Extract specific error details from a NetworkError exception.
    
    Analyzes the error message to determine the specific type of connectivity issue
    (DNS resolution failure, connection refused, network unreachable, etc.).
    
    Args:
        error: The NetworkError exception
    
    Returns:
        str: Specific error details (e.g., "DNS resolution failed", "Connection refused")
    """
    error_str = str(error).lower()
    
    # Check for DNS resolution errors
    if "getaddrinfo failed" in error_str or "name resolution" in error_str or "dns" in error_str:
        return "DNS resolution failed"
    
    # Check for connection refused errors
    if "connection refused" in error_str or "refused" in error_str:
        return "Connection refused"
    
    # Check for network unreachable errors
    if "network unreachable" in error_str or "unreachable" in error_str:
        return "Network unreachable"
    
    # Check for timeout-related network errors
    if "timeout" in error_str or "timed out" in error_str:
        return "Connection timeout"
    
    # Default to generic connectivity error
    return "Cannot connect to exchange"


class DebugExchangeService:
    """
    Service for retrieving raw exchange data with field mapping documentation.
    
    This service provides diagnostic capabilities by exposing unprocessed
    exchange responses along with metadata about which fields are used by
    the application.
    """
    
    def __init__(self, exchange_connector: ExchangeConnector):
        """
        Initialize the DebugExchangeService.
        
        Args:
            exchange_connector: ExchangeConnector instance for accessing the exchange
        """
        self.exchange = exchange_connector.get_exchange()
        self.field_mappings = self._initialize_field_mappings()
        logger.info("DebugExchangeService initialized")
    
    def _initialize_field_mappings(self) -> Dict[str, Dict[str, Any]]:
        """
        Initialize field mapping documentation for all data types.
        
        Field mappings document which exchange fields are used by the application,
        including the application field name, whether the field is required,
        the expected data type, and any transformations applied.
        
        Returns:
            dict: Dictionary containing field mappings for ticker, open interest,
                  funding rate, and long/short ratio data types
        """
        return {
            "ticker": {
                "last": {
                    "app_field": "price",
                    "required": True,
                    "data_type": "float",
                    "description": "Most recent trade price"
                },
                "percentage": {
                    "app_field": "change_24h",
                    "required": True,
                    "data_type": "float",
                    "description": "24-hour percentage change"
                },
                "quoteVolume": {
                    "app_field": "volume_24h",
                    "required": True,
                    "data_type": "float",
                    "description": "24-hour trading volume in quote currency (USDT)"
                },
                "baseVolume": {
                    "app_field": "volume_24h",
                    "required": False,
                    "data_type": "float",
                    "description": "Fallback: 24-hour trading volume in base currency"
                }
            },
            "openInterest": {
                "openInterestAmount": {
                    "app_field": "open_interest",
                    "required": False,
                    "data_type": "float",
                    "description": "Total outstanding derivative contracts"
                },
                "openInterest": {
                    "app_field": "open_interest",
                    "required": False,
                    "data_type": "float",
                    "description": "Fallback field for open interest"
                }
            },
            "fundingRate": {
                "fundingRate": {
                    "app_field": "funding_rate",
                    "required": True,
                    "data_type": "float",
                    "description": "Funding rate as decimal (e.g., 0.0001)",
                    "transformation": "Multiply by 100 to convert to percentage"
                }
            },
            "longShortRatio": {
                "longShortRatio": {
                    "app_field": "long_short_ratio",
                    "required": True,
                    "data_type": "float",
                    "description": "Ratio of long positions to short positions from Binance top trader data"
                }
            }
        }
    
    async def fetch_raw_ticker(self, symbol: str) -> DebugResponse:
        """
        Fetch raw ticker data from the exchange with timing and field mapping.
        
        This method retrieves unprocessed ticker data from the Binance Futures API,
        including price, volume, and 24-hour change information. The response includes
        request/response timing metrics and field mapping documentation.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT")
        
        Returns:
            DebugResponse: Response containing raw ticker data, metadata, and field mappings
        
        Raises:
            No exceptions are raised - all errors are captured in the DebugResponse
        """
        # Record request timestamp
        request_timestamp = datetime.utcnow()
        
        try:
            # Validate symbol
            is_valid, error_message = validate_symbol(symbol)
            if not is_valid:
                response_timestamp = datetime.utcnow()
                response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
                
                return DebugResponse(
                    success=False,
                    error=ErrorInfo(
                        message=error_message,
                        code="INVALID_INPUT"
                    ),
                    metadata=RequestMetadata(
                        request_timestamp=request_timestamp,
                        response_timestamp=response_timestamp,
                        response_time_ms=round(response_time_ms, 2),
                        exchange="binanceusdm"
                    )
                )
            
            # Normalize symbol (uppercase and trim)
            normalized_symbol = normalize_symbol(symbol)
            
            # Convert to CCXT unified format (fetch_ticker requires CCXT format)
            ccxt_symbol = ensure_ccxt_format(normalized_symbol)
            
            # Call exchange API to fetch ticker
            logger.info(f"Fetching raw ticker data for symbol: {normalized_symbol} (CCXT format: {ccxt_symbol})")
            raw_data = self.exchange.fetch_ticker(ccxt_symbol)
            
            # Sanitize response data to remove sensitive fields
            sanitized_data = sanitize_response_data(raw_data)
            
            # Record response timestamp
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.info(f"Successfully fetched ticker data for {normalized_symbol} in {response_time_ms:.2f}ms")
            
            # Build successful response
            return DebugResponse(
                success=True,
                data=sanitized_data,
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=200,
                    exchange="binanceusdm"
                ),
                fieldMapping=self.field_mappings["ticker"]
            )
        
        except ccxt.AuthenticationError as e:
            # Authentication error (401) - when auth is enabled and credentials are invalid/missing
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Authentication error fetching ticker for {symbol}: {str(e)}", exc_info=True)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message="Authentication required",
                    code="UNAUTHORIZED"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=401,
                    exchange="binanceusdm"
                )
            )
        
        except ccxt.RequestTimeout as e:
            # Timeout error (504) - must be before NetworkError since RequestTimeout is a subclass
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Request timeout fetching ticker for {symbol}: {str(e)}", exc_info=True)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message="Gateway timeout: Exchange request timed out",
                    code="GATEWAY_TIMEOUT",
                    timeout_duration_ms=round(response_time_ms, 2)
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=504,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.NetworkError as e:
            # Network/connectivity error (503)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Network error fetching ticker for {symbol}: {str(e)}", exc_info=True)
            
            # Extract specific error details
            error_details = _extract_network_error_details(e)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message=f"Service unavailable: {str(e)}",
                    code="SERVICE_UNAVAILABLE",
                    details=error_details
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.ExchangeError as e:
            # Exchange-specific error (4xx or 5xx)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Exchange error fetching ticker for {symbol}: {str(e)}", exc_info=True)
            
            # Try to extract status code from exception
            http_status = 502  # Default to Bad Gateway
            if hasattr(e, 'status_code'):
                http_status = e.status_code
            
            # Determine error code based on HTTP status
            # 5xx errors are server errors, 4xx are client errors
            if http_status >= 500 and http_status < 600:
                error_code = "EXCHANGE_SERVER_ERROR"
                error_message = f"Exchange server error: {str(e)}"
            else:
                error_code = "EXCHANGE_ERROR"
                error_message = f"Exchange error: {str(e)}"
            
            # Try to preserve original exchange error response
            error_data = None
            try:
                if hasattr(e, 'response'):
                    # Sanitize error response to remove sensitive fields
                    error_data = sanitize_response_data(e.response)
            except Exception:
                pass
            
            return DebugResponse(
                success=False,
                data=error_data,
                error=ErrorInfo(
                    message=error_message,
                    code=error_code
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=http_status,
                    exchange="binanceusdm"
                )
            )
            
        except Exception as e:
            # Unexpected internal error (500)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Unexpected error fetching ticker for {symbol}: {str(e)}", exc_info=True)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message="Internal server error: An unexpected error occurred",
                    code="INTERNAL_ERROR"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=500,
                    exchange="binanceusdm"
                )
            )

    async def fetch_raw_open_interest(self, symbol: str) -> DebugResponse:
        """
        Fetch raw open interest data from the exchange with timing and field mapping.
        
        This method retrieves unprocessed open interest data from the Binance Futures API,
        showing the total number of outstanding derivative contracts. The response includes
        request/response timing metrics and field mapping documentation.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT")
        
        Returns:
            DebugResponse: Response containing raw open interest data, metadata, and field mappings
        
        Raises:
            No exceptions are raised - all errors are captured in the DebugResponse
        """
        # Record request timestamp
        request_timestamp = datetime.utcnow()
        
        try:
            # Validate symbol
            is_valid, error_message = validate_symbol(symbol)
            if not is_valid:
                response_timestamp = datetime.utcnow()
                response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
                
                return DebugResponse(
                    success=False,
                    error=ErrorInfo(
                        message=error_message,
                        code="INVALID_INPUT"
                    ),
                    metadata=RequestMetadata(
                        request_timestamp=request_timestamp,
                        response_timestamp=response_timestamp,
                        response_time_ms=round(response_time_ms, 2),
                        exchange="binanceusdm"
                    )
                )
            
            # Normalize symbol (uppercase and trim)
            normalized_symbol = normalize_symbol(symbol)
            
            # Convert to CCXT unified format (fetch_open_interest requires CCXT format)
            ccxt_symbol = ensure_ccxt_format(normalized_symbol)
            
            # Call exchange API to fetch open interest
            logger.info(f"Fetching raw open interest data for symbol: {normalized_symbol} (CCXT format: {ccxt_symbol})")
            raw_data = self.exchange.fetch_open_interest(ccxt_symbol)
            
            # Sanitize response data to remove sensitive fields
            sanitized_data = sanitize_response_data(raw_data)
            
            # Record response timestamp
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.info(f"Successfully fetched open interest data for {normalized_symbol} in {response_time_ms:.2f}ms")
            
            # Build successful response
            return DebugResponse(
                success=True,
                data=sanitized_data,
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=200,
                    exchange="binanceusdm"
                ),
                fieldMapping=self.field_mappings["openInterest"]
            )
            
        except ccxt.AuthenticationError as e:
            # Authentication error (401) - when auth is enabled and credentials are invalid/missing
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Authentication error fetching open interest for {symbol}: {str(e)}", exc_info=True)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message="Authentication required",
                    code="UNAUTHORIZED"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=401,
                    exchange="binanceusdm"
                )
            )
        
        except ccxt.RequestTimeout as e:
            # Timeout error (504) - must come before NetworkError since it's a subclass
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Request timeout fetching open interest for {symbol}: {str(e)}", exc_info=True)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message="Gateway timeout: Exchange request timed out",
                    code="GATEWAY_TIMEOUT",
                    timeout_duration_ms=round(response_time_ms, 2)
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=504,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.NetworkError as e:
            # Network/connectivity error (503)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Network error fetching open interest for {symbol}: {str(e)}", exc_info=True)
            
            # Extract specific error details
            error_details = _extract_network_error_details(e)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message=f"Service unavailable: {str(e)}",
                    code="SERVICE_UNAVAILABLE",
                    details=error_details
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.ExchangeError as e:
            # Exchange-specific error (4xx or 5xx)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Exchange error fetching open interest for {symbol}: {str(e)}", exc_info=True)
            
            # Try to extract status code from exception
            http_status = 502  # Default to Bad Gateway
            if hasattr(e, 'status_code'):
                http_status = e.status_code
            
            # Determine error code based on HTTP status
            # 5xx errors are server errors, 4xx are client errors
            if http_status >= 500 and http_status < 600:
                error_code = "EXCHANGE_SERVER_ERROR"
                error_message = f"Exchange server error: {str(e)}"
            else:
                error_code = "EXCHANGE_ERROR"
                error_message = f"Exchange error: {str(e)}"
            
            # Try to preserve original exchange error response
            error_data = None
            try:
                if hasattr(e, 'response'):
                    # Sanitize error response to remove sensitive fields
                    error_data = sanitize_response_data(e.response)
            except Exception:
                pass
            
            return DebugResponse(
                success=False,
                data=error_data,
                error=ErrorInfo(
                    message=error_message,
                    code=error_code
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=http_status,
                    exchange="binanceusdm"
                )
            )
            
        except Exception as e:
            # Unexpected internal error (500)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Unexpected error fetching open interest for {symbol}: {str(e)}", exc_info=True)
            
            return DebugResponse(
                success=False,
                error=ErrorInfo(
                    message="Internal server error: An unexpected error occurred",
                    code="INTERNAL_ERROR"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=500,
                    exchange="binanceusdm"
                )
            )

    def fetch_raw_funding_rate(self, symbol: str) -> DebugResponse:
        """
        Fetch raw funding rate data from the exchange with timing and field mapping.
        
        This method retrieves unprocessed funding rate data from the Binance Futures API,
        including request/response timing metrics and field mapping documentation.
        
        NOTE: Symbol format handling - This endpoint accepts both CCXT unified format
        (BTC/USDT:USDT) and Binance native format (BTCUSDT). The CCXT fetch_funding_rate()
        method handles format conversion internally, so no explicit conversion is needed here.
        This endpoint is NOT affected by the symbol format bug fix.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT")
        
        Returns:
            DebugResponse: Response containing raw funding rate data, metadata,
                          and field mappings, or error information if the request fails
        
        Examples:
            >>> service = DebugExchangeService(exchange_connector)
            >>> response = service.fetch_raw_funding_rate("BTCUSDT")
            >>> print(response.data['fundingRate'])
            0.0001
        """
        # Validate symbol parameter
        is_valid, error_message = validate_symbol(symbol)
        if not is_valid:
            # Return error response for invalid symbol
            request_time = datetime.now()
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message=error_message,
                    code="INVALID_INPUT"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_time,
                    response_timestamp=request_time,
                    response_time_ms=0.0,
                    http_status=400,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
        
        # Normalize symbol (trim whitespace and convert to uppercase)
        normalized_symbol = normalize_symbol(symbol)
        
        # Record request timestamp
        request_timestamp = datetime.now()
        
        try:
            # Call exchange API to fetch funding rate
            raw_data = self.exchange.fetch_funding_rate(normalized_symbol)
            
            # Sanitize response data to remove sensitive fields
            sanitized_data = sanitize_response_data(raw_data)
            
            # Record response timestamp
            response_timestamp = datetime.now()
            
            # Calculate response time in milliseconds
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            # Build successful response
            return DebugResponse(
                success=True,
                data=sanitized_data,
                error=None,
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=200,
                    exchange="binanceusdm"
                ),
                fieldMapping=self.field_mappings["fundingRate"]
            )
            
        except ccxt.AuthenticationError as e:
            # Handle authentication errors (401) - when auth is enabled and credentials are invalid/missing
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Authentication error fetching funding rate for {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message="Authentication required",
                    code="UNAUTHORIZED"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=401,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
        
        except ccxt.RequestTimeout as e:
            # Handle timeout errors (504)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Request timeout fetching funding rate for {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message="Gateway timeout: Exchange request timed out",
                    code="GATEWAY_TIMEOUT",
                    timeout_duration_ms=round(response_time_ms, 2)
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=504,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except ccxt.NetworkError as e:
            # Handle network/connectivity errors (503)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Network error fetching funding rate for {normalized_symbol}: {e}", exc_info=True)
            
            # Extract specific error details
            error_details = _extract_network_error_details(e)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message=f"Service unavailable: {str(e)}",
                    code="SERVICE_UNAVAILABLE",
                    details=error_details
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except ccxt.ExchangeError as e:
            # Handle exchange-specific errors (4xx or 5xx)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Exchange error fetching funding rate for {normalized_symbol}: {e}", exc_info=True)
            
            # Try to extract status code from exception
            http_status = 502  # Default to Bad Gateway
            if hasattr(e, 'status_code'):
                http_status = e.status_code
            
            # Determine error code based on HTTP status
            # 5xx errors are server errors, 4xx are client errors
            if http_status >= 500 and http_status < 600:
                error_code = "EXCHANGE_SERVER_ERROR"
                error_message = f"Exchange server error: {str(e)}"
            else:
                error_code = "EXCHANGE_ERROR"
                error_message = f"Exchange error: {str(e)}"
            
            # Try to preserve original exchange error response
            error_data = None
            try:
                if hasattr(e, 'response'):
                    # Sanitize error response to remove sensitive fields
                    error_data = sanitize_response_data(e.response)
            except Exception:
                pass
            
            return DebugResponse(
                success=False,
                data=error_data,
                error=ErrorInfo(
                    message=error_message,
                    code=error_code
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=http_status,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except Exception as e:
            # Handle unexpected errors (500)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Unexpected error fetching funding rate for {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message="Internal server error: An unexpected error occurred",
                    code="INTERNAL_ERROR"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=500,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )

    def fetch_raw_long_short_ratio(self, symbol: str) -> DebugResponse:
        """
        Fetch raw long/short ratio data from the exchange with timing and field mapping.
        
        This method retrieves unprocessed long/short ratio data from the Binance Futures API
        using a direct HTTP request (not available in CCXT). The long/short ratio represents
        the ratio of long positions to short positions from Binance top trader data.
        
        NOTE: Symbol format handling - This endpoint already has correct format conversion logic.
        It uses self.exchange.market(normalized_symbol) to look up the market and extracts
        market['id'] to get the Binance native format (BTCUSDT) required by the direct Binance
        API endpoint. This conversion logic works with both CCXT unified format (BTC/USDT:USDT)
        and Binance native format (BTCUSDT) inputs. This endpoint is NOT affected by the symbol
        format bug fix - the existing market lookup handles conversion correctly.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT")
        
        Returns:
            DebugResponse: Response containing raw long/short ratio data, metadata,
                          and field mappings, or error information if the request fails
        
        Examples:
            >>> service = DebugExchangeService(exchange_connector)
            >>> response = service.fetch_raw_long_short_ratio("BTCUSDT")
            >>> print(response.data[0]['longShortRatio'])
            1.5
        """
        # Validate symbol parameter
        is_valid, error_message = validate_symbol(symbol)
        if not is_valid:
            # Return error response for invalid symbol
            request_time = datetime.now()
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message=error_message,
                    code="INVALID_INPUT"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_time,
                    response_timestamp=request_time,
                    response_time_ms=0.0,
                    http_status=400,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
        
        # Normalize symbol (trim whitespace and convert to uppercase)
        normalized_symbol = normalize_symbol(symbol)
        
        # Record request timestamp
        request_timestamp = datetime.now()
        
        try:
            # Get Binance symbol format (e.g., 'BTCUSDT' without slashes)
            # The exchange.market() method returns market info including the exchange-specific symbol ID
            market = self.exchange.market(normalized_symbol)
            binance_symbol = market['id']  # e.g., 'BTCUSDT'
            
            # Binance Futures API endpoint for top trader long/short ratio
            url = 'https://fapi.binance.com/futures/data/topLongShortAccountRatio'
            params = {
                'symbol': binance_symbol,
                'period': '5m',  # 5-minute period
                'limit': 1  # Get only the most recent data point
            }
            
            # Make direct HTTP request to Binance API
            logger.info(f"Fetching raw long/short ratio data for symbol: {binance_symbol}")
            response = requests.get(url, params=params, timeout=10)
            
            # Record response timestamp
            response_timestamp = datetime.now()
            
            # Calculate response time in milliseconds
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            # Check HTTP status code
            response.raise_for_status()
            
            # Parse JSON response
            raw_data = response.json()
            
            # Sanitize response data to remove sensitive fields
            sanitized_data = sanitize_response_data(raw_data)
            
            logger.info(f"Successfully fetched long/short ratio data for {binance_symbol} in {response_time_ms:.2f}ms")
            
            # Build successful response
            # Note: Binance API returns a list, but we wrap it in a dict for consistency with DebugResponse model
            return DebugResponse(
                success=True,
                data={"result": sanitized_data} if isinstance(sanitized_data, list) else sanitized_data,
                error=None,
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=response.status_code,
                    exchange="binanceusdm"
                ),
                fieldMapping=self.field_mappings["longShortRatio"]
            )
            
        except ccxt.AuthenticationError as e:
            # Handle authentication errors from CCXT market lookup (401)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Authentication error fetching long/short ratio for {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message="Authentication required",
                    code="UNAUTHORIZED"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=401,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
        
        except requests.exceptions.Timeout as e:
            # Handle timeout errors (504)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Request timeout fetching long/short ratio for {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message="Gateway timeout: Exchange request timed out",
                    code="GATEWAY_TIMEOUT",
                    timeout_duration_ms=round(response_time_ms, 2)
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=504,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except requests.exceptions.ConnectionError as e:
            # Handle network/connectivity errors (503)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Network error fetching long/short ratio for {normalized_symbol}: {e}", exc_info=True)
            
            # Extract specific error details
            error_details = _extract_network_error_details(e)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message=f"Service unavailable: Cannot connect to exchange",
                    code="SERVICE_UNAVAILABLE",
                    details=error_details
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except requests.exceptions.HTTPError as e:
            # Handle HTTP errors from Binance API (4xx or 5xx)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"HTTP error fetching long/short ratio for {normalized_symbol}: {e}", exc_info=True)
            
            # Try to preserve original exchange error response
            error_data = None
            http_status = 502  # Default to Bad Gateway
            try:
                if hasattr(e, 'response') and e.response is not None:
                    http_status = e.response.status_code
                    try:
                        # Sanitize error response to remove sensitive fields
                        error_data = sanitize_response_data(e.response.json())
                    except Exception:
                        error_data = {"error": e.response.text}
            except Exception:
                pass
            
            # Determine error code based on HTTP status
            # 401 is authentication error
            # 5xx errors are server errors, 4xx are client errors
            if http_status == 401:
                error_code = "UNAUTHORIZED"
                error_message = "Authentication required"
            elif http_status >= 500 and http_status < 600:
                error_code = "EXCHANGE_SERVER_ERROR"
                error_message = f"Exchange server error: {str(e)}"
            else:
                error_code = "EXCHANGE_ERROR"
                error_message = f"Exchange error: {str(e)}"
            
            return DebugResponse(
                success=False,
                data=error_data,
                error=ErrorInfo(
                    message=error_message,
                    code=error_code
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=http_status,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except ccxt.BadSymbol as e:
            # Handle invalid symbol errors from CCXT market lookup
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Invalid symbol for long/short ratio: {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message=f"Invalid symbol: {str(e)}",
                    code="INVALID_INPUT"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=400,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )
            
        except Exception as e:
            # Handle unexpected errors (500)
            response_timestamp = datetime.now()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Unexpected error fetching long/short ratio for {normalized_symbol}: {e}", exc_info=True)
            
            return DebugResponse(
                success=False,
                data=None,
                error=ErrorInfo(
                    message="Internal server error: An unexpected error occurred",
                    code="INTERNAL_ERROR"
                ),
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=500,
                    exchange="binanceusdm"
                ),
                fieldMapping=None
            )

    async def fetch_all_raw_data(self, symbol: str) -> AggregatedDebugResponse:
        """
        Fetch all raw data types concurrently for a given symbol.
        
        This method executes all four fetch methods (ticker, open interest, funding rate,
        and long/short ratio) concurrently using asyncio.gather(). Each fetch call has
        individual error handling to prevent one failure from blocking others.
        
        NOTE: Symbol format handling - This endpoint accepts both CCXT unified format
        (BTC/USDT:USDT) and Binance native format (BTCUSDT). Format conversion is handled
        automatically by the individual fetch methods:
        - fetch_raw_ticker() and fetch_raw_open_interest() convert to CCXT format
        - fetch_raw_funding_rate() accepts both formats (CCXT handles internally)
        - fetch_raw_long_short_ratio() uses market lookup for conversion
        No explicit format conversion is needed in this aggregated method.
        
        Args:
            symbol: Trading pair symbol in either format (e.g., "BTCUSDT" or "BTC/USDT:USDT")
        
        Returns:
            AggregatedDebugResponse: Response containing results for all four data types,
                                    individual timing information, and field mappings
        
        Examples:
            >>> service = DebugExchangeService(exchange_connector)
            >>> response = await service.fetch_all_raw_data("BTCUSDT")
            >>> print(response.data['ticker'].success)
            True
            >>> print(response.metadata['individual_timings']['ticker_ms'])
            150.25
            
            >>> response = await service.fetch_all_raw_data("BTC/USDT:USDT")
            >>> print(response.data['ticker'].success)
            True
        """
        # Validate symbol once before all requests
        is_valid, error_message = validate_symbol(symbol)
        if not is_valid:
            # Return error response for invalid symbol
            request_time = datetime.utcnow()
            return AggregatedDebugResponse(
                success=False,
                data={
                    "ticker": DataTypeResult(success=False, data=None, error=ErrorInfo(message=error_message, code="INVALID_INPUT")),
                    "openInterest": DataTypeResult(success=False, data=None, error=ErrorInfo(message=error_message, code="INVALID_INPUT")),
                    "fundingRate": DataTypeResult(success=False, data=None, error=ErrorInfo(message=error_message, code="INVALID_INPUT")),
                    "longShortRatio": DataTypeResult(success=False, data=None, error=ErrorInfo(message=error_message, code="INVALID_INPUT"))
                },
                metadata={
                    "request_timestamp": request_time.isoformat(),
                    "response_timestamp": request_time.isoformat(),
                    "total_response_time_ms": 0.0,
                    "individual_timings": {
                        "ticker_ms": 0.0,
                        "open_interest_ms": 0.0,
                        "funding_rate_ms": 0.0,
                        "long_short_ratio_ms": 0.0
                    }
                },
                fieldMapping={
                    "ticker": self.field_mappings["ticker"],
                    "openInterest": self.field_mappings["openInterest"],
                    "fundingRate": self.field_mappings["fundingRate"],
                    "longShortRatio": self.field_mappings["longShortRatio"]
                }
            )
        
        # Record overall request timestamp
        overall_request_timestamp = datetime.utcnow()
        
        # Normalize symbol (uppercase and trim)
        normalized_symbol = normalize_symbol(symbol)
        
        logger.info(f"Fetching all raw data types concurrently for symbol: {normalized_symbol}")
        
        # Define wrapper functions with individual error handling for each data type
        async def fetch_ticker_safe():
            """Wrapper for ticker fetch with error handling."""
            try:
                start_time = datetime.utcnow()
                result = await self.fetch_raw_ticker(normalized_symbol)
                end_time = datetime.utcnow()
                timing_ms = (end_time - start_time).total_seconds() * 1000
                return ("ticker", result, timing_ms)
            except Exception as e:
                logger.error(f"Unexpected error in fetch_ticker_safe: {e}", exc_info=True)
                # Return error result
                error_result = DebugResponse(
                    success=False,
                    data=None,
                    error=ErrorInfo(message=f"Internal error: {str(e)}", code="INTERNAL_ERROR"),
                    metadata=RequestMetadata(
                        request_timestamp=datetime.utcnow(),
                        response_timestamp=datetime.utcnow(),
                        response_time_ms=0.0,
                        exchange="binanceusdm"
                    )
                )
                return ("ticker", error_result, 0.0)
        
        async def fetch_open_interest_safe():
            """Wrapper for open interest fetch with error handling."""
            try:
                start_time = datetime.utcnow()
                result = await self.fetch_raw_open_interest(normalized_symbol)
                end_time = datetime.utcnow()
                timing_ms = (end_time - start_time).total_seconds() * 1000
                return ("openInterest", result, timing_ms)
            except Exception as e:
                logger.error(f"Unexpected error in fetch_open_interest_safe: {e}", exc_info=True)
                error_result = DebugResponse(
                    success=False,
                    data=None,
                    error=ErrorInfo(message=f"Internal error: {str(e)}", code="INTERNAL_ERROR"),
                    metadata=RequestMetadata(
                        request_timestamp=datetime.utcnow(),
                        response_timestamp=datetime.utcnow(),
                        response_time_ms=0.0,
                        exchange="binanceusdm"
                    )
                )
                return ("openInterest", error_result, 0.0)
        
        async def fetch_funding_rate_safe():
            """Wrapper for funding rate fetch with error handling."""
            try:
                start_time = datetime.utcnow()
                # Note: fetch_raw_funding_rate is synchronous, so we need to run it in executor
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, self.fetch_raw_funding_rate, normalized_symbol)
                end_time = datetime.utcnow()
                timing_ms = (end_time - start_time).total_seconds() * 1000
                return ("fundingRate", result, timing_ms)
            except Exception as e:
                logger.error(f"Unexpected error in fetch_funding_rate_safe: {e}", exc_info=True)
                error_result = DebugResponse(
                    success=False,
                    data=None,
                    error=ErrorInfo(message=f"Internal error: {str(e)}", code="INTERNAL_ERROR"),
                    metadata=RequestMetadata(
                        request_timestamp=datetime.utcnow(),
                        response_timestamp=datetime.utcnow(),
                        response_time_ms=0.0,
                        exchange="binanceusdm"
                    )
                )
                return ("fundingRate", error_result, 0.0)
        
        async def fetch_long_short_ratio_safe():
            """Wrapper for long/short ratio fetch with error handling."""
            try:
                start_time = datetime.utcnow()
                # Note: fetch_raw_long_short_ratio is synchronous, so we need to run it in executor
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, self.fetch_raw_long_short_ratio, normalized_symbol)
                end_time = datetime.utcnow()
                timing_ms = (end_time - start_time).total_seconds() * 1000
                return ("longShortRatio", result, timing_ms)
            except Exception as e:
                logger.error(f"Unexpected error in fetch_long_short_ratio_safe: {e}", exc_info=True)
                error_result = DebugResponse(
                    success=False,
                    data=None,
                    error=ErrorInfo(message=f"Internal error: {str(e)}", code="INTERNAL_ERROR"),
                    metadata=RequestMetadata(
                        request_timestamp=datetime.utcnow(),
                        response_timestamp=datetime.utcnow(),
                        response_time_ms=0.0,
                        exchange="binanceusdm"
                    )
                )
                return ("longShortRatio", error_result, 0.0)
        
        # Execute all four fetch methods concurrently
        results = await asyncio.gather(
            fetch_ticker_safe(),
            fetch_open_interest_safe(),
            fetch_funding_rate_safe(),
            fetch_long_short_ratio_safe(),
            return_exceptions=False  # Exceptions are handled within each wrapper
        )
        
        # Record overall response timestamp
        overall_response_timestamp = datetime.utcnow()
        total_response_time_ms = (overall_response_timestamp - overall_request_timestamp).total_seconds() * 1000
        
        # Build data structure with results for all four data types
        data_results = {}
        individual_timings = {}
        
        for data_type, debug_response, timing_ms in results:
            # Convert DebugResponse to DataTypeResult
            data_results[data_type] = DataTypeResult(
                success=debug_response.success,
                data=debug_response.data,
                error=debug_response.error
            )
            
            # Store individual timing
            timing_key = data_type.replace("openInterest", "open_interest").replace("fundingRate", "funding_rate").replace("longShortRatio", "long_short_ratio") + "_ms"
            individual_timings[timing_key] = round(timing_ms, 2)
        
        # Determine overall success (true if any data type succeeded)
        overall_success = any(result.success for result in data_results.values())
        
        logger.info(f"Completed fetching all raw data for {normalized_symbol} in {total_response_time_ms:.2f}ms")
        
        # Build AggregatedDebugResponse
        return AggregatedDebugResponse(
            success=overall_success,
            data=data_results,
            metadata={
                "request_timestamp": overall_request_timestamp.isoformat(),
                "response_timestamp": overall_response_timestamp.isoformat(),
                "total_response_time_ms": round(total_response_time_ms, 2),
                "individual_timings": individual_timings
            },
            fieldMapping={
                "ticker": self.field_mappings["ticker"],
                "openInterest": self.field_mappings["openInterest"],
                "fundingRate": self.field_mappings["fundingRate"],
                "longShortRatio": self.field_mappings["longShortRatio"]
            }
        )

    async def check_exchange_health(self) -> HealthCheckResponse:
        """
        Check exchange connectivity and return health status.
        
        This method verifies that the exchange connection is working by fetching
        the server timestamp. It returns connection status, exchange information,
        available debug endpoints, and timing metrics.
        
        Returns:
            HealthCheckResponse: Response containing connection status, exchange info,
                                server timestamp, available endpoints, and metadata
        
        Examples:
            >>> service = DebugExchangeService(exchange_connector)
            >>> response = await service.check_exchange_health()
            >>> print(response.data['status'])
            'connected'
        """
        # Record request timestamp
        request_timestamp = datetime.utcnow()
        
        try:
            # Call exchange.fetch_time() to get server timestamp and verify connectivity
            logger.info("Checking exchange health by fetching server time")
            server_timestamp = await self.exchange.fetch_time()
            
            # Record response timestamp
            response_timestamp = datetime.utcnow()
            
            # Calculate response time in milliseconds
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            # Get exchange base URL from exchange instance
            base_url = getattr(self.exchange, 'urls', {}).get('api', {})
            if isinstance(base_url, dict):
                # For CCXT exchanges, the API URLs are nested
                base_url = base_url.get('public', 'https://fapi.binance.com')
            elif not base_url:
                base_url = 'https://fapi.binance.com'
            
            # Build list of available debug endpoints
            available_endpoints = [
                "/api/v1/debug/exchange/ticker/{symbol}",
                "/api/v1/debug/exchange/open-interest/{symbol}",
                "/api/v1/debug/exchange/funding-rate/{symbol}",
                "/api/v1/debug/exchange/long-short-ratio/{symbol}",
                "/api/v1/debug/exchange/all/{symbol}"
            ]
            
            logger.info(f"Exchange health check successful in {response_time_ms:.2f}ms")
            
            # Build successful health check response
            return HealthCheckResponse(
                success=True,
                data={
                    "status": "connected",
                    "exchange": "binanceusdm",
                    "base_url": base_url,
                    "server_timestamp": server_timestamp,
                    "available_endpoints": available_endpoints
                },
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=200,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.AuthenticationError as e:
            # Authentication error (401) - when auth is enabled and credentials are invalid/missing
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Authentication error during health check: {str(e)}", exc_info=True)
            
            return HealthCheckResponse(
                success=False,
                data={
                    "status": "disconnected",
                    "exchange": "binanceusdm",
                    "error_details": "Authentication required"
                },
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=401,
                    exchange="binanceusdm"
                )
            )
        
        except ccxt.RequestTimeout as e:
            # Timeout error (503 for health check)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Request timeout during health check: {str(e)}", exc_info=True)
            
            return HealthCheckResponse(
                success=False,
                data={
                    "status": "disconnected",
                    "exchange": "binanceusdm",
                    "error_details": f"Request timeout: Exchange request timed out after {round(response_time_ms, 2)}ms"
                },
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.NetworkError as e:
            # Network/connectivity error (503)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Network error during health check: {str(e)}", exc_info=True)
            
            # Determine specific error details
            error_details = f"Cannot connect to exchange: {str(e)}"
            if "getaddrinfo failed" in str(e).lower() or "name resolution" in str(e).lower():
                error_details = "DNS resolution failed"
            elif "connection refused" in str(e).lower():
                error_details = "Connection refused"
            
            return HealthCheckResponse(
                success=False,
                data={
                    "status": "disconnected",
                    "exchange": "binanceusdm",
                    "error_details": error_details
                },
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                )
            )
            
        except ccxt.ExchangeError as e:
            # Exchange-specific error (503)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Exchange error during health check: {str(e)}", exc_info=True)
            
            return HealthCheckResponse(
                success=False,
                data={
                    "status": "disconnected",
                    "exchange": "binanceusdm",
                    "error_details": f"Exchange error: {str(e)}"
                },
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                )
            )
            
        except Exception as e:
            # Unexpected internal error (503)
            response_timestamp = datetime.utcnow()
            response_time_ms = (response_timestamp - request_timestamp).total_seconds() * 1000
            
            logger.error(f"Unexpected error during health check: {str(e)}", exc_info=True)
            
            return HealthCheckResponse(
                success=False,
                data={
                    "status": "disconnected",
                    "exchange": "binanceusdm",
                    "error_details": "Internal server error: An unexpected error occurred"
                },
                metadata=RequestMetadata(
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                    response_time_ms=round(response_time_ms, 2),
                    http_status=503,
                    exchange="binanceusdm"
                )
            )
