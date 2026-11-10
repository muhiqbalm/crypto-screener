"""
Authentication tests for the debug API (/api/v1/debug/*).

The debug router is protected by src.api.auth.verify_debug_api_key, controlled
by SCREENER_REQUIRE_API_KEY and SCREENER_DEBUG_API_KEY:
- disabled  -> every request passes
- enabled   -> missing key = 401, wrong key = 403, correct debug key = 200
- the regular (browser-shipped) SCREENER_API_KEY does NOT unlock debug
- no debug key configured -> debug API closed (403 for any key)
"""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config.settings import Settings

API_KEY = "test-secret-key"
PUBLIC_KEY = "public-frontend-key"

ENDPOINTS = [
    "/api/v1/debug/exchange/ticker/BTCUSDT",
    "/api/v1/debug/exchange/open-interest/BTCUSDT",
    "/api/v1/debug/exchange/funding-rate/BTCUSDT",
    "/api/v1/debug/exchange/long-short-ratio/BTCUSDT",
    "/api/v1/debug/exchange/all/BTCUSDT",
    "/api/v1/debug/health",
]


def _service_response(data):
    payload = {"success": True, "data": data, "metadata": {"http_status": 200}}
    return Mock(
        success=True,
        data=data,
        error=None,
        metadata=Mock(http_status=200),
        model_dump=Mock(return_value=payload),
    )


def _mock_debug_service():
    service = Mock()
    service.fetch_raw_ticker = AsyncMock(return_value=_service_response({"last": 50000.0}))
    service.fetch_raw_open_interest = AsyncMock(return_value=_service_response({"openInterest": 1e6}))
    service.fetch_raw_funding_rate = AsyncMock(return_value=_service_response({"fundingRate": 0.0001}))
    service.fetch_raw_long_short_ratio = AsyncMock(return_value=_service_response({"longShortRatio": 1.5}))
    service.fetch_all_raw_data = AsyncMock(return_value=_service_response({}))
    service.check_exchange_health = AsyncMock(return_value=_service_response({"status": "connected"}))
    return service


def _client(require_api_key: bool, debug_api_key: str | None = None) -> TestClient:
    app = create_app()
    app.state.settings = Settings(
        symbols="BTC/USDT:USDT",
        require_api_key=require_api_key,
        api_key=PUBLIC_KEY if require_api_key else "",
        debug_api_key=(API_KEY if require_api_key else "") if debug_api_key is None else debug_api_key,
    )
    app.state.debug_service = _mock_debug_service()
    # No `with` block: the lifespan (exchange/trading startup) is not run.
    return TestClient(app)


@pytest.fixture
def client_auth_disabled():
    return _client(require_api_key=False)


@pytest.fixture
def client_auth_enabled():
    return _client(require_api_key=True)


class TestDebugAPIAuthentication:

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_endpoint_open_when_auth_disabled(self, client_auth_disabled, endpoint):
        response = client_auth_disabled.get(endpoint)
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_endpoint_requires_key_when_enabled(self, client_auth_enabled, endpoint):
        response = client_auth_enabled.get(endpoint)
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_endpoint_rejects_wrong_key(self, client_auth_enabled, endpoint):
        response = client_auth_enabled.get(endpoint, headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid API key."

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_endpoint_accepts_valid_key(self, client_auth_enabled, endpoint):
        response = client_auth_enabled.get(endpoint, headers={"X-API-Key": API_KEY})
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_bearer_token_is_not_accepted(self, client_auth_enabled):
        """Only the X-API-Key header authenticates; an Authorization header does not."""
        response = client_auth_enabled.get(
            ENDPOINTS[0], headers={"Authorization": f"Bearer {API_KEY}"}
        )
        assert response.status_code == 401


class TestDebugKeySeparation:

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_public_frontend_key_does_not_unlock_debug(self, client_auth_enabled, endpoint):
        response = client_auth_enabled.get(endpoint, headers={"X-API-Key": PUBLIC_KEY})
        assert response.status_code == 403

    def test_debug_closed_when_no_debug_key_configured(self):
        client = _client(require_api_key=True, debug_api_key="")
        for key in (PUBLIC_KEY, API_KEY):
            response = client.get(ENDPOINTS[-1], headers={"X-API-Key": key})
            assert response.status_code == 403
        # An empty header must not match an empty (unset) debug key.
        response = client.get(ENDPOINTS[-1], headers={"X-API-Key": ""})
        assert response.status_code in (401, 403)

    def test_public_key_still_unlocks_screener(self):
        client = TestClient(_client(require_api_key=True).app, raise_server_exceptions=False)
        # Screener auth is unchanged: it accepts the regular key (the request
        # itself may fail without a warmed cache, but must pass auth).
        response = client.get("/api/v1/screener/summary", headers={"X-API-Key": PUBLIC_KEY})
        assert response.status_code not in (401, 403)
