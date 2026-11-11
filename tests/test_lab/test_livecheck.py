"""Cek bot live vs strategi: log parsing (plain + gz), sanitising, delivery assembly,
per-bar matching, job, schedule and API.

No network, no engine: expected signals come from a fake ``compute_fn``; logs and
bmtm_trading.db are throw-away files in tmp_path.
"""
import gzip
import json
import pathlib
import sqlite3

import pytest

from src.lab import queue as q
from src.lab.ledger.store import iso, kv_get, to_epoch
from src.lab.livecheck import jobs, logs, match, report, schedule
from src.lab.livecheck.store import ensure_schema, livecheck_settings

H4 = 14_400
TV_IP = "52.89.214.238"
B0 = int(to_epoch("2026-11-04T12:00:00Z"))      # open of the signal bar; its close (alert) is B0 + H4


def _nginx(ts: float, status: int = 202, ip: str = TV_IP, ua: str = "TradingView Webhook",
           method: str = "POST", path: str = "/webhook/tradingview") -> str:
    from datetime import datetime, timezone
    t = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
    return f'{ip} - - [{t}] "{method} {path} HTTP/1.1" {status} 0 "-" "{ua}"'


def _app(ts: float, message: str, logger: str = "src.trading.router", **extra) -> str:
    from datetime import datetime, timezone
    t = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    return json.dumps({"timestamp": t, "level": "INFO", "logger": logger, "message": message, **extra})


def _done(ts: float, status: int, ms: float = 40.0) -> str:
    return _app(ts, "Request completed", "src.api.app", endpoint="/webhook/tradingview", method="POST",
                status_code=status, response_time_ms=ms)


