"""
Unit tests for debug API authentication.

Tests that authentication is properly enforced when enabled and
bypassed when disabled for all debug endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch

from src.api.app import create_app
from src.config.settings import Settings


class TestDebugAPIAuthentication:
    """Tests for debug API authentication functionality."""

    @pytest.fixture
    def app_with_auth_disabled(self):
        """Create app with authentication disabled."""
        with patch('src.config.settings.Settings') as mock_settings_class:
            mock_settings = Mock(spec=Settings)
            mock_settings.api_host = "0.0.0.0"
            mock_settings.api_port = 8000
            mock_settings.cache_ttl = 60
            mock_settings.log_level = "INFO"
            mock_settings.symbols_list = ["BTC/USDT:USDT"]
            mock_settings.mock_mode = False
            mock_settings.cors_origins_list = ["*"]
            mock_settings.shutdown_timeout = 30
            mock_settings.debug_api_auth_enabled = False
            mock_settings.debug_api_auth_token = ""
            
            mock_settings_class.return_value = mock_settings
            
            app = create_app()
            app.state.settings = mock_settings
            
            # Mock the debug service to avoid actual exchange connections
            mock_debug_service = Mock()
            mock_debug_service.fetch_raw_ticker = AsyncMock(return_value=Mock(
                success=True,
                data={"symbol": "BTCUSDT", "last": 50000.0},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"symbol": "BTCUSDT", "last": 50000.0},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_raw_open_interest = AsyncMock(return_value=Mock(
                success=True,
                data={"openInterest": 1000000.0},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"openInterest": 1000000.0},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_raw_funding_rate = Mock(return_value=Mock(
                success=True,
                data={"fundingRate": 0.0001},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"fundingRate": 0.0001},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_raw_long_short_ratio = Mock(return_value=Mock(
                success=True,
                data={"longShortRatio": 1.5},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"longShortRatio": 1.5},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_all_raw_data = AsyncMock(return_value=Mock(
                success=True,
                data={},
                metadata={},
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {},
                    "metadata": {}
                })
            ))
            mock_debug_service.check_exchange_health = AsyncMock(return_value=Mock(
                success=True,
                data={"status": "connected"},
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"status": "connected"},
                    "metadata": {"http_status": 200}
                })
            ))
            app.state.debug_service = mock_debug_service
            
            yield app

    @pytest.fixture
    def app_with_auth_enabled(self):
        """Create app with authentication enabled."""
        with patch('src.config.settings.Settings') as mock_settings_class:
            mock_settings = Mock(spec=Settings)
            mock_settings.api_host = "0.0.0.0"
            mock_settings.api_port = 8000
            mock_settings.cache_ttl = 60
            mock_settings.log_level = "INFO"
            mock_settings.symbols_list = ["BTC/USDT:USDT"]
            mock_settings.mock_mode = False
            mock_settings.cors_origins_list = ["*"]
            mock_settings.shutdown_timeout = 30
            mock_settings.debug_api_auth_enabled = True
            mock_settings.debug_api_auth_token = "test-secret-token"
            
            mock_settings_class.return_value = mock_settings
            
            app = create_app()
            app.state.settings = mock_settings
            
            # Mock the debug service to avoid actual exchange connections
            mock_debug_service = Mock()
            mock_debug_service.fetch_raw_ticker = AsyncMock(return_value=Mock(
                success=True,
                data={"symbol": "BTCUSDT", "last": 50000.0},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"symbol": "BTCUSDT", "last": 50000.0},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_raw_open_interest = AsyncMock(return_value=Mock(
                success=True,
                data={"openInterest": 1000000.0},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"openInterest": 1000000.0},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_raw_funding_rate = Mock(return_value=Mock(
                success=True,
                data={"fundingRate": 0.0001},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"fundingRate": 0.0001},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_raw_long_short_ratio = Mock(return_value=Mock(
                success=True,
                data={"longShortRatio": 1.5},
                error=None,
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"longShortRatio": 1.5},
                    "metadata": {"http_status": 200}
                })
            ))
            mock_debug_service.fetch_all_raw_data = AsyncMock(return_value=Mock(
                success=True,
                data={},
                metadata={},
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {},
                    "metadata": {}
                })
            ))
            mock_debug_service.check_exchange_health = AsyncMock(return_value=Mock(
                success=True,
                data={"status": "connected"},
                metadata=Mock(http_status=200),
                model_dump=Mock(return_value={
                    "success": True,
                    "data": {"status": "connected"},
                    "metadata": {"http_status": 200}
                })
            ))
            app.state.debug_service = mock_debug_service
            
            yield app

    def test_ticker_endpoint_without_auth_when_disabled(self, app_with_auth_disabled):
        """Test that ticker endpoint works without auth when authentication is disabled."""
        client = TestClient(app_with_auth_disabled)
        response = client.get("/api/v1/debug/exchange/ticker/BTCUSDT")
        
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_ticker_endpoint_without_auth_when_enabled(self, app_with_auth_enabled):
        """Test that ticker endpoint returns 401 without auth when authentication is enabled."""
        client = TestClient(app_with_auth_enabled)
        response = client.get("/api/v1/debug/exchange/ticker/BTCUSDT")
        
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]

    def test_ticker_endpoint_with_invalid_token(self, app_with_auth_enabled):
        """Test that ticker endpoint returns 401 with invalid token."""
        client = TestClient(app_with_auth_enabled)
        response = client.get(
            "/api/v1/debug/exchange/ticker/BTCUSDT",
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == 401
        assert "Invalid authentication credentials" in response.json()["detail"]

    def test_ticker_endpoint_with_valid_token(self, app_with_auth_enabled):
        """Test that ticker endpoint works with valid token."""
        client = TestClient(app_with_auth_enabled)
        response = client.get(
            "/api/v1/debug/exchange/ticker/BTCUSDT",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_open_interest_endpoint_requires_auth(self, app_with_auth_enabled):
        """Test that open interest endpoint requires authentication when enabled."""
        client = TestClient(app_with_auth_enabled)
        
        # Without auth
        response = client.get("/api/v1/debug/exchange/open-interest/BTCUSDT")
        assert response.status_code == 401
        
        # With valid auth
        response = client.get(
            "/api/v1/debug/exchange/open-interest/BTCUSDT",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        assert response.status_code == 200

    def test_funding_rate_endpoint_requires_auth(self, app_with_auth_enabled):
        """Test that funding rate endpoint requires authentication when enabled."""
        client = TestClient(app_with_auth_enabled)
        
        # Without auth
        response = client.get("/api/v1/debug/exchange/funding-rate/BTCUSDT")
        assert response.status_code == 401
        
        # With valid auth
        response = client.get(
            "/api/v1/debug/exchange/funding-rate/BTCUSDT",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        assert response.status_code == 200

    def test_long_short_ratio_endpoint_requires_auth(self, app_with_auth_enabled):
        """Test that long/short ratio endpoint requires authentication when enabled."""
        client = TestClient(app_with_auth_enabled)
        
        # Without auth
        response = client.get("/api/v1/debug/exchange/long-short-ratio/BTCUSDT")
        assert response.status_code == 401
        
        # With valid auth
        response = client.get(
            "/api/v1/debug/exchange/long-short-ratio/BTCUSDT",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        assert response.status_code == 200

    def test_aggregated_endpoint_requires_auth(self, app_with_auth_enabled):
        """Test that aggregated endpoint requires authentication when enabled."""
        client = TestClient(app_with_auth_enabled)
        
        # Without auth
        response = client.get("/api/v1/debug/exchange/all/BTCUSDT")
        assert response.status_code == 401
        
        # With valid auth
        response = client.get(
            "/api/v1/debug/exchange/all/BTCUSDT",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        assert response.status_code == 200

    def test_health_endpoint_requires_auth(self, app_with_auth_enabled):
        """Test that health endpoint requires authentication when enabled."""
        client = TestClient(app_with_auth_enabled)
        
        # Without auth
        response = client.get("/api/v1/debug/health")
        assert response.status_code == 401
        
        # With valid auth
        response = client.get(
            "/api/v1/debug/health",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        assert response.status_code == 200

    def test_all_endpoints_work_without_auth_when_disabled(self, app_with_auth_disabled):
        """Test that all endpoints work without authentication when auth is disabled."""
        client = TestClient(app_with_auth_disabled)
        
        endpoints = [
            "/api/v1/debug/exchange/ticker/BTCUSDT",
            "/api/v1/debug/exchange/open-interest/BTCUSDT",
            "/api/v1/debug/exchange/funding-rate/BTCUSDT",
            "/api/v1/debug/exchange/long-short-ratio/BTCUSDT",
            "/api/v1/debug/exchange/all/BTCUSDT",
            "/api/v1/debug/health",
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, f"Endpoint {endpoint} failed with status {response.status_code}"

    def test_bearer_token_format_validation(self, app_with_auth_enabled):
        """Test that only Bearer token format is accepted."""
        client = TestClient(app_with_auth_enabled)
        
        # Test with Basic auth (should fail)
        response = client.get(
            "/api/v1/debug/exchange/ticker/BTCUSDT",
            headers={"Authorization": "Basic dGVzdDp0ZXN0"}
        )
        assert response.status_code == 401
        
        # Test with no scheme (should fail)
        response = client.get(
            "/api/v1/debug/exchange/ticker/BTCUSDT",
            headers={"Authorization": "test-secret-token"}
        )
        assert response.status_code == 401
        
        # Test with Bearer scheme (should succeed)
        response = client.get(
            "/api/v1/debug/exchange/ticker/BTCUSDT",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        assert response.status_code == 200
