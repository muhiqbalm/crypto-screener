"""Shadow execution: trade_logs reader, signal grouping, fill maths, job, schedule, API.

No network: the market is a fake. bmtm_trading.db is a throw-away file in tmp_path.
"""
import io
import pathlib
import sqlite3
import zipfile

import pytest

from src.lab import queue as q
from src.lab.ledger.store import iso, kv_get, to_epoch
from src.lab.shadow import jobs, report, schedule, simulate, source
from src.lab.shadow.market import PublicMarket, Unavailable
from src.lab.shadow.store import ensure_schema, shadow_settings

BAR = int(to_epoch("2026-11-09T00:00:00Z"))          # 4H close that fired the alert
ARR = BAR + 5                                        # alert arrival
H4 = 14_400


def _trading_db(path, rows, extra_cols=()):
    c = sqlite3.connect(path)
    cols = ["id TEXT", "user_id TEXT", "symbol TEXT", "action TEXT", "side TEXT", "exchange TEXT",
            "size_value REAL", "status TEXT", "order_id TEXT", "fill_price REAL", "filled_quantity REAL",
            "created_at TEXT", "error_details TEXT", *extra_cols]
    c.execute(f"CREATE TABLE trade_logs ({', '.join(cols)})")
    c.execute("CREATE TABLE webhook_configs (id TEXT, user_id TEXT, passphrase TEXT)")
    c.execute("INSERT INTO webhook_configs VALUES ('w', 'u1', 'super-secret')")
    for r in rows:
        keys = list(r)
        c.execute(f"INSERT INTO trade_logs ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                  [r[k] for k in keys])
    c.commit()
    c.close()


def row(i, action="open", side="long", status="success", fill=None, qty=None, at=ARR + 2, user="u1", **kw):
    return {"id": f"r{i}", "user_id": user, "symbol": "ETH/USDT:USDT", "action": action, "side": side,
            "exchange": "binance", "size_value": 50.0, "status": status, "fill_price": fill,
            "filled_quantity": qty, "created_at": iso(at).replace("Z", "+00:00"), "error_details": "x", **kw}


class FakeMarket:
    """4H bars with a constant 20-point range (ATR = 20) closing at 2000 at BAR; a 1m path
    after BAR given by ``path(minute) -> (o, h, l, c)``; aggTrades derived from it."""

    def __init__(self, path, agg=True, now_ms=None):
        self.path, self.agg, self.calls = path, agg, {"klines": 0}

    def klines(self, symbol, tf, a, b):
        self.calls["klines"] += 1
        if tf == "4h":
            out, t = [], BAR - 60 * H4
            while t + H4 <= BAR:
                if a <= t * 1000 < b:
                    out.append({"ts": t * 1000, "o": 2000.0, "h": 2010.0, "l": 1990.0, "c": 2000.0})
                t += H4
            return out
        out = []
        t = a // 60_000 * 60_000
        while t < b:
            m = (t // 1000 - BAR) // 60
            if m >= 0:
                o, h, lo, c = self.path(m)
                out.append({"ts": t, "o": o, "h": h, "l": lo, "c": c})
            t += 60_000
        return out

    def agg_trades(self, symbol, windows):
        if not self.agg:
            raise Unavailable("no trades")
        out = {}
        for w in windows:
            trades = []
            t = w[0] // 60_000 * 60_000
            while t < w[1]:
                m = (t // 1000 - BAR) // 60
                o, h, lo, c = self.path(m)
                # o at +0s, h at +20s, l at +40s, c at +59s
                for dt, px in ((0, o), (20_000, h), (40_000, lo), (59_000, c)):
                    if w[0] <= t + dt < w[1]:
                        trades.append((t + dt, px))
                t += 60_000
            out[w] = trades
        return out


def dip_path(m):
    """Flat 2000 except minute 3 dips to 1995 (k=0.25 * ATR 20 = 5 points)."""
    if m == 3:
        return 2000.0, 2000.5, 1994.0, 1999.0
    return 2000.0, 2000.5, 1999.5, 2000.0


# ── source ───────────────────────────────────────────────────────────────

def test_trade_dir():
    assert source.trade_dir("open", "long") == 1 and source.trade_dir("open", "short") == -1
    assert source.trade_dir("close", "long") == -1 and source.trade_dir("close", "short") == 1
    assert source.trade_dir("noop", "long") == 0


def test_read_trade_logs_selects_only_needed_columns_read_only(tmp_path):
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p, [row(1, fill=2001.0, qty=0.1)], extra_cols=("passphrase TEXT",))
    before = p.read_bytes()
    rows = source.read_trade_logs(str(p))
    assert len(rows) == 1
    assert "passphrase" not in rows[0] and "error_details" not in rows[0] and "id" not in rows[0]
    assert rows[0]["fill_px"] == 2001.0 and rows[0]["_arrival_col"] is None
    assert p.read_bytes() == before
    assert source.read_trade_logs(str(tmp_path / "missing.db")) == []


def test_group_signals_fanout_close_offclose_and_new_columns(tmp_path):
    rows = [row(1, fill=2001.0, qty=1.0, user="u1"), row(2, fill=2003.0, qty=3.0, user="u2", at=ARR + 4),
            row(3, action="close", side="short", status="rejected", at=ARR + 3),
            row(4, side="short", status="rejected", at=BAR + 2 * 3600)]           # 2h after a close
    p = tmp_path / "t.db"
    _trading_db(p, rows)
    sigs = source.group_signals(source.read_trade_logs(str(p)))
    assert len(sigs) == 3
    o = next(s for s in sigs if s["action"] == "open" and s["side"] == "long")
    assert o["n_rows"] == 2 and o["n_users"] == 2 and o["fill_price"] == pytest.approx(2002.5)
    assert o["bar_close_s"] == BAR and o["arrival_basis"] == "created_at" and o["off_close"] == 0
    c = next(s for s in sigs if s["action"] == "close")
    assert c["trade_dir"] == 1 and c["fill_price"] is None and c["statuses"] == ["rejected"]
    late = next(s for s in sigs if s["side"] == "short" and s["action"] == "open")
    assert late["off_close"] == 1
    # fast-ack style schema: explicit receipt + fill time columns, non-final status first
    p2 = tmp_path / "t2.db"
    _trading_db(p2, [row(1, status="queued", received_at=iso(ARR), filled_at=None)],
                extra_cols=("received_at TEXT", "filled_at TEXT"))
    s2 = source.group_signals(source.read_trade_logs(str(p2)))[0]
    assert s2["arrival_s"] == ARR and s2["arrival_basis"] == "received_at" and s2["final"] is False


# ── maths ────────────────────────────────────────────────────────────────

def test_atr_constant_range():
    bars = [{"h": 10.0, "l": 0.0, "c": 5.0}] * 20
    assert simulate.atr(bars) == pytest.approx(10.0)
    assert simulate.atr(bars[:5]) is None


def _sig(**kw):
    return {"symbol": "ETHUSDT", "trade_dir": 1, "tf": "4h", "bar_close_s": BAR, "arrival_s": ARR,
            "fill_price": 2001.0, "fill_s": None, **kw}


def test_evaluate_fill_miss_postonly():
    m = FakeMarket(dip_path)
    now = (ARR + 300 * 60) * 1000
    res = simulate.evaluate(_sig(), m, (-0.1, 0.0, 0.25, 0.5), (5, 240), 3.0, now)
    assert res["status"] == "done" and res["complete"]
    a = res["actual"]
    assert a["bar_close_px"] == 2000.0 and a["atr"] == pytest.approx(20.0) and a["latency_s"] == 5
    assert a["p0"] == 2000.5 and a["p0_basis"] == "aggtrades"           # first trade after arrival (minute 0 high)
    assert a["slippage_bps"] == pytest.approx(5.0) and a["drift_bps"] == pytest.approx(2.5)
    assert a["impact_bps"] == pytest.approx(0.5 / 2000.5 * 1e4)
    r = {(x["k"], x["ttl_min"]): x for x in res["results"]}
    assert r[(-0.1, 5)]["outcome"] == "postonly" and r[(-0.1, 5)]["saving_bps"] == 0
    # k=0: limit 2000 -> first trade < 2000 is minute 0 low at +40s
    f = r[(0.0, 5)]
    assert f["outcome"] == "filled" and f["fill_ts"] == iso(BAR + 40) and f["time_to_fill_s"] == 35
    assert f["saving_bps"] == pytest.approx(1.0 / 2001.0 * 1e4 + 3.0) and f["ref_basis"] == "fill"
    # k=0.25: limit 1995, minute 3 low 1994 at +40s
    g = r[(0.25, 240)]
    assert g["outcome"] == "filled" and g["fill_ts"] == iso(BAR + 180 + 40) and g["data_basis"] == "aggtrades"
    assert g["limit_px"] == pytest.approx(1995.0)
    # k=0.5: limit 1990 never traded through -> chase at expiry 2000
    h = r[(0.5, 240)]
    assert h["outcome"] == "missed" and h["saving_bps"] == pytest.approx(-(2000 - 2001) / 2001 * 1e4)
    assert h["runaway_max_bps"] == pytest.approx((2000.5 - 2001) / 2001 * 1e4)


def test_evaluate_trade_at_limit_is_not_a_fill_and_partial_windows():
    def path(m):                       # low exactly AT 1995 (k=0.25): touch, not a trade-through
        return (2000.0, 2001.0, 1995.0, 2000.0) if m == 3 else (2000.0, 2001.0, 1999.0, 2000.0)
    m = FakeMarket(path)
    now = (ARR + 30 * 60) * 1000
    res = simulate.evaluate(_sig(fill_price=None), m, (0.25,), (5, 15, 60), 3.0, now)
    assert res["status"] == "partial" and not res["complete"]
    assert {x["ttl_min"] for x in res["results"]} == {5, 15}
    assert all(x["outcome"] == "missed" and x["ref_basis"] == "proxy" for x in res["results"])
    assert res["actual"]["slippage_bps"] is None and res["actual"]["drift_bps"] == pytest.approx(5.0)


def test_evaluate_sell_side_and_kline_fallback():
    def path(m):                       # price rises: a sell limit above the close fills
        return (2000.0 + m, 2001.0 + m, 1999.0 + m, 2000.5 + m)
    m = FakeMarket(path, agg=False)
    sig = _sig(trade_dir=-1, fill_price=1999.0)
    res = simulate.evaluate(sig, m, (0.25,), (15,), 3.0, (ARR + 3600) * 1000)
    x = res["results"][0]
    # limit 2005: first minute with high > 2005 is m=5 (2006); no trades -> minute open, klines basis
    assert x["outcome"] == "filled" and x["fill_ts"] == iso(BAR + 300) and x["data_basis"] == "klines_1m"
    assert x["saving_bps"] == pytest.approx((2005 - 1999) / 1999 * 1e4 + 3.0)
    assert res["actual"]["p0_basis"] == "klines_1m"
    assert res["actual"]["slippage_bps"] == pytest.approx(-(1999 - 2000) / 2000 * 1e4)


def test_vision_zip_parsing(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        lines = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
        for i, (ts, px) in enumerate([(1000, 1.0), (2000, 2.0), (3000, 3.0), (5000, 5.0)]):
            lines.append(f"{i},{px},1,{i},{i},{BAR * 1000 + ts},false")
        z.writestr("ETHUSDT-aggTrades-2026-11-09.csv", "\n".join(lines))
    mk = PublicMarket(cache_dir=str(tmp_path), now_ms=(BAR + 10 * 86400) * 1000)
    monkeypatch.setattr(mk, "_day_file", lambda s, d: buf.getvalue())
    w1, w2 = (BAR * 1000 + 1500, BAR * 1000 + 3001), (BAR * 1000, BAR * 1000 + 1001)
    out = mk.agg_trades("ETHUSDT", [w1, w2])
    assert out[w1] == [(BAR * 1000 + 2000, 2.0), (BAR * 1000 + 3000, 3.0)]
    assert out[w2] == [(BAR * 1000 + 1000, 1.0)]


# ── job / schedule / report ──────────────────────────────────────────────

def test_execute_cycle_backfill_then_progress(conn, tmp_path):
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p, [row(1, fill=2001.0, qty=1.0), row(2, status="rejected", user="u2")])
    m = FakeMarket(dip_path)
    out = jobs.execute_cycle(conn, None, market=m, now=ARR + 60, trading_db_path=str(p))
    assert out["sync"] == {"new": 1, "changed": 0} and out["evaluated"] == {}      # not due yet (3 min)
    out = jobs.execute_cycle(conn, None, market=m, now=ARR + 20 * 60, trading_db_path=str(p))
    assert out["evaluated"] == {"partial": 1} and out["sync"]["new"] == 0
    s = conn.execute("SELECT * FROM shadow_signals").fetchone()
    assert s["slippage_bps"] == pytest.approx(5.0) and s["next_due"] > iso(ARR + 20 * 60)
    out = jobs.execute_cycle(conn, None, market=m, now=ARR + 300 * 60, trading_db_path=str(p))
    assert out["evaluated"] == {"done": 1}
    cfg = shadow_settings()
    n = conn.execute("SELECT COUNT(*) FROM shadow_results").fetchone()[0]
    assert n == len(cfg.ks) * len(cfg.ttls_min)
    again = jobs.execute_cycle(conn, None, market=m, now=ARR + 400 * 60, trading_db_path=str(p))
    assert again["evaluated"] == {} and kv_get(conn, "shadow_last_cycle")["evaluated"] == {}
    rep = report.build(conn)
    assert rep["actual"]["n_signals"] == 1 and rep["actual"]["n_with_fill"] == 1
    assert rep["actual"]["sample"] == "too_few" and rep["actual"]["latency_upper_bound"] is True
    cell = next(c for c in rep["grid"] if c["k"] == 0.25 and c["ttl_min"] == 240)
    assert cell["n"] == 1 and cell["filled"] == 1 and cell["fill_rate"] == 1.0
    assert "user_id" not in str(rep) and "u1" not in str(rep["signals"])


def test_changed_trade_logs_requeue(conn, tmp_path):
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p, [row(1, status="queued")])
    m = FakeMarket(dip_path)
    jobs.execute_cycle(conn, None, market=m, now=ARR + 300 * 60, trading_db_path=str(p))
    s = conn.execute("SELECT status, fill_price FROM shadow_signals").fetchone()
    assert s["status"] == "partial" and s["fill_price"] is None          # waits for a final status
    c = sqlite3.connect(p)
    c.execute("UPDATE trade_logs SET status='success', fill_price=2002.0, filled_quantity=1")
    c.commit()
    c.close()
    out = jobs.execute_cycle(conn, None, market=m, now=ARR + 301 * 60, trading_db_path=str(p))
    assert out["sync"]["changed"] == 1 and out["evaluated"] == {"done": 1}
    assert conn.execute("SELECT fill_price FROM shadow_signals").fetchone()[0] == 2002.0


def test_schedule_tick(conn, tmp_path, monkeypatch):
    from src.lab.settings import get_lab_settings
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p, [row(1)])
    monkeypatch.setenv("LAB_TRADING_DB_PATH", str(p))
    get_lab_settings.cache_clear()
    s = get_lab_settings()
    now = ARR + 100
    assert len(schedule.tick(conn, s, now)) == 1                    # trade_logs changed (first run = backfill)
    assert schedule.tick(conn, s, now + 60) == []                   # busy
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert schedule.tick(conn, s, now + 60) == []                   # nothing new, same hour
    assert len(schedule.tick(conn, s, now + 3600)) == 1             # hourly catch-up
    conn.execute("UPDATE lab_jobs SET status='done'")
    ensure_schema(conn)
    conn.execute("INSERT INTO shadow_signals (key, symbol, action, side, trade_dir, tf, bar_close_ts, arrival_ts, "
                 "status, next_due, created_at) VALUES ('k', 'ETHUSDT', 'open', 'long', 1, '4h', ?, ?, 'pending', ?, ?)",
                 (iso(BAR), iso(ARR), iso(now + 3700), iso(now)))
    conn.commit()
    jid = schedule.tick(conn, s, now + 3720)
    assert len(jid) == 1 and conn.execute("SELECT payload_json FROM lab_jobs WHERE id=?", (jid[0],)).fetchone()[0] \
        == '{"reason": "due"}'
    monkeypatch.setenv("LAB_SHADOW_ENABLED", "0")
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert schedule.tick(conn, s, now + 9000) == []


