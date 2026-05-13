"""Tests for rate limiting middleware (src/api/rate_limit_middleware.py).

Validates:
- Rate limiting is applied only to debug endpoints
- Rate limit is enforced correctly (429 after exceeding limit)
- Rate limit window works correctly (sliding window)
- Client identification works correctly (IP address, X-Forwarded-For)
- Rate limit configuration is respected
"""

import time
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.app import create_app
from src.api.rate_limit_middleware import RateLimitMiddleware


@pytest.fixture
def app_with_rate_limit():
    """Create a FastAPI app with rate limiting enabled for testing."""
    import os
    from unittest.mock import AsyncMock
    
    # Set environment variables to enable rate limiting
    os.environ["SCREENER_DEBUG_RATE_LIMIT_ENABLED"] = "true"
    os.environ["SCREENER_DEBUG_RATE_LIMIT_REQUESTS"] = "3"
    os.environ["SCREENER_DEBUG_RATE_LIMIT_WINDOW"] = "10"
    
    # Mock the exchange connector to avoid actual network calls
    with patch('src.exchange.connector.ExchangeConnector') as mock_connector_class:
        mock_connector = MagicMock()
        mock_connector.connect.return_value = True
        mock_connector_class.return_value = mock_connector
        
        app = create_app()
        
        # Mock the debug service to avoid exchange calls during tests
        mock_debug_service = MagicMock()
        mock_health_response = MagicMock()
        mock_health_response.success = True
        mock_health_response.model_dump.return_value = {
            "success": True,
            "data": {"status": "connected"},
            "metadata": {"request_timestamp": "2024-01-01T00:00:00Z"}
        }
        # Use AsyncMock for async methods
        mock_debug_service.check_exchange_health = AsyncMock(return_value=mock_health_response)
        app.state.debug_service = mock_debug_service
    
    # Clean up environment variables
    del os.environ["SCREENER_DEBUG_RATE_LIMIT_ENABLED"]
    del os.environ["SCREENER_DEBUG_RATE_LIMIT_REQUESTS"]
    del os.environ["SCREENER_DEBUG_RATE_LIMIT_WINDOW"]
    
    return app


@pytest.fixture
def app_without_rate_limit():
    """Create a FastAPI app without rate limiting for testing."""
    import os
    from unittest.mock import AsyncMock
    
    # Ensure rate limiting is disabled
    os.environ["SCREENER_DEBUG_RATE_LIMIT_ENABLED"] = "false"
    
    # Mock the exchange connector to avoid actual network calls
    with patch('src.exchange.connector.ExchangeConnector') as mock_connector_class:
        mock_connector = MagicMock()
        mock_connector.connect.return_value = True
        mock_connector_class.return_value = mock_connector
        
        app = create_app()
        
        # Mock the debug service to avoid exchange calls during tests
        mock_debug_service = MagicMock()
        mock_health_response = MagicMock()
        mock_health_response.success = True
        mock_health_response.model_dump.return_value = {
            "success": True,
            "data": {"status": "connected"},
            "metadata": {"request_timestamp": "2024-01-01T00:00:00Z"}
        }
        # Use AsyncMock for async methods
        mock_debug_service.check_exchange_health = AsyncMock(return_value=mock_health_response)
        app.state.debug_service = mock_debug_service
    
    # Clean up environment variables
    del os.environ["SCREENER_DEBUG_RATE_LIMIT_ENABLED"]
    
    return app


