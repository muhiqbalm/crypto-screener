"""Security hardening regression tests (audit 2026-11).

- Auth endpoints are rate limited per client IP; the TradingView webhook and
  other routes are never touched by that limiter.
- The limiter keys on the proxy-observed IP (X-Real-IP / last XFF hop), so a
  client cannot dodge it by sending its own X-Forwarded-For.
- Screener error responses do not echo exception text.
- CORS never combines a wildcard origin with credentials.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.app import AUTH_RATE_LIMITED_PATHS, create_app
from src.api.rate_limit_middleware import AuthRateLimitMiddleware, RateLimitMiddleware
from src.config.settings import Settings


def _limited_app(max_requests=3, window=60, **kw) -> FastAPI:
    app = FastAPI()

    @app.post("/trading/auth/login")
    async def login():
        return {"ok": True}

    @app.post("/trading/auth/refresh")
    async def refresh():
        return {"ok": True}

    @app.get("/trading/auth/login")
    async def login_get():
        return {"ok": True}

    @app.post("/webhook/tradingview")
    async def webhook():
        return {"ok": True}

    app.add_middleware(
        AuthRateLimitMiddleware,
        max_requests=max_requests,
        window_seconds=window,
        path_prefixes=AUTH_RATE_LIMITED_PATHS,
        methods=("POST",),
        **kw,
    )
    return app


class TestAuthRateLimit:

    def test_login_limited_after_max_requests(self):
        client = TestClient(_limited_app())
        for _ in range(3):
            assert client.post("/trading/auth/login").status_code == 200
        r = client.post("/trading/auth/login")
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert r.headers["Retry-After"] == "60"

    def test_webhook_never_limited(self):
        client = TestClient(_limited_app(max_requests=1))
        for _ in range(20):
            assert client.post("/webhook/tradingview").status_code == 200

    def test_only_post_is_limited(self):
        client = TestClient(_limited_app(max_requests=1))
        for _ in range(5):
            assert client.get("/trading/auth/login").status_code == 200

    def test_buckets_are_per_real_ip(self):
        client = TestClient(_limited_app(max_requests=2))
        a = {"X-Real-IP": "203.0.113.1"}
        b = {"X-Real-IP": "203.0.113.2"}
        for _ in range(2):
            assert client.post("/trading/auth/login", headers=a).status_code == 200
        assert client.post("/trading/auth/login", headers=a).status_code == 429
        assert client.post("/trading/auth/login", headers=b).status_code == 200

    def test_spoofed_xff_first_hop_does_not_reset_bucket(self):
        client = TestClient(_limited_app(max_requests=2))
        # nginx appends the real peer as the LAST hop; the first hop is attacker-controlled.
        for i in range(2):
            h = {"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.7"}
            assert client.post("/trading/auth/login", headers=h).status_code == 200
        h = {"X-Forwarded-For": "10.9.9.9, 198.51.100.7"}
        assert client.post("/trading/auth/login", headers=h).status_code == 429

    def test_x_real_ip_wins_over_xff(self):
        mw = RateLimitMiddleware(app=None)
        req = MagicMock()
        req.headers = {"X-Real-IP": "198.51.100.9", "X-Forwarded-For": "1.1.1.1"}
        assert mw._get_client_identifier(req) == "198.51.100.9"


class TestAppWiring:

    def _app(self, **env):
        with patch("src.exchange.connector.ExchangeConnector"):
            with patch.dict("os.environ", env):
                return create_app()

    def test_auth_limiter_registered_by_default(self):
        names = [m.cls.__name__ for m in self._app().user_middleware]
        assert "AuthRateLimitMiddleware" in names
        assert "RateLimitMiddleware" in names  # debug limiter is on by default

    def test_auth_limiter_can_be_disabled(self):
        names = [m.cls.__name__ for m in self._app(SCREENER_AUTH_RATE_LIMIT_ENABLED="false").user_middleware]
        assert "AuthRateLimitMiddleware" not in names

    def test_auth_paths_cover_login_refresh_register_only(self):
        assert set(AUTH_RATE_LIMITED_PATHS) == {
            "/trading/auth/login", "/trading/auth/refresh", "/trading/auth/register"
        }
        assert not any(p.startswith("/webhook") for p in AUTH_RATE_LIMITED_PATHS)


class TestCors:

    def test_wildcard_origin_disables_credentials(self):
        assert Settings(cors_origins="*").cors_allow_credentials is False

    def test_explicit_origin_keeps_credentials(self):
        assert Settings(cors_origins="https://bmtm-trade.duckdns.org").cors_allow_credentials is True


class TestScreenerErrorLeakage:

    def test_internal_error_message_is_generic(self):
        app = create_app()
        app.state.settings = Settings(symbols="BTC/USDT:USDT", require_api_key=False)
        cache = MagicMock()
        cache.get.side_effect = RuntimeError("secret internal path /root/crypto-screener/.env")
        app.state.cache_manager = cache
        app.state.data_processor = MagicMock()
        app.state.response_builder = MagicMock()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/screener/summary")
        assert r.status_code == 500
        assert "/root" not in r.text and "secret" not in r.text