def test_worker_and_runner_know_the_job(lab_env):
    from src.lab.worker import FAST_KINDS, Worker
    assert "shadow_cycle" in FAST_KINDS
    w = Worker()
    assert w._cmd(1, "shadow_cycle")[0] == w.settings.engine_python
    assert "shadow_cycle" in (pathlib.Path(__file__).resolve().parents[2] / "src/lab/runner.py").read_text()


def test_runner_executes_shadow_job(conn, tmp_path, monkeypatch):
    from src.lab import runner
    from src.lab.settings import get_lab_settings
    monkeypatch.setenv("LAB_TRADING_DB_PATH", str(tmp_path / "none.db"))
    get_lab_settings.cache_clear()
    jid = q.enqueue(conn, "shadow_cycle", None, {})
    conn.commit()
    assert runner.main([str(jid)]) == 0
    assert conn.execute("SELECT status FROM lab_jobs WHERE id=?", (jid,)).fetchone()[0] == "done"


def test_shadow_never_imports_trading_or_places_orders():
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "lab" / "shadow"
    for f in root.glob("*.py"):
        text = f.read_text()
        imports = [ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any("trading" in ln for ln in imports), f
        assert "/fapi/v1/order" not in text and "X-MBX-APIKEY" not in text and "telegram" not in text.lower(), f


# ── API ──────────────────────────────────────────────────────────────────

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


def test_api_admin_only_and_shape(api, conn, tmp_path):
    assert api("u-plain").get("/api/v1/lab/shadow").status_code == 403
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p, [row(1, fill=2001.0, qty=1.0)])
    jobs.execute_cycle(conn, None, market=FakeMarket(dip_path), now=ARR + 300 * 60, trading_db_path=str(p))
    r = api("u-admin").get("/api/v1/lab/shadow")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["fee_diff_bps"] == 3.0 and len(body["signals"]) == 1
    assert body["signals"][0]["results"] and body["actual"]["n_with_fill"] == 1
    assert {c["ttl_min"] for c in body["grid"]} == set(shadow_settings().ttls_min)
