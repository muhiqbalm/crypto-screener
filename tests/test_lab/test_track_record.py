"""Screener track record: pooled ledger stats per signal type + direction, cache, auth."""
import pytest

from src.lab.ledger import scoring, track_record as tr
from src.lab.ledger.store import ensure_schema, insert_signal, iso, to_epoch

T0 = int(to_epoch("2026-10-01T00:00:00Z"))


def rising_bars(sym, a, b):
    # 15m bars, price rises 0.05 % per bar: long wins, short loses; BTC flat
    out, step = [], 900
    for i in range(int((b - a) // step) + 2):
        ts = (a // step) * step + i * step
        if sym == "BTCUSDT":
            o = c = 100.0
        else:
            o, c = 100 * 1.0005 ** i, 100 * 1.0005 ** (i + 1)
        out.append({"ts": ts * 1000, "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": 1.0})
    return out


def seed(conn):
    ensure_schema(conn)
    for i in range(12):  # tier_a long, 12 signals on 12 days, alternating coins
        insert_signal(conn, source="screener_rekon" if i < 10 else "screener", signal_type="tier_a",
                      symbol="ETHUSDT" if i % 2 else "SOLUSDT", direction=1,
                      ts=iso(T0 + i * 86400 + (i % 3) * 3600), dedupe_key=f"a{i}")
    for i in range(4):  # tier_c short, too few
        insert_signal(conn, source="screener_rekon", signal_type="tier_c", symbol="ETHUSDT", direction=-1,
                      ts=iso(T0 + i * 86400), dedupe_key=f"c{i}")
    insert_signal(conn, source="lab_watch", signal_type="tier_a", symbol="ETHUSDT", direction=1,
                  ts=iso(T0), dedupe_key="w0")  # other source: ignored
    insert_signal(conn, source="screener", signal_type="komposit", symbol="ETHUSDT", direction=-1,
                  ts=iso(T0 + 40 * 86400), dedupe_key="pending")  # not scored yet
    conn.commit()
    scoring.score_pending(conn, lambda s, a, b: rising_bars(s, a // 1000, b // 1000), now_s=T0 + 30 * 86400)


def by(items, t, d):
    return next(i for i in items if i["signal_type"] == t and i["direction"] == d)


def test_compute_pools_screener_sources_and_maps_verdicts(conn):
    seed(conn)
    out = tr.compute(conn)
    assert out["headline_horizon"] == "1d" and out["secondary_horizon"] == "3d"
    a = by(out["items"], "tier_a", 1)
    assert (a["n_signals"], a["n_live"], a["n_rekon"]) == (12, 2, 10)
    h = a["stats"]["1d"]
    assert h["n"] == 12 and h["days"] == 12 and h["hit_rate"] == 1.0 and h["coins"] == 2
    assert a["verdict"] == "terbukti" == h["verdict"] and a["verdict_rel_btc"] == "terbukti"
    assert set(a["stats"]) == {"1d", "3d"}
    c = by(out["items"], "tier_c", -1)
    assert c["verdict"] == "belum_cukup_data" and c["stats"]["1d"]["hit_rate"] == 0.0
    k = by(out["items"], "komposit", -1)
    assert k["n_pending"] == 1 and k["stats"]["1d"]["n"] == 0 and k["verdict"] == "belum_cukup_data"
    # order follows the screener's type list, lab_watch never appears
    assert [i["signal_type"] for i in out["items"]] == ["komposit", "tier_a", "tier_c"]
    assert out["period"]["from"] == iso(T0)


def test_compute_without_ledger_tables_is_empty(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "empty.db")
    c.row_factory = sqlite3.Row
    assert tr.compute(c)["items"] == []


def test_ttl_cache_reuses_value_and_caches_errors_briefly():
    now = [0.0]
    cache = tr.TTLCache(ttl_s=600, error_ttl_s=60, clock=lambda: now[0])
    calls = []
    assert cache.get(lambda: calls.append(1) or "v1", lambda e: "err") == "v1"
    now[0] = 599
    assert cache.get(lambda: "v2", lambda e: "err") == "v1"
    now[0] = 601

    def boom():
        raise RuntimeError("db locked")
    assert cache.get(boom, lambda e: f"err:{e}") == "err:db locked"
    now[0] = 650
    assert cache.get(lambda: "v3", lambda e: "err") == "err:db locked"
    now[0] = 662
    assert cache.get(lambda: "v3", lambda e: "err") == "v3"


@pytest.fixture
def client_for(lab_env):
    from fastapi.testclient import TestClient
    from src.api import ledger_routes
    from src.api.app import create_app
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers

    ledger_routes._tr_caches.clear()

    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        if sub is not None:
            app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    yield make
    ledger_routes._tr_caches.clear()


PATH = "/api/v1/screener/signal-track-record"


def test_api_needs_login_but_not_admin(client_for, conn):
    seed(conn)
    assert client_for(None).get(PATH).status_code == 401
    r = client_for("u-plain").get(PATH)  # non-admin, logged in
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and by(body["items"], "tier_a", 1)["verdict"] == "terbukti"
    # admin-only ledger endpoints stay admin-only
    assert client_for("u-plain").get("/api/v1/lab/ledger/summary").status_code == 403


def test_api_is_cached(client_for, conn):
    seed(conn)
    c = client_for("u-plain")
    first = c.get(PATH).json()
    insert_signal(conn, source="screener", signal_type="oi", symbol="ETHUSDT", direction=1, ts=iso(T0),
                  dedupe_key="late")
    conn.commit()
    second = c.get(PATH).json()
    assert second == first and not any(i["signal_type"] == "oi" for i in second["items"])


def test_api_missing_db_degrades_gracefully(client_for, lab_env, monkeypatch):
    from src.lab import settings as lab_settings
    monkeypatch.setenv("LAB_DB_PATH", str(lab_env / "nope" / "lab.db"))
    lab_settings.get_lab_settings.cache_clear()
    r = client_for("u-plain").get(PATH)
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["items"] == []
    assert not (lab_env / "nope" / "lab.db").exists()  # read-only: never creates the file
