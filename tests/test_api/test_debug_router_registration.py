"""Tests for debug router registration in the main application.

Validates:
- Debug router is properly registered
- Debug routes are available in the application
"""

import pytest
from src.api.app import create_app


class TestDebugRouterRegistration:
    """Tests for debug router registration."""

    @pytest.fixture
    def app(self):
        """Create a fresh FastAPI app instance for testing."""
        return create_app()

    def test_debug_router_registered(self, app):
        """Debug router is registered in the application."""
        # Get all routes from the app
        routes = [route.path for route in app.routes]
        
        # Check that debug routes are present
        assert "/api/v1/debug/health" in routes
        assert "/api/v1/debug/exchange/ticker/{symbol}" in routes
        assert "/api/v1/debug/exchange/open-interest/{symbol}" in routes
        assert "/api/v1/debug/exchange/funding-rate/{symbol}" in routes
        assert "/api/v1/debug/exchange/long-short-ratio/{symbol}" in routes
        assert "/api/v1/debug/exchange/all/{symbol}" in routes

    def test_debug_routes_count(self, app):
        """All 6 debug endpoints are registered."""
        debug_routes = [
            route for route in app.routes 
            if route.path.startswith("/api/v1/debug")
        ]
        assert len(debug_routes) == 6

    def test_debug_routes_methods(self, app):
        """All debug routes use GET method."""
        debug_routes = [
            route for route in app.routes 
            if route.path.startswith("/api/v1/debug")
        ]
        
        for route in debug_routes:
            assert "GET" in route.methods
