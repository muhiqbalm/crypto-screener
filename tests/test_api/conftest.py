"""Shared fixtures for API tests."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def mock_debug_service_for_rate_limit_tests(request):
    """Auto-mock debug service for rate limit tests to avoid exchange connections.
    
    This fixture is automatically applied to all tests in the test_api directory.
    It mocks the debug service after app creation to avoid actual exchange connections.
    """
    # Only apply to rate limit middleware tests
    if "test_rate_limit_middleware" not in str(request.fspath):
        return
    
    # Get the app fixture if it exists
    if "app_with_rate_limit" in request.fixturenames or "app_without_rate_limit" in request.fixturenames:
        def _mock_debug_service(app):
            """Mock the debug service on the app."""
            mock_debug_service = MagicMock()
            mock_health_response = MagicMock()
            mock_health_response.success = True
            mock_health_response.model_dump.return_value = {
                "success": True,
                "data": {"status": "connected"},
                "metadata": {"request_timestamp": "2024-01-01T00:00:00Z"}
            }
            mock_debug_service.check_exchange_health.return_value = mock_health_response
            app.state.debug_service = mock_debug_service
            return app
        
        # Store the mock function for use in fixtures
        request.node._mock_debug_service = _mock_debug_service
