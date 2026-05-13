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

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs each request with endpoint, method, and response time.

    Also rejects new requests with 503 when the application is shutting down.
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

        logger.info(
            "Request completed",
            extra={
                "endpoint": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "response_time_ms": round(response_time_ms, 2),
            },
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
        version="1.0.0",
        description="REST API backend for crypto screener data",
        lifespan=lifespan,
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

    # Register request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Register API routes
    from src.api.routes import router

    app.include_router(router)

    return app
