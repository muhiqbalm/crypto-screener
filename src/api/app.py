"""FastAPI application factory with middleware and lifespan management.

Provides create_app() factory function that configures:
- CORS middleware with configurable origins
- Request logging middleware (timestamp, endpoint, response time)
- Lifespan context manager for graceful startup/shutdown
- Graceful shutdown: rejects new requests with 503 after SIGTERM,
  waits up to 30 seconds for active requests to complete
"""

import asyncio
import logging
import signal
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from src.config.logging_config import setup_logging
from src.config.settings import Settings
from src.services.cache_manager import CacheManager
from src.services.data_processor import DataProcessor
from src.services.response_builder import ResponseBuilder

# 1 MB limit for all request bodies (Requirement 20.3)
_MAX_CONTENT_SIZE = 1_048_576

logger = logging.getLogger(__name__)


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that rejects request bodies exceeding max_content_size bytes.

    Checks the ``Content-Length`` header first (fast path) and then verifies
    the actual body size for chunked transfers where no Content-Length is
    present.  Returns a 413 JSON response when the limit is exceeded.

    Satisfies Requirement 20.3: bodies > 1 MB are rejected with 413.
    """

    def __init__(self, app, max_content_size: int = _MAX_CONTENT_SIZE) -> None:
        super().__init__(app)
        self.max_content_size = max_content_size

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Fast path: reject based on Content-Length header alone
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
                if content_length > self.max_content_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "status": "error",
                            "error": "Payload too large",
                            "detail": f"Request body must not exceed {self.max_content_size} bytes",
                        },
                    )
            except ValueError:
                pass  # Malformed header — let FastAPI handle it downstream

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs each request with endpoint, method, and response time.

    Also rejects new requests with 503 when the application is shutting down.
    
    For debug endpoints, additionally logs:
    - Symbol parameter (from path parameters)
    - Requester identity (from X-Forwarded-For, X-Real-IP, or User-Agent headers)
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Check if the app is shutting down — reject new requests with 503
        app = request.app
        if getattr(app.state, "shutting_down", False):
            logger.warning(
                "Request rejected during shutdown",
                extra={
                    "endpoint": request.url.path,
                    "method": request.method,
                },
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service Unavailable",
                    "message": "Server is shutting down. Please retry later.",
                },
            )

        # Track active requests
        app.state.active_requests = getattr(app.state, "active_requests", 0) + 1

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            app.state.active_requests = max(
                0, getattr(app.state, "active_requests", 1) - 1
            )

        response_time_ms = (time.perf_counter() - start_time) * 1000

        # Build log extra data
        log_extra = {
            "endpoint": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "response_time_ms": round(response_time_ms, 2),
        }

        # For debug endpoints, add symbol parameter and requester identity
        if request.url.path.startswith("/api/v1/debug/"):
            # Extract symbol from path parameters if present
            path_params = request.path_params
            if "symbol" in path_params:
                log_extra["symbol"] = path_params["symbol"]
            
            # Extract requester identity from headers
            # Priority: X-Forwarded-For > X-Real-IP > User-Agent
            requester_identity = (
                request.headers.get("X-Forwarded-For") or
                request.headers.get("X-Real-IP") or
                request.headers.get("User-Agent") or
                "unknown"
            )
            log_extra["requester_identity"] = requester_identity

        logger.info(
            "Request completed",
            extra=log_extra,
        )

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and graceful shutdown.

    On startup:
        - Initializes CacheManager, ResponseBuilder, stores in app.state
        - Records start_time for uptime tracking

    On shutdown:
        - Sets shutting_down flag to reject new requests
        - Waits for active requests to complete (max shutdown_timeout seconds)
        - Logs shutdown event
    """
    settings: Settings = app.state.settings

    # --- Startup ---
    logger.info("Application starting up")

    app.state.cache_manager = CacheManager(ttl=settings.cache_ttl)
    app.state.response_builder = ResponseBuilder()
    app.state.data_processor = DataProcessor(settings)
    app.state.start_time = time.time()
    app.state.shutting_down = False
    app.state.active_requests = 0

    # Initialize ExchangeConnector and DebugExchangeService for debug endpoints
    from src.exchange.connector import ExchangeConnector
    from src.services.debug_exchange_service import DebugExchangeService

    try:
        exchange_connector = ExchangeConnector(exchange_id="binanceusdm")
        exchange_connector.connect()
        app.state.exchange_connector = exchange_connector
        app.state.debug_service = DebugExchangeService(exchange_connector)
        logger.info("DebugExchangeService initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize DebugExchangeService: {e}")
        # Continue startup even if debug service fails to initialize
        app.state.exchange_connector = None
        app.state.debug_service = None

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def _handle_shutdown_signal() -> None:
        """Set the shutting_down flag when SIGTERM/SIGINT is received."""
        if not app.state.shutting_down:
            app.state.shutting_down = True
            logger.info("Shutdown signal received, rejecting new requests")

    # Register signal handlers (SIGTERM for production, SIGINT for dev)
    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_shutdown_signal)
        loop.add_signal_handler(signal.SIGINT, _handle_shutdown_signal)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler; use signal.signal fallback
        signal.signal(signal.SIGTERM, lambda s, f: _handle_shutdown_signal())
        signal.signal(signal.SIGINT, lambda s, f: _handle_shutdown_signal())

    logger.info(
        "Application started successfully",
        extra={
            "host": settings.api_host,
            "port": settings.api_port,
            "symbols": settings.symbols_list,
            "cache_ttl": settings.cache_ttl,
            "mock_mode": settings.mock_mode,
        },
    )

    yield

    # --- Shutdown ---
    app.state.shutting_down = True
    logger.info("Application shutting down, waiting for active requests to complete")

    shutdown_timeout = settings.shutdown_timeout
    wait_start = time.time()

    # Wait for active requests to finish (max shutdown_timeout seconds)
    while getattr(app.state, "active_requests", 0) > 0:
        elapsed = time.time() - wait_start
        if elapsed >= shutdown_timeout:
            remaining = getattr(app.state, "active_requests", 0)
            logger.warning(
                "Shutdown timeout reached, forcing exit",
                extra={
                    "remaining_requests": remaining,
                    "timeout_seconds": shutdown_timeout,
                },
            )
            break
        await asyncio.sleep(0.1)

    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance with middleware, lifespan, and shared state.
    """
    # Load settings and configure logging
    settings = Settings()
    setup_logging(settings.log_level)

    # Create FastAPI instance with lifespan
    app = FastAPI(
        title="Crypto Screener API",
        version="2.0.0",
        description="""
