"""Debug API route handlers for raw exchange data inspection.

Defines endpoints:
- GET /api/v1/debug/exchange/ticker/{symbol} — raw ticker data
- GET /api/v1/debug/exchange/open-interest/{symbol} — raw open interest data
- GET /api/v1/debug/exchange/funding-rate/{symbol} — raw funding rate data
- GET /api/v1/debug/exchange/long-short-ratio/{symbol} — raw long/short ratio data
- GET /api/v1/debug/exchange/all/{symbol} — aggregated raw data for all types
- GET /api/v1/debug/health — exchange health check
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.api.debug_models import (
    AggregatedDebugResponse,
    DebugResponse,
    HealthCheckResponse,
)
from src.services.debug_exchange_service import DebugExchangeService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/debug",
    tags=["Debug API"],
    responses={
        400: {"description": "Invalid input parameters"},
        401: {"description": "Authentication required (when enabled)"},
        503: {"description": "Exchange service unavailable"},
        504: {"description": "Exchange request timeout"}
    }
)

# HTTP Bearer token security scheme (optional)
security = HTTPBearer(auto_error=False)


def verify_authentication(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> None:
    """Verify authentication credentials when authentication is enabled.
    
    This dependency checks if authentication is enabled in the application settings.
    If enabled, it validates the provided Bearer token against the configured token.
    If authentication is disabled, this dependency does nothing.
    
    Args:
        request: FastAPI request object (provides access to app.state)
        credentials: HTTP Bearer token credentials (optional)
    
    Raises:
        HTTPException: 401 Unauthorized if authentication is enabled and
                      credentials are missing or invalid
    """
    # Get settings from app.state
    settings = request.app.state.settings
    
    # If authentication is not enabled, allow the request
    if not settings.debug_api_auth_enabled:
        return
    
    # Authentication is enabled - verify credentials
    if credentials is None:
        logger.warning("Authentication required but no credentials provided")
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify the token matches the configured token
    if credentials.credentials != settings.debug_api_auth_token:
        logger.warning("Authentication failed: invalid token")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Authentication successful
    logger.debug("Authentication successful")



def get_debug_service(request: Request) -> DebugExchangeService:
    """Dependency to get or create DebugExchangeService instance.
    
    Retrieves the DebugExchangeService from app.state if it exists,
    otherwise creates a new instance and stores it in app.state.
    
    Args:
        request: FastAPI request object (provides access to app.state)
    
    Returns:
        DebugExchangeService: The debug exchange service instance
    """
    # Check if debug_service already exists in app.state
    if not hasattr(request.app.state, "debug_service"):
        # Create new DebugExchangeService using the exchange_connector from app.state
        from src.exchange.connector import ExchangeConnector
        
        # Get or create exchange_connector
        if not hasattr(request.app.state, "exchange_connector"):
            exchange_connector = ExchangeConnector(exchange_id="binanceusdm")
            exchange_connector.connect()
            request.app.state.exchange_connector = exchange_connector
        else:
            exchange_connector = request.app.state.exchange_connector
        
        # Create and store debug_service
        request.app.state.debug_service = DebugExchangeService(exchange_connector)
        logger.info("Created new DebugExchangeService instance")
    
    return request.app.state.debug_service


@router.get(
    "/exchange/ticker/{symbol}",
    response_model=DebugResponse,
    summary="Get raw ticker data",
    description="Retrieve unprocessed ticker data from Binance Futures API including price, volume, and 24-hour change information",
    responses={
        200: {
            "description": "Successfully retrieved raw ticker data",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "symbol": "BTC/USDT:USDT",
                            "last": 45000.50,
                            "percentage": 2.5,
                            "quoteVolume": 1500000000.0
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.250Z",
                            "response_time_ms": 250.45
                        }
                    }
                }
            }
        }
    }
)
async def get_raw_ticker(
    symbol: str,
    debug_service: DebugExchangeService = Depends(get_debug_service),
    _auth: None = Depends(verify_authentication)
) -> JSONResponse:
    """Return raw ticker data from the exchange.
    
    Retrieves unprocessed ticker data including price, volume, and 24-hour change
    information directly from the Binance Futures API. The response includes
    request/response timing metrics and field mapping documentation.
    
    **Parameters:**
    - **symbol**: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT"). Must be alphanumeric,
                  max 20 characters. Whitespace is trimmed and converted to uppercase.
    
    **Response includes:**
    - **success**: Boolean indicating if the request succeeded
    - **data**: Raw ticker response from CCXT including symbol, last price, percentage
                change, quote volume, base volume, and other ticker fields
    - **metadata**: Request timing (request_timestamp, response_timestamp, response_time_ms)
                    and exchange identifier
    - **fieldMapping**: Documentation of which exchange fields map to application fields,
                        including data types and transformation notes
    
    **Error codes:**
    - 400: Invalid symbol parameter (empty, non-alphanumeric, or exceeds 20 chars)
    - 401: Authentication required (when authentication is enabled)
    - 503: Exchange service unavailable (connection failure, DNS error)
    - 504: Exchange request timeout
    """
    logger.info(f"Received request for raw ticker data: {symbol}")
    
    # Fetch raw ticker data
    response = await debug_service.fetch_raw_ticker(symbol)
    
    # Determine HTTP status code based on response
    status_code = response.metadata.http_status or (200 if response.success else 500)
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json")
    )


@router.get(
    "/exchange/open-interest/{symbol}",
    response_model=DebugResponse,
    summary="Get raw open interest data",
    description="Retrieve unprocessed open interest data showing total outstanding derivative contracts",
    responses={
        200: {
            "description": "Successfully retrieved raw open interest data",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "symbol": "BTC/USDT:USDT",
                            "openInterestAmount": 1000000.0
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.300Z",
                            "response_time_ms": 300.0
                        }
                    }
                }
            }
        }
    }
)
async def get_raw_open_interest(
    symbol: str,
    debug_service: DebugExchangeService = Depends(get_debug_service),
    _auth: None = Depends(verify_authentication)
) -> JSONResponse:
    """Return raw open interest data from the exchange.
    
    Retrieves unprocessed open interest data showing the total number of
    outstanding derivative contracts directly from the Binance Futures API.
    The response includes request/response timing metrics and field mapping
    documentation.
    
    **Parameters:**
    - **symbol**: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT"). Must be alphanumeric,
                  max 20 characters. Whitespace is trimmed and converted to uppercase.
    
    **Response includes:**
    - **success**: Boolean indicating if the request succeeded
    - **data**: Raw open interest response including openInterestAmount and openInterest fields
    - **metadata**: Request timing and exchange identifier
    - **fieldMapping**: Documentation of which exchange fields map to application fields
    
    **Error codes:**
    - 400: Invalid symbol parameter
    - 401: Authentication required (when authentication is enabled)
    - 503: Exchange service unavailable
    - 504: Exchange request timeout
    """
    logger.info(f"Received request for raw open interest data: {symbol}")
    
    # Fetch raw open interest data
    response = await debug_service.fetch_raw_open_interest(symbol)
    
    # Determine HTTP status code based on response
    status_code = response.metadata.http_status or (200 if response.success else 500)
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json")
    )


@router.get(
    "/exchange/funding-rate/{symbol}",
    response_model=DebugResponse,
    summary="Get raw funding rate data",
    description="Retrieve unprocessed funding rate data showing periodic payments between long and short positions",
    responses={
        200: {
            "description": "Successfully retrieved raw funding rate data",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "symbol": "BTC/USDT:USDT",
                            "fundingRate": 0.0001
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.280Z",
                            "response_time_ms": 280.0
                        }
                    }
                }
            }
        }
    }
)
async def get_raw_funding_rate(
    symbol: str,
    debug_service: DebugExchangeService = Depends(get_debug_service),
    _auth: None = Depends(verify_authentication)
) -> JSONResponse:
    """Return raw funding rate data from the exchange.
    
    Retrieves unprocessed funding rate data showing the periodic payment
    between long and short positions directly from the Binance Futures API.
    The response includes request/response timing metrics and field mapping
    documentation.
    
    **Parameters:**
    - **symbol**: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT"). Must be alphanumeric,
                  max 20 characters. Whitespace is trimmed and converted to uppercase.
    
    **Response includes:**
    - **success**: Boolean indicating if the request succeeded
    - **data**: Raw funding rate response including fundingRate as decimal (e.g., 0.0001)
    - **metadata**: Request timing and exchange identifier
    - **fieldMapping**: Documentation including transformation note (multiply by 100 for percentage)
    
    **Error codes:**
    - 400: Invalid symbol parameter
    - 401: Authentication required (when authentication is enabled)
    - 503: Exchange service unavailable
    - 504: Exchange request timeout
    """
    logger.info(f"Received request for raw funding rate data: {symbol}")
    
    # Fetch raw funding rate data
    response = debug_service.fetch_raw_funding_rate(symbol)
    
    # Determine HTTP status code based on response
    status_code = response.metadata.http_status or (200 if response.success else 500)
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json")
    )


@router.get(
    "/exchange/long-short-ratio/{symbol}",
    response_model=DebugResponse,
    summary="Get raw long/short ratio data",
    description="Retrieve unprocessed long/short ratio data from Binance top trader statistics",
    responses={
        200: {
            "description": "Successfully retrieved raw long/short ratio data",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "symbol": "BTCUSDT",
                            "longShortRatio": 1.5
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.320Z",
                            "response_time_ms": 320.0
                        }
                    }
                }
            }
        }
    }
)
async def get_raw_long_short_ratio(
    symbol: str,
    debug_service: DebugExchangeService = Depends(get_debug_service),
    _auth: None = Depends(verify_authentication)
) -> JSONResponse:
    """Return raw long/short ratio data from the exchange.
    
    Retrieves unprocessed long/short ratio data showing the ratio of long
    positions to short positions from Binance top trader data. The response
    includes request/response timing metrics and field mapping documentation.
    
    **Parameters:**
    - **symbol**: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT"). Must be alphanumeric,
                  max 20 characters. Whitespace is trimmed and converted to uppercase.
    
    **Response includes:**
    - **success**: Boolean indicating if the request succeeded
    - **data**: Raw long/short ratio response including longShortRatio field
    - **metadata**: Request timing and exchange identifier
    - **fieldMapping**: Documentation of field mapping to application
    
    **Error codes:**
    - 400: Invalid symbol parameter
    - 401: Authentication required (when authentication is enabled)
    - 503: Exchange service unavailable
    - 504: Exchange request timeout
    """
    logger.info(f"Received request for raw long/short ratio data: {symbol}")
    
    # Fetch raw long/short ratio data
    response = debug_service.fetch_raw_long_short_ratio(symbol)
    
    # Determine HTTP status code based on response
    status_code = response.metadata.http_status or (200 if response.success else 500)
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json")
    )


@router.get(
    "/exchange/all/{symbol}",
    response_model=AggregatedDebugResponse,
    summary="Get aggregated raw data for all types",
    description="Retrieve raw data for ticker, open interest, funding rate, and long/short ratio concurrently",
    responses={
        200: {
            "description": "Successfully retrieved aggregated raw data (at least one data type succeeded)",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "ticker": {
                                "success": True,
                                "data": {"symbol": "BTC/USDT:USDT", "last": 45000.50},
                                "error": None
                            },
                            "openInterest": {
                                "success": True,
                                "data": {"openInterestAmount": 1000000.0},
                                "error": None
                            },
                            "fundingRate": {
                                "success": True,
                                "data": {"fundingRate": 0.0001},
                                "error": None
                            },
                            "longShortRatio": {
                                "success": True,
                                "data": {"longShortRatio": 1.5},
                                "error": None
                            }
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.500Z",
                            "total_response_time_ms": 500.0,
                            "individual_timings": {
                                "ticker_ms": 250.0,
                                "open_interest_ms": 300.0,
                                "funding_rate_ms": 280.0,
                                "long_short_ratio_ms": 320.0
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_all_raw_data(
    symbol: str,
    debug_service: DebugExchangeService = Depends(get_debug_service),
    _auth: None = Depends(verify_authentication)
) -> JSONResponse:
    """Return aggregated raw data for all data types.
    
    Retrieves raw data for ticker, open interest, funding rate, and long/short
    ratio concurrently from the Binance Futures API. The response includes
    individual timing information for each data type and field mappings for all
    data types. Individual endpoint failures do not prevent other data from
    being returned.
    
    **Parameters:**
    - **symbol**: Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT"). Must be alphanumeric,
                  max 20 characters. Whitespace is trimmed and converted to uppercase.
    
    **Response includes:**
    - **success**: Boolean indicating if at least one data type succeeded
    - **data**: Results for all four data types (ticker, openInterest, fundingRate, longShortRatio),
                each with its own success status, data, and error fields
    - **metadata**: Overall timing plus individual_timings for each data type
    - **fieldMapping**: Field mappings for all four data types
    
    **Features:**
    - Concurrent execution: All requests run in parallel for minimal latency
    - Graceful degradation: Individual failures don't prevent other data from being returned
    - Detailed timing: See exactly how long each data type took to fetch
    
    **Error codes:**
    - 400: Invalid symbol parameter
    - 401: Authentication required (when authentication is enabled)
    - 500: All data types failed (check individual error fields in response)
    """
    logger.info(f"Received request for aggregated raw data: {symbol}")
    
    # Fetch all raw data concurrently
    response = await debug_service.fetch_all_raw_data(symbol)
    
    # Aggregated endpoint always returns 200 if at least one data type succeeded
    # or appropriate error status if all failed
    status_code = 200 if response.success else 500
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json")
    )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Check exchange health status",
    description="Verify connection to Binance Futures exchange and get available endpoints",
    responses={
        200: {
            "description": "Exchange is connected and healthy",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "status": "connected",
                            "exchange": "binanceusdm",
                            "base_url": "https://fapi.binance.com",
                            "server_timestamp": 1705315800000,
                            "available_endpoints": [
                                "/api/v1/debug/exchange/ticker/{symbol}",
                                "/api/v1/debug/exchange/open-interest/{symbol}",
                                "/api/v1/debug/exchange/funding-rate/{symbol}",
                                "/api/v1/debug/exchange/long-short-ratio/{symbol}",
                                "/api/v1/debug/exchange/all/{symbol}"
                            ]
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.150Z",
                            "response_time_ms": 150.0
                        }
                    }
                }
            }
        },
        503: {
            "description": "Exchange is disconnected or unavailable",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "data": {
                            "status": "disconnected",
                            "exchange": "binanceusdm",
                            "error": "Connection refused"
                        },
                        "metadata": {
                            "request_timestamp": "2024-01-15T10:30:00.000Z",
                            "response_timestamp": "2024-01-15T10:30:00.100Z",
                            "response_time_ms": 100.0
                        }
                    }
                }
            }
        }
    }
)
async def check_exchange_health(
    debug_service: DebugExchangeService = Depends(get_debug_service),
    _auth: None = Depends(verify_authentication)
) -> JSONResponse:
    """Return exchange health check status.
    
    Checks the connection status to the Binance Futures exchange and returns
    information about available debug endpoints, exchange configuration, and
    current server timestamp.
    
    **Response includes:**
    - **success**: Boolean indicating if the exchange is connected
    - **data**: Health check information including:
        - **status**: "connected" or "disconnected"
        - **exchange**: Exchange identifier (binanceusdm)
        - **base_url**: Exchange API base URL
        - **server_timestamp**: Current exchange server time in milliseconds
        - **available_endpoints**: List of all debug API endpoints
    - **metadata**: Request timing information
    
    **Status codes:**
    - 200: Exchange is connected and healthy
    - 401: Authentication required (when authentication is enabled)
    - 503: Exchange is disconnected or unavailable
    
    **Use cases:**
    - Verify exchange connectivity before making data requests
    - Monitor exchange API availability
    - Discover available debug endpoints
    - Check exchange server time synchronization
    """
    logger.info("Received request for exchange health check")
    
    # Check exchange health
    response = await debug_service.check_exchange_health()
    
    # Determine HTTP status code based on connection status
    status_code = 200 if response.success else 503
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json")
    )
