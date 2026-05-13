"""Tests for the FastAPI application factory (src/api/app.py).

Validates:
- create_app() returns a properly configured FastAPI instance
- CORS middleware is registered with correct origins
- Request logging middleware is registered
- Lifespan initializes shared state (cache_manager, response_builder, etc.)
- Graceful shutdown rejects new requests with 503
"""

import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.app import create_app, RequestLoggingMiddleware


@pytest.fixture
def app():
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


class TestCreateApp:
    """Tests for the create_app() factory function."""

    def test_returns_fastapi_instance(self, app):
        """create_app() returns a FastAPI instance."""
        from fastapi import FastAPI

        assert isinstance(app, FastAPI)

    def test_app_title(self, app):
        """App title is set to 'Crypto Screener API'."""
        assert app.title == "Crypto Screener API"

    def test_app_version(self, app):
        """App version is set to '1.0.0'."""
        assert app.version == "1.0.0"

    def test_settings_stored_in_state(self, app):
        """Settings instance is stored in app.state."""
        from src.config.settings import Settings

        assert hasattr(app.state, "settings")
        assert isinstance(app.state.settings, Settings)

    def test_cors_middleware_registered(self, app):
        """CORS middleware is registered in the middleware stack."""
        middleware_classes = [
            m.cls.__name__ if hasattr(m, "cls") else type(m).__name__
            for m in app.user_middleware
        ]
        assert "CORSMiddleware" in middleware_classes

    def test_request_logging_middleware_registered(self, app):
        """Request logging middleware is registered in the middleware stack."""
        middleware_classes = [
            m.cls.__name__ if hasattr(m, "cls") else type(m).__name__
            for m in app.user_middleware
        ]
        assert "RequestLoggingMiddleware" in middleware_classes


class TestLifespan:
    """Tests for the lifespan context manager (startup/shutdown)."""

    @pytest_asyncio.fixture
    async def lifespan_app(self):
        """Create app and run lifespan manually for state inspection."""
        from contextlib import asynccontextmanager

        app = create_app()

        # Manually trigger the lifespan context manager
        async with app.router.lifespan_context(app):
            yield app

    @pytest.mark.asyncio
    async def test_lifespan_initializes_cache_manager(self, lifespan_app):
        """Lifespan startup initializes CacheManager in app.state."""
        from src.services.cache_manager import CacheManager

        assert hasattr(lifespan_app.state, "cache_manager")
        assert isinstance(lifespan_app.state.cache_manager, CacheManager)

    @pytest.mark.asyncio
    async def test_lifespan_initializes_response_builder(self, lifespan_app):
        """Lifespan startup initializes ResponseBuilder in app.state."""
        from src.services.response_builder import ResponseBuilder

        assert hasattr(lifespan_app.state, "response_builder")
        assert isinstance(lifespan_app.state.response_builder, ResponseBuilder)

    @pytest.mark.asyncio
    async def test_lifespan_initializes_start_time(self, lifespan_app):
        """Lifespan startup records start_time for uptime tracking."""
        assert hasattr(lifespan_app.state, "start_time")
        assert isinstance(lifespan_app.state.start_time, float)
        assert lifespan_app.state.start_time <= time.time()

    @pytest.mark.asyncio
    async def test_lifespan_initializes_shutting_down_flag(self, lifespan_app):
        """Lifespan startup sets shutting_down to False."""
        assert hasattr(lifespan_app.state, "shutting_down")
        assert lifespan_app.state.shutting_down is False

    @pytest.mark.asyncio
    async def test_lifespan_initializes_active_requests(self, lifespan_app):
        """Lifespan startup sets active_requests counter to 0."""
        assert hasattr(lifespan_app.state, "active_requests")
        assert lifespan_app.state.active_requests == 0


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior (503 rejection)."""

    @pytest.mark.asyncio
    async def test_rejects_requests_when_shutting_down(self):
        """Requests are rejected with 503 when shutting_down is True."""
        app = create_app()

        # Add a simple test route
        @app.get("/test")
        async def test_route():
            return {"status": "ok"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Set shutting_down flag
            app.state.shutting_down = True

            response = await client.get("/test")
            assert response.status_code == 503
            body = response.json()
            assert body["error"] == "Service Unavailable"
            assert "shutting down" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_normal_requests_succeed_before_shutdown(self):
        """Requests succeed normally when shutting_down is False."""
        app = create_app()

        @app.get("/test")
        async def test_route():
            return {"status": "ok"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


class TestCORSMiddleware:
    """Tests for CORS middleware configuration."""

    @pytest.mark.asyncio
    async def test_cors_headers_present(self):
        """CORS headers are included in responses for cross-origin requests."""
        app = create_app()

        @app.get("/test")
        async def test_route():
            return {"status": "ok"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/test",
                headers={
                    "origin": "http://localhost:3000",
                    "access-control-request-method": "GET",
                },
            )
            assert "access-control-allow-origin" in response.headers