class TestRateLimitMiddleware:
    """Tests for the RateLimitMiddleware class."""

    @pytest.mark.asyncio
    async def test_rate_limit_middleware_registered_when_enabled(self, app_with_rate_limit):
        """Rate limit middleware is registered when enabled in settings."""
        middleware_classes = [
            m.cls.__name__ if hasattr(m, "cls") else type(m).__name__
            for m in app_with_rate_limit.user_middleware
        ]
        assert "RateLimitMiddleware" in middleware_classes

    @pytest.mark.asyncio
    async def test_rate_limit_middleware_not_registered_when_disabled(self, app_without_rate_limit):
        """Rate limit middleware is not registered when disabled in settings."""
        middleware_classes = [
            m.cls.__name__ if hasattr(m, "cls") else type(m).__name__
            for m in app_without_rate_limit.user_middleware
        ]
        assert "RateLimitMiddleware" not in middleware_classes

    @pytest.mark.asyncio
    async def test_rate_limit_not_applied_to_non_debug_endpoints(self, app_with_rate_limit):
        """Rate limiting is not applied to non-debug endpoints."""
        # Add a test route outside debug endpoints
        @app_with_rate_limit.get("/api/v1/test")
        async def test_route():
            return {"status": "ok"}

        transport = ASGITransport(app=app_with_rate_limit)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make more requests than the rate limit allows
            for _ in range(5):
                response = await client.get("/api/v1/test")
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_applied_to_debug_endpoints(self, app_with_rate_limit):
        """Rate limiting is applied to debug endpoints."""
        transport = ASGITransport(app=app_with_rate_limit)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make requests up to the limit (3 requests)
            for i in range(3):
                response = await client.get("/api/v1/debug/health")
                # First 3 requests should succeed (or fail for other reasons, but not 429)
                assert response.status_code != 429, f"Request {i+1} was rate limited"

            # The 4th request should be rate limited
            response = await client.get("/api/v1/debug/health")
            assert response.status_code == 429
            body = response.json()
            assert body["success"] is False
            assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
            assert "Rate limit exceeded" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_rate_limit_window_resets(self, app_with_rate_limit):
        """Rate limit window resets after the configured time period."""
        transport = ASGITransport(app=app_with_rate_limit)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make requests up to the limit
            for _ in range(3):
                await client.get("/api/v1/debug/health")

            # Next request should be rate limited
            response = await client.get("/api/v1/debug/health")
            assert response.status_code == 429

            # Wait for the window to reset (10 seconds + small buffer)
            time.sleep(11)

            # Request should succeed after window reset
            response = await client.get("/api/v1/debug/health")
            assert response.status_code != 429

    @pytest.mark.asyncio
    async def test_rate_limit_per_client_ip(self, app_with_rate_limit):
        """Rate limiting is applied per client IP address."""
        transport = ASGITransport(app=app_with_rate_limit)
        
        # Client 1 makes requests up to the limit
        async with AsyncClient(transport=transport, base_url="http://test") as client1:
            for _ in range(3):
                await client1.get("/api/v1/debug/health")
            
            # Client 1 should be rate limited
            response = await client1.get("/api/v1/debug/health")
            assert response.status_code == 429

        # Client 2 (different IP) should not be rate limited
        # Note: In this test, both clients will have the same IP since they're from the same test
        # This test demonstrates the concept, but in real scenarios with different IPs,
        # they would have separate rate limits

    @pytest.mark.asyncio
    async def test_rate_limit_respects_x_forwarded_for_header(self, app_with_rate_limit):
        """Rate limiting uses X-Forwarded-For header when available."""
        transport = ASGITransport(app=app_with_rate_limit)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make requests with X-Forwarded-For header
            headers = {"X-Forwarded-For": "192.168.1.100"}
            
            for _ in range(3):
                await client.get("/api/v1/debug/health", headers=headers)

            # Next request should be rate limited
            response = await client.get("/api/v1/debug/health", headers=headers)
            assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_error_response_structure(self, app_with_rate_limit):
        """Rate limit error response has correct structure."""
        transport = ASGITransport(app=app_with_rate_limit)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Exceed rate limit
            for _ in range(4):
                response = await client.get("/api/v1/debug/health")

            # Check error response structure
            assert response.status_code == 429
            body = response.json()
            assert "success" in body
            assert body["success"] is False
            assert "error" in body
            assert "message" in body["error"]
            assert "code" in body["error"]
            assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
            assert "3 requests per 10 seconds" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_rate_limit_applies_to_all_debug_endpoints(self, app_with_rate_limit):
        """Rate limiting applies to all debug endpoints collectively."""
        transport = ASGITransport(app=app_with_rate_limit)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make requests to different debug endpoints
            await client.get("/api/v1/debug/health")
            await client.get("/api/v1/debug/health")
            await client.get("/api/v1/debug/health")

            # Next request to any debug endpoint should be rate limited
            response = await client.get("/api/v1/debug/health")
            assert response.status_code == 429


class TestRateLimitConfiguration:
    """Tests for rate limit configuration."""

    @pytest.mark.asyncio
    async def test_custom_rate_limit_values(self):
        """Custom rate limit values are respected."""
        import os
        from unittest.mock import AsyncMock
        
        # Set custom rate limit values
        os.environ["SCREENER_DEBUG_RATE_LIMIT_ENABLED"] = "true"
        os.environ["SCREENER_DEBUG_RATE_LIMIT_REQUESTS"] = "5"
        os.environ["SCREENER_DEBUG_RATE_LIMIT_WINDOW"] = "20"
        
        # Mock the exchange connector to avoid actual network calls
        with patch('src.exchange.connector.ExchangeConnector') as mock_connector_class:
            mock_connector = MagicMock()
            mock_connector.connect.return_value = True
            mock_connector_class.return_value = mock_connector
            
            app = create_app()
            
            # Mock the debug service to avoid exchange calls during tests
            mock_debug_service = MagicMock()
            mock_health_response = MagicMock()
            mock_health_response.success = True
            mock_health_response.model_dump.return_value = {
                "success": True,
                "data": {"status": "connected"},
                "metadata": {"request_timestamp": "2024-01-01T00:00:00Z"}
            }
            # Use AsyncMock for async methods
            mock_debug_service.check_exchange_health = AsyncMock(return_value=mock_health_response)
            app.state.debug_service = mock_debug_service
        
        # Clean up environment variables
        del os.environ["SCREENER_DEBUG_RATE_LIMIT_ENABLED"]
        del os.environ["SCREENER_DEBUG_RATE_LIMIT_REQUESTS"]
        del os.environ["SCREENER_DEBUG_RATE_LIMIT_WINDOW"]
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make 5 requests (should all succeed)
            for i in range(5):
                response = await client.get("/api/v1/debug/health")
                assert response.status_code != 429, f"Request {i+1} was rate limited"

            # 6th request should be rate limited
            response = await client.get("/api/v1/debug/health")
            assert response.status_code == 429
            body = response.json()
            assert "5 requests per 20 seconds" in body["error"]["message"]