REST API backend for quantitative crypto screening with multi-factor scoring, 
risk-adjusted ranking, and position sizing.

## Screener API

### Multi-Factor Scoring Engine
The screener combines **5 quantitative signal factors** into a single composite score:

| Signal | Weight | Source |
|--------|--------|--------|
| **Momentum (30d)** | 30% | 30-day price trend with MA50 exhaustion penalty |
| **Funding Rate** | 25% | Contrarian signal from perpetual swap funding rates |
| **OI Momentum** | 20% | OI-delta × price-action matrix (new longs/shorts/squeeze/liquidation) |
| **Sentiment (L/S)** | 15% | Contrarian signal from long/short account ratio |
| **Reversal (1d)** | 10% | Mean-reversion signal from 24h price change |

### Risk-Adjusted Scoring
- **`risk_adjusted_score`** = `multi_factor_score / max(atr_percent, 1.0)` — penalizes volatile assets
- Assets are ranked by risk-adjusted score (rank 1 = highest)

### Tier Classification
- **Tier A** (top 33%): Strong buy candidates
- **Tier B** (middle 34%): Moderate / hold
- **Tier C** (bottom 33%): Avoid / short candidates

### Position Sizing
- **Inverse Volatility Weighting**: lower-ATR assets get larger allocations
- `suggested_position_pct` sums to 100% across all assets

### Endpoints
- `GET /api/v1/screener/summary` — Full screener data with market overview and ranked assets
- `GET /api/v1/screener/assets/{symbol}` — Single asset detail with all metrics
- `GET /api/v1/health` — API health check with cache status

---

## Debug API
Diagnostic endpoints for raw exchange data inspection from Binance Futures.

**Includes:** raw ticker, open interest, funding rate, long/short ratio, aggregated data, exchange health.

**Features:** request/response timing, field mapping documentation, error handling, concurrent fetching, optional authentication.

## Authentication

All endpoints (except `/api/v1/health`) can be protected with an API key.
When enabled, include the key in every request header:
```
X-API-Key: <your-api-key>
```

Configure via environment variables:
- `SCREENER_REQUIRE_API_KEY=true` — enable authentication
- `SCREENER_API_KEY=<your-secret>` — the secret key value
        """,
        lifespan=lifespan,
        openapi_tags=[
            {
                "name": "Screener API",
                "description": "Quantitative crypto screener with multi-factor scoring, risk-adjusted ranking, tier classification, and position sizing",
            },
            {
                "name": "Debug API",
                "description": "Diagnostic endpoints for raw exchange data inspection and troubleshooting",
            },
        ],
    )

    # Store settings in app.state for access by lifespan and middleware
    app.state.settings = settings

    # Register CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register content-size limit middleware (1 MB, Requirement 20.3)
    app.add_middleware(ContentSizeLimitMiddleware, max_content_size=_MAX_CONTENT_SIZE)

    # Register request logging middleware
    app.add_middleware(RequestLoggingMiddleware)
    
    # Register rate limiting middleware for debug endpoints (if enabled)
    if settings.debug_rate_limit_enabled:
        from src.api.rate_limit_middleware import RateLimitMiddleware
        
        app.add_middleware(
            RateLimitMiddleware,
            max_requests=settings.debug_rate_limit_requests,
            window_seconds=settings.debug_rate_limit_window,
        )
        logger.info(
            f"Rate limiting enabled for debug endpoints: "
            f"{settings.debug_rate_limit_requests} requests per "
            f"{settings.debug_rate_limit_window} seconds"
        )

    # Register API routes
    from src.api.routes import router
    from src.api.debug_routes import router as debug_router
    from src.trading.router import router as trading_router
    from src.trading.routers.auth_router import router as trading_auth_router
    from src.trading.routers.users_router import router as trading_users_router

    app.include_router(router)
    app.include_router(debug_router)
    app.include_router(trading_router)
    app.include_router(trading_auth_router)
    app.include_router(trading_users_router)

    return app
