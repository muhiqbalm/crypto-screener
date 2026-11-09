"""API auth + contract shape. Uses a fake users table; never touches bmtm_trading.db."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.trading.active_user_guard import active_user_guard
from src.trading.router import get_supabase_client


class _Resp:
    def __init__(self, data):
        self.data = data


class FakeUsers:
    def __init__(self, emails):
        self.emails = emails
        self._id = None

    def table(self, name):
        assert name == "users"
        return self

    def select(self, *_):
        return self

    def eq(self, col, val):
        self._id = val
        return self

    def single(self):
        return self

    def execute(self):
        e = self.emails.get(self._id)
        return _Resp({"email": e} if e else None)


EMAILS = {"u-admin": "Boss@BMTM.io", "u-plain": "someone@x.io", "admin-uuid-1": "other@x.io"}


@pytest.fixture
def client_for(lab_env):
    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        if sub is not None:
            app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    return make


RUN = {"template_id": "rosyade_family", "symbol": "ETHUSDT", "timeframe": "4h", "mode": "backtest",
       "params": {}, "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}}


def test_no_token_is_401(client_for):
    c = client_for(None)
    assert c.get("/api/v1/lab/me").status_code == 401
    assert c.get("/api/v1/lab/templates").status_code == 401


def test_non_admin_gets_403_everywhere(client_for):
    c = client_for("u-plain")
    assert c.get("/api/v1/lab/me").json() == {"is_admin": False}
    for path in ("/api/v1/lab/templates", "/api/v1/lab/runs", "/api/v1/lab/symbols", "/api/v1/lab/scans",
                 "/api/v1/lab/data/status", "/api/v1/lab/runs/1", "/api/v1/lab/jobs/1"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/v1/lab/runs", json=RUN).status_code == 403
    assert c.post("/api/v1/lab/jobs/1/cancel").status_code == 403


def test_admin_by_email_case_insensitive(client_for):
    c = client_for("u-admin")
    assert c.get("/api/v1/lab/me").json() == {"is_admin": True}
    assert c.get("/api/v1/lab/templates").status_code == 200


def test_admin_by_user_id(client_for):
    c = client_for("admin-uuid-1")
    assert c.get("/api/v1/lab/me").json() == {"is_admin": True}


def test_empty_admin_list_denies(client_for, monkeypatch):
    from src.lab import settings
    monkeypatch.setenv("LAB_ADMIN_EMAILS", "")
    settings.get_lab_settings.cache_clear()
    c = client_for("u-admin")
    assert c.get("/api/v1/lab/me").json() == {"is_admin": False}
    assert c.get("/api/v1/lab/runs").status_code == 403


def test_run_lifecycle_contract(client_for):
    c = client_for("u-admin")
    t = c.get("/api/v1/lab/templates").json()
    assert t[0]["id"] == "rosyade_family" and t[0]["params"]
    r = c.post("/api/v1/lab/runs", json=RUN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"run_id", "job_id"}
    lst = c.get("/api/v1/lab/runs?limit=5").json()
    assert lst[0]["id"] == body["run_id"] and lst[0]["status"] == "queued" and lst[0]["verdict"] is None
    for k in ("id", "template_id", "symbol", "timeframe", "mode", "status", "verdict", "net_return_pct",
              "profit_factor", "max_dd_pct", "trades", "created_at"):
        assert k in lst[0]
    d = c.get(f"/api/v1/lab/runs/{body['run_id']}").json()
    for k in ("params", "costs", "start", "end", "metrics", "oos_metrics", "checks", "holdout_touches",
              "engine_commit", "error", "best_params"):
        assert k in d
    assert d["params"]["long_sl_pct"] == 13.0
    assert c.get(f"/api/v1/lab/runs/{body['run_id']}/equity").json() == []
    assert c.get(f"/api/v1/lab/runs/{body['run_id']}/trades").json() == []
    j = c.get(f"/api/v1/lab/jobs/{body['job_id']}").json()
    assert j["status"] == "queued"
    assert c.post(f"/api/v1/lab/jobs/{body['job_id']}/cancel").json()["status"] == "cancelled"
    assert c.get(f"/api/v1/lab/runs/{body['run_id']}").json()["status"] == "cancelled"
    assert c.get("/api/v1/lab/runs/999").status_code == 404


@pytest.mark.parametrize("patch", [
    {"template_id": "nope"},
    {"timeframe": "15m"},
    {"symbol": "ETH"},
    {"params": {"long_sl_pct": 500}},
    {"params": {"unknown": 1}},
    {"mode": "live"},
    {"start": "2023-13-01"},
    {"start": "2024-01-01", "end": "2023-01-01"},
    {"costs": {"commission_pct": 5}},
])
def test_run_validation_422(client_for, patch):
    c = client_for("u-admin")
    assert c.post("/api/v1/lab/runs", json={**RUN, **patch}).status_code == 422


def test_symbol_normalisation(client_for):
    c = client_for("u-admin")
    r = c.post("/api/v1/lab/runs", json={**RUN, "symbol": "eth/usdt:usdt"})
    assert r.status_code == 200
    assert c.get(f"/api/v1/lab/runs/{r.json()['run_id']}").json()["symbol"] == "ETHUSDT"


def test_scan_creates_one_run_per_combo(client_for):
    c = client_for("u-admin")
    r = c.post("/api/v1/lab/scans", json={"template_id": "rosyade_family", "symbols": ["ETHUSDT", "BTCUSDT"],
                                          "timeframes": ["4h", "1d"], "mode": "validate",
                                          "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}})
    assert r.status_code == 200, r.text
    s = c.get(f"/api/v1/lab/scans/{r.json()['scan_id']}").json()
    assert s["progress"] == {"done": 0, "total": 4} and s["status"] == "queued"
    assert {(x["symbol"], x["timeframe"]) for x in s["rows"]} == {
        ("ETHUSDT", "4h"), ("ETHUSDT", "1d"), ("BTCUSDT", "4h"), ("BTCUSDT", "1d")}
    for row in s["rows"]:
        assert set(row) >= {"symbol", "timeframe", "run_id", "status", "verdict", "oos_net_return_pct",
                            "oos_profit_factor", "oos_max_dd_pct", "trades"}
    assert c.get("/api/v1/lab/scans").json()[0]["id"] == s["id"]


def test_symbols_and_data_status(client_for):
    c = client_for("u-admin")
    syms = c.get("/api/v1/lab/symbols").json()
    assert any(s["symbol"] == "ETHUSDT" for s in syms)
    assert all(set(s) == {"symbol", "has_data", "timeframes"} for s in syms)
    assert c.get("/api/v1/lab/data/status").json() == []


def test_app_still_starts_with_lab_router(lab_env):
    app = create_app()
    c = TestClient(app)  # no lifespan: avoids exchange/trading startup side effects in tests
    spec = c.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/lab/runs" in paths and "/api/v1/lab/runs/{run_id}" in paths
    assert any("webhook" in p for p in paths)  # live trading routes still registered
