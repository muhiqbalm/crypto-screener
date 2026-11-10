"""Tests for debug router registration in the main application.

Uses the generated OpenAPI schema so the check does not depend on FastAPI's
internal route classes (which changed in newer FastAPI releases).
"""

import pytest

from src.api.app import create_app

DEBUG_PATHS = {
    "/api/v1/debug/health",
    "/api/v1/debug/exchange/ticker/{symbol}",
    "/api/v1/debug/exchange/open-interest/{symbol}",
    "/api/v1/debug/exchange/funding-rate/{symbol}",
    "/api/v1/debug/exchange/long-short-ratio/{symbol}",
    "/api/v1/debug/exchange/all/{symbol}",
}


@pytest.fixture(scope="module")
def openapi_paths():
    return create_app().openapi()["paths"]


class TestDebugRouterRegistration:

    def test_debug_router_registered(self, openapi_paths):
        assert DEBUG_PATHS <= set(openapi_paths)

    def test_debug_routes_count(self, openapi_paths):
        debug = {p for p in openapi_paths if p.startswith("/api/v1/debug")}
        assert debug == DEBUG_PATHS

    def test_debug_routes_methods(self, openapi_paths):
        for path in DEBUG_PATHS:
            assert set(openapi_paths[path]) == {"get"}, path