def _trading_db(path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE trade_logs (id TEXT, user_id TEXT, symbol TEXT, action TEXT, side TEXT, exchange TEXT, "
              "size_value REAL, status TEXT, order_id TEXT, fill_price REAL, filled_quantity REAL, created_at TEXT, "
              "error_details TEXT)")
    c.execute("CREATE TABLE positions (id TEXT, user_id TEXT, symbol TEXT, side TEXT, size REAL, entry_price REAL, "
              "status TEXT, exchange TEXT, created_at TEXT, closed_at TEXT, quantity REAL, exit_price REAL)")
    c.execute("CREATE TABLE webhook_configs (id TEXT, user_id TEXT, passphrase TEXT)")
    c.execute("INSERT INTO webhook_configs VALUES ('w', 'user-rosyade-02', 'super-secret')")
    for i, r in enumerate(rows):
        c.execute("INSERT INTO trade_logs VALUES (?, 'user-rosyade-02', ?, ?, ?, 'binance', 50, ?, 'o1', ?, ?, ?, ?)",
                  (f"r{i}", r.get("symbol", "ETH/USDT:USDT"), r["action"], r["side"], r["status"], r.get("fill"),
                   r.get("qty"), iso(r["ts"]).replace("Z", "+00:00"), r.get("err")))
    c.commit()
    c.close()


def ev(action, side, bar_open, alert="close", price=2000.0, reason=None):
    return {"key": f"{action}|{side}|{int(bar_open)}", "action": action, "side": side, "bar_open": bar_open,
            "alert": alert, "price": price, "reason": reason}


@pytest.fixture
def lc_env(lab_env, monkeypatch):
    nginx_dir = lab_env / "nginx"
    nginx_dir.mkdir()
    app_dir = lab_env / "pm2"
    app_dir.mkdir()
    monkeypatch.setenv("LAB_LIVECHECK_NGINX_GLOB", str(nginx_dir / "access.log*"))
    monkeypatch.setenv("LAB_LIVECHECK_APP_GLOBS", str(app_dir / "bmtm-api-out*.log*"))
    monkeypatch.setenv("LAB_LIVECHECK_SINCE", "2026-11-01")
    monkeypatch.setenv("LAB_LIVECHECK_LOCAL_IPS", "198.51.100.7")
    monkeypatch.setenv("LAB_TRADING_DB_PATH", str(lab_env / "bmtm_trading.db"))
    return {"nginx": nginx_dir, "app": app_dir, "root": lab_env}


# ── logs ─────────────────────────────────────────────────────────────────────

def test_parse_nginx_filters_local_get_and_other_paths():
    t = B0 + H4 + 5
    f = logs.parse_nginx(_nginx(t, 499), "/webhook/tradingview")
    assert f == {"ts": t, "status": 499, "tv": True, "ip": "52.89.x.x", "ua": "TradingView"}
    assert logs.parse_nginx(_nginx(t, ip="127.0.0.1"), "/webhook/tradingview") is None
    assert logs.parse_nginx(_nginx(t, ip="10.0.0.3"), "/webhook/tradingview") is None
    assert logs.parse_nginx(_nginx(t, ip="198.51.100.7"), "/webhook/tradingview", ["198.51.100.7"]) is None
    assert logs.parse_nginx(_nginx(t, method="GET", status=405), "/webhook/tradingview") is None
    assert logs.parse_nginx(_nginx(t, path="/webhook?_rsc=x"), "/webhook/tradingview") is None
    curl = logs.parse_nginx(_nginx(t, 401, ip="8.8.4.4", ua="curl/8.7.1"), "/webhook/tradingview")
    assert curl["tv"] is False and curl["ua"] == "curl" and curl["ip"] == "8.8.x.x"


def test_parse_app_lines():
    t = B0 + H4
    assert logs.parse_app(_done(t, 409, 2817.6), "/webhook/tradingview") == ("done", t, {"status": 409, "ms": 2817.6})
    assert logs.parse_app(_app(t, "Order placed: symbol=ETH/USDT:USDT side=sell quantity=6.0 order_id=8389766305917338253",
                               "src.trading.executor"), "/webhook/tradingview") == \
        ("order", t, {"symbol": "ETH/USDT:USDT", "trade_dir": -1})
    kind, _, data = logs.parse_app(_app(t, "Order execution failed for user=user-rosyade-02 symbol=ETH/USDT:USDT: "
                                           "binance {\"code\":-2015,\"msg\":\"Invalid API-key\"}"), "/webhook/tradingview")
    assert kind == "fail" and "rosyade" not in json.dumps(data) and "-2015" in data["reason"]
    assert logs.parse_app(_done(t, 200) .replace("/webhook/tradingview", "/api/v1/health"), "/webhook/tradingview") is None
    assert logs.parse_app("not json at all webhook", "/webhook/tradingview") is None


def test_sanitize_strips_ids_and_secrets():
    s = logs.sanitize("An open position for 'ETH/USDT:USDT' already exists on the exchange for user "
                      "'user-rosyade-02' passphrase=hunter2 id 41c83acf-70d6-442a-b6d4-7d3520f7b365 "
                      "order 8389766305917338253 mail a@b.io")
    assert "rosyade" not in s and "hunter2" not in s and "41c83acf" not in s and "8389766305917338253" not in s
    assert "a@b.io" not in s and "already exists on the exchange" in s


def test_collect_reads_gz_and_tracks_coverage(lc_env):
    t = B0 + H4
    (lc_env["nginx"] / "access.log").write_text("\n".join([
        '1.2.3.4 - - [04/Nov/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 1 "-" "x"',
        _nginx(t + 4, 202)]) + "\n")
    with gzip.open(lc_env["nginx"] / "access.log.2.gz", "wt") as fh:
        fh.write(_nginx(t - 3 * 86400, 499) + "\n" + _nginx(t - 3 * 86400 + 60, 401, ip="127.0.0.1") + "\n")
    (lc_env["app"] / "bmtm-api-out.log").write_text(_done(t + 5, 202) + "\nplain text line\n")
    cfg = livecheck_settings()
    got = logs.collect(cfg.nginx_glob, cfg.app_globs, cfg.webhook_path, cfg.local_ips, now=t + 600)
    hits = [e for e in got["evidence"] if e["kind"] == "hit"]
    assert sorted(h["data"]["status"] for h in hits) == [202, 499]
    assert len(got["sigs"]) == 1 and got["sigs"][0].startswith("access.log.2.gz|")
    assert any(c[2] == "app" for c in got["coverage"]) and any(c[2] == "nginx" for c in got["coverage"])
    again = logs.collect(cfg.nginx_glob, cfg.app_globs, cfg.webhook_path, cfg.local_ips, skip_sigs=got["sigs"],
                         now=t + 600)
    assert sorted(h["data"]["status"] for h in again["evidence"] if h["kind"] == "hit") == [202]
    cov = logs.merge_intervals([[0, 10, "a"], [20, 30, "b"], [100000, 100010, "a"]], tolerance_s=15)
    assert cov == [[0.0, 30.0, "a+b"], [100000.0, 100010.0, "a"]]


# ── matching ─────────────────────────────────────────────────────────────────

def _nginx_ev(t, status=202, tv=True):
    return {"source": "nginx", "kind": "hit", "ts": t, "data": {"status": status, "tv": tv, "ip": "52.89.x.x",
                                                               "ua": "TradingView" if tv else "curl"}}


def _app_ev(kind, t, **data):
    return {"source": "app", "kind": kind, "ts": t, "data": data}


def run_match(variants, evidence, tl, now, coverage=None, nginx_cov=None, price_bps=30.0):
    cov = coverage if coverage is not None else [[B0 - 30 * 86400, now, "nginx"]]
    dl = match.build_deliveries(evidence, tl, "ETHUSDT", nginx_cov if nginx_cov is not None else cov, now)
    primary, alt = match.merge_variants(variants)
    return match.match(primary, alt, dl, step=H4, coverage=cov, now=now, data_last_bar=now - now % H4 - H4,
                       price_bps=price_bps)


def test_merge_variants_causes():
    a, b, c = ev("open", "short", B0), ev("close", "short", B0 + 2 * H4, "intrabar", reason="hard_sl"), ev("open", "long", B0 + 9 * H4)
    primary, alt = match.merge_variants({"utama": [a, b], "pendek": [a, c], "biaya": [a, b]})
    assert [p["causes"] for p in primary] == [[], ["warmup", "intrabar"]]
    assert [x["key"] for x in alt] == [c["key"]]


def test_cocok_harga_beda_and_gagal_manual_position():
    t1 = B0 + H4 + 3
    t2 = B0 + 3 * H4 + 4
    t3 = B0 + 6 * H4 + 2
    variants = {"utama": [ev("open", "long", B0, price=2000.0), ev("close", "long", B0 + 2 * H4, price=2100.0),
                          ev("open", "short", B0 + 5 * H4, price=2050.0)]}
    evidence = [_nginx_ev(t1), _nginx_ev(t2), _nginx_ev(t3, 202)]
    tl = [{"ts": t1 + 2, "action": "open", "side": "long", "status": "success", "fill_price": 2001.0, "fill_qty": 1.0,
           "reason": None},
          {"ts": t2 + 2, "action": "close", "side": "long", "status": "success", "fill_price": 2080.0,
           "fill_qty": 1.0, "reason": None},
          {"ts": t3 + 3, "action": "open", "side": "short", "status": "rejected", "fill_price": None,
           "fill_qty": None, "reason": logs.sanitize("An open position for 'ETH/USDT:USDT' already exists on the "
                                                     "exchange for user 'user-rosyade-02'")}]
    rows = run_match(variants, evidence, tl, now=B0 + 10 * H4)
    assert [r["status"] for r in rows] == ["cocok", "harga_beda", "gagal"]
    assert rows[0]["price_diff_bps"] == pytest.approx(5.0)
    assert rows[1]["price_diff_bps"] == pytest.approx(95.238, rel=1e-3)       # sold lower = cost for a close long
    assert "posisi manual" in rows[2]["reason"] and not rows[2]["perlu_dicek"]
    assert "rosyade" not in json.dumps(rows)


def test_tidak_terkirim_tanpa_log_menunggu_and_tak_terduga():
    now = B0 + 20 * H4 + 600
    variants = {"utama": [ev("open", "long", B0), ev("close", "long", B0 + 3 * H4),
                          ev("open", "short", B0 + 19 * H4)]}
    cov = [[B0 + 2 * H4, now, "nginx"]]                      # the first alert time is not covered by any log
    stray = B0 + 10 * H4 + 7
    rows = run_match(variants, [_nginx_ev(stray, 202)], [], now, coverage=cov)
    st = {(r["action"], r["status"]) for r in rows}
    assert ("open", "tanpa_log") in st and ("close", "tidak_terkirim") in st and ("open", "menunggu") in st
    odd = [r for r in rows if r["status"] == "tak_terduga"]
    assert len(odd) == 1 and odd[0]["perlu_dicek"] and odd[0]["bar_open"] == B0 + 9 * H4
    assert "tidak ada catatan eksekusi" in odd[0]["reason"]


def test_beda_bar_and_exit_later_in_same_trade():
    variants = {"utama": [ev("open", "short", B0), ev("close", "short", B0 + 8 * H4, reason="ema_exit"),
                          ev("open", "long", B0 + 14 * H4)]}
    t_open = B0 + 2 * H4 + 5                                  # one bar late
    t_close = B0 + 5 * H4 + 1800 + 600                        # 3 bars early, mid-bar
    evidence = [_nginx_ev(t_open, 499), _app_ev("done", t_open + 8, status=500, ms=11000.0),
                _app_ev("order", t_open + 7, symbol="ETH/USDT:USDT", trade_dir=-1),
                _nginx_ev(t_close, 499), _app_ev("done", t_close + 6, status=500, ms=9000.0),
                _app_ev("order", t_close + 5, symbol="ETH/USDT:USDT", trade_dir=1)]
    rows = run_match(variants, evidence, [], now=B0 + 13 * H4)
    o, c = rows[0], rows[1]
    assert o["status"] == "cocok" and o["causes"] == ["beda_bar"] and o["perlu_dicek"]
    assert "walau respons HTTP 500" in o["reason"]
    assert c["status"] == "cocok" and c["causes"] == ["beda_waktu_exit"] and c["bar_open"] == B0 + 8 * H4
    assert c["delivery"]["nginx_status"] == 499 and c["delivery"]["app_status"] == 500


def test_other_symbol_manual_client_and_app_only_period():
    now = B0 + 10 * H4
    t = B0 + H4 + 3
    evidence = [
        # app-only era (nginx does not cover it): BTC test -> dropped, ETH request -> kept
        _app_ev("done", t + 1, status=400, ms=20.0), _app_ev("sym", t + 1, symbol="BTC/USDT:USDT"),
        _app_ev("done", t + 900, status=400, ms=20.0),
        _nginx_ev(B0 + 7 * H4 + 5000, 401, tv=False),
    ]
    rows = run_match({"utama": []}, evidence, [], now, coverage=[[B0, now, "app+nginx"]],
                     nginx_cov=[[B0 + 5 * H4, now, "nginx"]])
    assert [r["status"] for r in rows] == ["tak_terduga", "diabaikan"]
    assert "400" in rows[0]["reason"] and rows[0]["delivery"]["sources"] == ["app"]
    assert "uji manual" in rows[1]["reason"]


# ── job / schedule / API ─────────────────────────────────────────────────────

def fake_compute(events, last_bar):
    def fn(params, costs, symbol, tf, since, short_days, **kw):
        assert symbol == "ETHUSDT" and tf == "4h" and params
        return {"variants": {"utama": events, "pendek": events, "biaya": events}, "data_first_bar": B0 - 900 * H4,
                "data_last_bar": last_bar, "engine_commit": "test"}
    return fn


def test_execute_cycle_end_to_end(conn, lc_env):
    from src.lab import presets
    presets.seed(conn)
    t1 = B0 + H4 + 4
    (lc_env["nginx"] / "access.log").write_text(_nginx(B0 - 86400, 200).replace("/webhook/tradingview", "/")
                                                + "\n" + _nginx(t1, 202) + "\n")
    (lc_env["app"] / "bmtm-api-out.log").write_text(_done(t1, 202, 30.0) + "\n")
    _trading_db(lc_env["root"] / "bmtm_trading.db",
                [{"ts": t1 + 2, "action": "open", "side": "short", "status": "rejected",
                  "err": "An open position for 'ETH/USDT:USDT' already exists on the exchange for user 'user-rosyade-02'"},
                 {"ts": t1 + 2, "action": "open", "side": "short", "status": "success", "symbol": "BTC/USDT:USDT",
                  "fill": 1.0}])
    now = B0 + 4 * H4
    out = jobs.execute_cycle(conn, None, now=now, compute_fn=fake_compute([ev("open", "short", B0)], now - H4))
    assert out["counts"] == {"gagal": 1} and out["params_source"].startswith("preset")
    assert conn.execute("SELECT COUNT(*) FROM livecheck_evidence").fetchone()[0] == 2
    body = report.build(conn, bars=60, now=now)
    assert body["summary"]["counts"]["gagal"] == 1 and body["summary"]["expected"] == 1
    r = body["rows"][0]
    assert r["delivery"]["nginx_status"] == 202 and r["delivery"]["app_status"] == 202
    dumped = json.dumps(body)
    assert "rosyade" not in dumped and "super-secret" not in dumped and "52.89.214.238" not in dumped
    # evidence survives log rotation: logs gone, the row stays
    (lc_env["nginx"] / "access.log").unlink()
    (lc_env["app"] / "bmtm-api-out.log").unlink()
    out2 = jobs.execute_cycle(conn, None, now=now + 60, compute_fn=fake_compute([ev("open", "short", B0)], now - H4))
    assert out2["counts"] == {"gagal": 1}


def test_execute_cycle_engine_failure_keeps_evidence(conn, lc_env):
    (lc_env["nginx"] / "access.log").write_text(_nginx(B0 + H4 + 4, 202) + "\n")

    def boom(*a, **k):
        raise RuntimeError("no data")
    with pytest.raises(RuntimeError):
        jobs.execute_cycle(conn, None, now=B0 + 3 * H4, compute_fn=boom)
    assert conn.execute("SELECT COUNT(*) FROM livecheck_evidence").fetchone()[0] == 1
    assert "no data" in kv_get(conn, "livecheck_last_cycle")["error"]


def test_schedule_tick(conn, lc_env, monkeypatch):
    from src.lab.settings import get_lab_settings
    s = get_lab_settings()
    now = B0 + H4 + 300
    ids = schedule.tick(conn, s, now)
    assert len(ids) == 1 and q.get_job(conn, ids[0])["kind"] == "livecheck_cycle"
    assert schedule.tick(conn, s, now + 60) == []                 # one queued already
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert schedule.tick(conn, s, now + 60) == []                 # same bar, same hour
    assert len(schedule.tick(conn, s, now + 3600)) == 1           # hourly catch-up
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert len(schedule.tick(conn, s, B0 + 2 * H4 + 200)) == 1    # next 4H close (after delay)
    monkeypatch.setenv("LAB_LIVECHECK_ENABLED", "0")
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert schedule.tick(conn, s, B0 + 9 * H4) == []


def test_worker_and_runner_know_the_job(lab_env):
    from src.lab.worker import FAST_KINDS, Worker
    assert "livecheck_cycle" in FAST_KINDS
    w = Worker()
    assert w._cmd(1, "livecheck_cycle")[0] == w.settings.engine_python      # needs pandas + engine
    root = pathlib.Path(__file__).resolve().parents[2]
    assert "livecheck_cycle" in (root / "src/lab/runner.py").read_text()
    assert "livecheck" in (root / "src/lab/scheduler.py").read_text()


def test_livecheck_never_imports_trading_or_sends_anything():
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "lab" / "livecheck"
    files = list(root.glob("*.py")) + [root.parents[1] / "api" / "livecheck_routes.py"]
    for f in files:
        text = f.read_text()
        imports = [ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any("trading" in ln for ln in imports), f
        for bad in ("/fapi/v1/order", "X-MBX-APIKEY", "telegram", "urlopen", "requests.", "httpx", "ccxt"):
            assert bad.lower() not in text.lower(), (f, bad)


def test_trade_logs_reader_is_read_only_and_selects_no_user(tmp_path):
    from src.lab.livecheck.trades import read_bot_positions, read_trade_logs
    p = tmp_path / "t.db"
    _trading_db(p, [{"ts": B0, "action": "open", "side": "long", "status": "success", "fill": 2000.0, "qty": 1.0}])
    rows = read_trade_logs(str(p), "ETHUSDT")
    assert rows == [{"ts": B0, "action": "open", "side": "long", "status": "success", "fill_price": 2000.0,
                     "fill_qty": 1.0, "reason": None}]
    assert read_bot_positions(str(p), "ETHUSDT") == []
    assert read_trade_logs(str(tmp_path / "missing.db"), "ETHUSDT") == []


@pytest.fixture
def api(lab_env):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers

    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    return make


def test_api_admin_only_and_shape(api, conn, lc_env):
    assert api("u-plain").get("/api/v1/lab/live-check").status_code == 403
    ensure_schema(conn)
    r = api("u-admin").get("/api/v1/lab/live-check?bars=42")
    assert r.status_code == 200
    body = r.json()
    assert body["preset"] == "4H-ETH-Basic" and body["window"]["bars"] == 42 and body["rows"] == []
    assert set(body["summary"]["counts"]) >= {"cocok", "gagal", "tidak_terkirim", "tak_terduga", "harga_beda"}
    assert "warmup" in body["causes"]
    assert api("u-admin").get("/api/v1/lab/live-check?bars=1").status_code == 422
