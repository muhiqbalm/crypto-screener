"""API route handlers for the crypto screener REST API.

Defines endpoints:
- GET /api/v1/screener/summary — full or summary-only screener data
- GET /api/v1/screener/assets/{symbol} — single asset detail
- GET /api/v1/health — health check with cache status and uptime
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from src.api.auth import verify_api_key
from src.api.models import (
    AssetDetailResponse,
    CacheStatus,
    ErrorResponse,
    HealthResponse,
    ScreenerResponse,
)
from src.services.symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

# Auth dependency applied to the router — protects /screener/* endpoints.
# Health check is registered separately without auth so monitoring tools work.
router = APIRouter(prefix="/api/v1")
screener_router = APIRouter(dependencies=[Depends(verify_api_key)])


@screener_router.get(
    "/screener/summary",
    response_model=ScreenerResponse,
    tags=["Screener API"],
    summary="Get Screener Summary",
    description="Returns the full screener dataset including metadata, market overview "
    "(tier distribution, signal counts), and an array of all ranked assets with "
    "5-factor scoring, risk-adjusted scores, tier classification, and position sizing. "
    "Use `summary_only=true` to omit the assets array.",
)
async def get_screener_summary(request: Request, summary_only: bool = False):
    """Return full screener data or summary-only based on query parameter.

    Args:
        request: FastAPI request object (provides access to app.state).
        summary_only: If True, omit the assets array from the response.

    Returns:
        ScreenerResponse with metadata, summary, and optionally assets.
        On exchange error: 503 with ErrorResponse.
        On other error: 500 with ErrorResponse.
    """
    cache_manager = request.app.state.cache_manager
    data_processor = request.app.state.data_processor
    response_builder = request.app.state.response_builder
    settings = request.app.state.settings

    try:
        # Check cache first
        cache_entry = cache_manager.get()

        if cache_entry is not None:
            # Cache hit
            cache_hit = True
            result = cache_entry.result
            data_age_seconds = cache_entry.age_seconds
            logger.info(
                "Cache hit for screener summary",
                extra={"data_age_seconds": round(data_age_seconds, 2)},
            )
        else:
            # Cache miss — fetch fresh data
            cache_hit = False
            logger.info("Cache miss for screener summary, fetching fresh data")

            result = await data_processor.process_all()
            cache_manager.set(result)
            data_age_seconds = 0.0

            logger.info(
                "Fresh data fetched and cached",
                extra={"symbols_count": len(result.data), "errors_count": len(result.errors)},
            )

        # Build response
        errors = result.errors
        df = result.data

        if summary_only:
            response = response_builder.build_summary_only(
                df=df,
                cache_hit=cache_hit,
                data_age_seconds=data_age_seconds,
                errors=errors,
            )
        else:
            response = response_builder.build_full_response(
                df=df,
                cache_hit=cache_hit,
                data_age_seconds=data_age_seconds,
                errors=errors,
            )

        return response

    except Exception as e:
        # Determine if this is an exchange/network error (503) or internal error (500)
        error_type = type(e).__name__
        is_exchange_error = _is_exchange_error(e)

        if is_exchange_error:
            logger.error(
                "Exchange error during screener summary",
                extra={"error_type": error_type, "error_detail": str(e)},
            )
            error_response = ErrorResponse(
                error="Service Unavailable",
                message=f"Service temporarily unavailable: {str(e)}",
                timestamp=datetime.now(timezone.utc),
            )
            return JSONResponse(
                status_code=503,
                content=error_response.model_dump(mode="json"),
            )
        else:
            logger.error(
                "Internal error during screener summary",
                extra={"error_type": error_type, "error_detail": str(e)},
                exc_info=True,
            )
            error_response = ErrorResponse(
                error="Internal Server Error",
                message=f"An unexpected error occurred: {str(e)}",
                timestamp=datetime.now(timezone.utc),
            )
            return JSONResponse(
                status_code=500,
                content=error_response.model_dump(mode="json"),
            )


@screener_router.get(
    "/screener/assets/{symbol:path}",
    response_model=AssetDetailResponse,
    tags=["Screener API"],
    summary="Get Asset Detail",
    description="Returns detailed data for a single asset including price, volume, "
    "derivatives metrics (funding rate, OI, L/S ratio), all signal factor scores, "
    "risk-adjusted composite score, tier classification, and suggested position sizing.",
)
async def get_asset_detail(request: Request, symbol: str):
    """Return detailed data for a single asset.

    Args:
        request: FastAPI request object (provides access to app.state).
        symbol: The asset symbol in any accepted format.

    Returns:
        AssetDetailResponse with metadata and asset detail.
        404 if symbol not found or not in configured list.
        503 on exchange error, 500 on internal error.
    """
    cache_manager = request.app.state.cache_manager
    data_processor = request.app.state.data_processor
    response_builder = request.app.state.response_builder
    settings = request.app.state.settings

    # Validate and normalize symbol
    normalized = normalize_symbol(symbol, settings.symbols_list)

    if normalized is None:
        logger.info(
            "Symbol not found",
            extra={"requested_symbol": symbol, "available_symbols": settings.symbols_list},
        )
        error_response = ErrorResponse(
            error="Not Found",
            message=f"Symbol {symbol} not found. Available symbols: {settings.symbols_list}",
            available_symbols=settings.symbols_list,
            timestamp=datetime.now(timezone.utc),
        )
        return JSONResponse(
            status_code=404,
            content=error_response.model_dump(mode="json"),
        )

    try:
        # Check cache first
        cache_entry = cache_manager.get()

        if cache_entry is not None:
            cache_hit = True
            result = cache_entry.result
            data_age_seconds = cache_entry.age_seconds
            logger.info(
                "Cache hit for asset detail",
                extra={"symbol": normalized, "data_age_seconds": round(data_age_seconds, 2)},
            )
        else:
            cache_hit = False
            logger.info(
                "Cache miss for asset detail, fetching fresh data",
                extra={"symbol": normalized},
            )

            result = await data_processor.process_all()
            cache_manager.set(result)
            data_age_seconds = 0.0

        df = result.data

        # Check if symbol exists in the processed data
        if df.empty or normalized not in df["symbol"].values:
            logger.warning(
                "Symbol not found in processed data",
                extra={"symbol": normalized},
            )
            error_response = ErrorResponse(
                error="Not Found",
                message=f"Symbol {normalized} not found in current data",
                available_symbols=settings.symbols_list,
                timestamp=datetime.now(timezone.utc),
            )
            return JSONResponse(
                status_code=404,
                content=error_response.model_dump(mode="json"),
            )

        # Build asset detail response
        response = response_builder.build_asset_detail(
            df=df,
            symbol=normalized,
            cache_hit=cache_hit,
            data_age_seconds=data_age_seconds,
        )

        return response

    except Exception as e:
        error_type = type(e).__name__
        is_exchange_error = _is_exchange_error(e)

        if is_exchange_error:
            logger.error(
                "Exchange error during asset detail fetch",
                extra={"symbol": normalized, "error_type": error_type, "error_detail": str(e)},
            )
            error_response = ErrorResponse(
                error="Service Unavailable",
                message=f"Service temporarily unavailable: {str(e)}",
                timestamp=datetime.now(timezone.utc),
            )
            return JSONResponse(
                status_code=503,
                content=error_response.model_dump(mode="json"),
            )
        else:
            logger.error(
                "Internal error during asset detail fetch",
                extra={"symbol": normalized, "error_type": error_type, "error_detail": str(e)},
                exc_info=True,
            )
            error_response = ErrorResponse(
                error="Internal Server Error",
                message=f"An unexpected error occurred: {str(e)}",
                timestamp=datetime.now(timezone.utc),
            )
            return JSONResponse(
                status_code=500,
                content=error_response.model_dump(mode="json"),
            )


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Screener API"],
    summary="Health Check",
    description="Returns API health status including server uptime and cache status "
    "(data age, staleness, next refresh time). Always returns HTTP 200.",
)
async def health_check(request: Request):
    """Return API health status including cache status and uptime.

    Always returns HTTP 200 with current health information.

    Args:
        request: FastAPI request object (provides access to app.state).

    Returns:
        HealthResponse with status, uptime, and cache status.
    """
    cache_manager = request.app.state.cache_manager
    start_time = request.app.state.start_time

    uptime_seconds = time.time() - start_time

    # Build cache status
    data_age = cache_manager.data_age_seconds
    is_stale = cache_manager.is_stale
    next_refresh = cache_manager.next_refresh_at

    next_refresh_in = None
    if next_refresh is not None:
        next_refresh_in = max(0.0, (next_refresh - datetime.utcnow()).total_seconds())

    cache_status = CacheStatus(
        data_age_seconds=round(data_age, 2) if data_age is not None else None,
        is_stale=is_stale,
        next_refresh_in=round(next_refresh_in, 2) if next_refresh_in is not None else None,
    )

    # Determine overall status
    if is_stale and data_age is not None:
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(
        status=status,
        uptime_seconds=round(uptime_seconds, 2),
        cache_status=cache_status,
    )


def _is_exchange_error(exc: Exception) -> bool:
    """Check if an exception is related to exchange connectivity.

    Checks for ccxt exceptions (NetworkError, ExchangeError, etc.)
    and common timeout/connection errors.

    Args:
        exc: The exception to check.

    Returns:
        True if the exception is exchange-related, False otherwise.
    """
    # Check for ccxt exceptions by class name (avoids hard import dependency)
    exc_class_name = type(exc).__name__
    exchange_error_names = {
        "NetworkError",
        "ExchangeError",
        "ExchangeNotAvailable",
        "RequestTimeout",
        "RateLimitExceeded",
        "DDoSProtection",
    }

    if exc_class_name in exchange_error_names:
        return True

    # Check module path for ccxt
    exc_module = type(exc).__module__ or ""
    if "ccxt" in exc_module:
        return True

    # Check for common timeout/connection errors
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True

    return False


# Include the auth-protected screener endpoints into the main router
router.include_router(screener_router)
