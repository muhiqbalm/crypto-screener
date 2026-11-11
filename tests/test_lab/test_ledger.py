"""Signal Ledger: scoring maths, onset/dedupe rules, collectors, scheduling, API.

No network: every exchange call is a fake. bmtm_trading.db is a throw-away file in tmp_path.
"""
import math
import os
import sqlite3
import sys

import pytest

from src.lab import queue as q
from src.lab.ledger import HORIZONS, collect, schedule, scoring, screener, stats
from src.lab.ledger.store import ensure_schema, insert_signal, iso, kv_get, norm_symbol, to_epoch

T0 = int(to_epoch("2026-10-01T00:00:00Z"))


def bars(start_s, n, price, step=900, wick=0.0):
    """n closed bars from start_s; price(i) = open of bar i, close = price(i+1)."""
    out = []
    for i in range(n):
        o, c = price(i), price(i + 1)
        out.append({"ts": (start_s + i * step) * 1000, "o": o, "h": max(o, c) + wick, "l": min(o, c) - wick,
                    "c": c, "v": 10.0})
    return out


# ── scoring ──────────────────────────────────────────────────────────────

def test_outcome_long_short_and_btc_relative():
    coin = scoring.Path(bars(T0, 7 * 96 + 10, lambda i: 100.0 + i * 0.1, wick=0.05))
    btc = scoring.Path(bars(T0, 7 * 96 + 10, lambda i: 1000.0))       # flat BTC
    now = T0 + 30 * 86400
    sig = {"ts": iso(T0 + 30), "direction": 1, "symbol": "ETHUSDT"}  # 30 s after the bar open -> that bar
    res = scoring.score_signal(sig, coin, btc, now, set())
    assert res["entry"] == (iso(T0), 100.0)
    assert res["complete"] and set(res["outcomes"]) == set(HORIZONS)
    o = res["outcomes"]["4h"]                                         # 16 bars: close of bar 15 = price(16)
    assert o["ret_pct"] == pytest.approx((101.6 / 100 - 1) * 100)
    assert o["dir_ret_pct"] == pytest.approx(o["ret_pct"]) and o["hit"] == 1
    assert o["btc_ret_pct"] == pytest.approx(0.0) and o["rel_btc_pct"] == pytest.approx(o["ret_pct"])
    assert o["mfe_pct"] == pytest.approx((101.65 / 100 - 1) * 100)
    assert o["mae_pct"] == pytest.approx(-0.05)
    assert o["exit_ts"] == iso(T0 + 4 * 3600)
    short = scoring.score_signal({**sig, "direction": -1}, coin, btc, now, set())["outcomes"]["4h"]
    assert short["dir_ret_pct"] == pytest.approx(-o["ret_pct"]) and short["hit"] == 0
    assert short["mfe_pct"] == pytest.approx(0.05) and short["mae_pct"] == pytest.approx(-(101.65 / 100 - 1) * 100)
    assert short["rel_btc_pct"] == pytest.approx(-o["ret_pct"])


def test_entry_waits_for_next_bar_when_signal_is_late():
    coin = scoring.Path(bars(T0, 200, lambda i: 100.0 + i))
    res = scoring.score_signal({"ts": iso(T0 + 120), "direction": 1, "symbol": "X"}, coin, None, T0 + 10 ** 6, set())
    assert res["entry"] == (iso(T0 + 900), 101.0)                  # 120 s > 90 s tolerance -> next bar
    assert res["outcomes"]["4h"]["btc_ret_pct"] is None


def test_horizons_fill_in_as_time_passes_and_give_up_on_missing_data():
    coin = scoring.Path(bars(T0, 30, lambda i: 100.0))             # only 7.5 h of data
    sig = {"ts": iso(T0), "direction": 1, "symbol": "X"}
    r = scoring.score_signal(sig, coin, None, T0 + 5 * 3600, set())
    assert set(r["outcomes"]) == {"4h"} and not r["complete"]
    later = scoring.score_signal(sig, coin, None, T0 + 30 * 86400, {"4h"})
    assert later["complete"] and later["outcomes"]["7d"]["ret_pct"] is None   # gap -> resolved as no data


def test_score_pending_end_to_end(conn):
    ensure_schema(conn)
    insert_signal(conn, source="webhook", signal_type="tv_open", symbol="ETH/USDT:USDT", direction=-1,
                  ts=iso(T0), dedupe_key="a")
    insert_signal(conn, source="webhook", signal_type="tv_open", symbol="BTCUSDT", direction=1, ts=iso(T0),
                  dedupe_key="b")
    conn.commit()
    calls = []

    def fetch(sym, a, b):
        calls.append(sym)
        return bars(T0 - 3600, 8 * 96, (lambda i: 50.0 - i * 0.01) if sym == "ETHUSDT" else (lambda i: 1000.0))

    res = scoring.score_pending(conn, fetch, now_s=T0 + 20 * 86400)
    assert res["completed"] == 2 and res["scored"] == 8
    assert sorted(calls) == ["BTCUSDT", "ETHUSDT"]                  # BTC fetched once, reused
    eth = conn.execute("SELECT * FROM ledger_signals WHERE symbol='ETHUSDT'").fetchone()
    assert eth["status"] == "done" and eth["entry_ts"] == iso(T0)
    o = conn.execute("SELECT * FROM ledger_outcomes WHERE signal_id=? AND horizon='1d'", (eth["id"],)).fetchone()
    assert o["hit"] == 1 and o["dir_ret_pct"] > 0                  # short on a falling coin
    assert scoring.score_pending(conn, fetch, now_s=T0 + 20 * 86400)["pending"] == 0


def test_unknown_symbol_is_marked_no_data(conn):
    ensure_schema(conn)
    insert_signal(conn, source="webhook", signal_type="tv_open", symbol="NOPEUSDT", direction=1, ts=iso(T0),
                  dedupe_key="x")

    def fetch(sym, a, b):
        if sym == "NOPEUSDT":
            from src.lab.ledger.binance import UnknownSymbol
            raise UnknownSymbol("Invalid symbol")
        return []

    scoring.score_pending(conn, fetch, now_s=T0 + 86400)
    assert conn.execute("SELECT status FROM ledger_signals").fetchone()[0] == "no_data"


# ── stats ────────────────────────────────────────────────────────────────

def test_wilson_and_sample_flags():
    lo, hi = stats.wilson(7, 10)
    assert lo == pytest.approx(0.3968, abs=1e-3) and hi == pytest.approx(0.8922, abs=1e-3)
    assert stats.wilson(0, 0) == (None, None)
    assert [stats.sample_flag(n) for n in (0, 5, 20, 30)] == ["none", "too_few", "small", "ok"]


def test_horizon_stats_verdicts():
    rows = [{"dir_ret_pct": 1.0 + (i % 3) * 0.1, "hit": 1, "rel_btc_pct": 0.5, "mfe_pct": 2, "mae_pct": -1,
             "ts": f"2026-10-{1 + i % 5:02d}T00:00:00Z", "symbol": "A"} for i in range(12)]
    s = stats.horizon_stats(rows + [{"dir_ret_pct": None}])
    assert s["n"] == 12 and s["hit_rate"] == 1.0 and s["verdict"] == "positive" and s["sample"] == "small"
    assert s["days"] == 5 and s["coins"] == 1 and s["mean_ci"][0] > 0
    few = stats.horizon_stats(rows[:3])
    assert few["verdict"] == "insufficient" and few["sample"] == "too_few"
    mixed = stats.horizon_stats([{"dir_ret_pct": (-1) ** i * 1.0, "hit": int(i % 2 == 0), "rel_btc_pct": 0.1 * i,
                                  "ts": f"2026-10-{1 + i // 4:02d}T00:00:00Z"} for i in range(40)])
    assert mixed["verdict"] == "inconclusive" and mixed["hit_rate"] == 0.5 and mixed["days"] == 10
    assert mixed["verdict_rel_btc"] == "positive"
    one_day = stats.horizon_stats([{"dir_ret_pct": 1.0 + i, "hit": 1, "ts": "2026-10-01T00:00:00Z"} for i in range(30)])
    assert one_day["verdict"] == "insufficient" and one_day["mean_ci"] is None   # one market day = one cluster


def test_clustered_ci_is_wider_than_naive_for_correlated_days():
    xs = [1.0] * 10 + [-1.0] * 10 + [1.2] * 10
    days = ["a"] * 10 + ["b"] * 10 + ["c"] * 10
    lo, hi = stats.clustered_ci(xs, days)
    lo2, hi2 = stats.clustered_ci(xs, [str(i) for i in range(30)])
    assert hi - lo > 2 * (hi2 - lo2)


# ── screener onsets ──────────────────────────────────────────────────────

def st(signal="NEUTRAL", tier="B", conf="LOW", mom="HOLD", fund="NEUTRAL", oi="NEUTRAL", price=10.0):
    return {"signal": signal, "tier": tier, "confidence_tier": conf, "momentum_signal": mom,
            "funding_rate_signal": fund, "oi_signal": oi, "price": price}


def _events(conn, source="screener"):
    return [(r["signal_type"], r["symbol"], r["direction"], r["ts"]) for r in conn.execute(
        "SELECT * FROM ledger_signals WHERE source=? ORDER BY id", (source,))]


def test_snapshot_onsets_baseline_cooldown_and_gap(conn):
    h = lambda k: iso(T0 + k * 3600)  # noqa: E731
    r = screener.record_snapshot(conn, kind="live", bar=h(0), ts=h(0), states={"AUSDT": st("BULLISH", tier="A")})
    assert r["baseline"] and _events(conn) == []                    # unknown onset time -> no event
    screener.record_snapshot(conn, kind="live", bar=h(1), ts=h(1), states={"AUSDT": st("BULLISH", tier="A")})
    assert _events(conn) == []                                       # still active, no new event
    screener.record_snapshot(conn, kind="live", bar=h(2), ts=h(2), states={"AUSDT": st("BEARISH", tier="C", conf="HIGH")})
    assert sorted(_events(conn)) == sorted([("komposit", "AUSDT", -1, h(2)), ("komposit_high", "AUSDT", -1, h(2)),
                                            ("tier_c", "AUSDT", -1, h(2))])
    screener.record_snapshot(conn, kind="live", bar=h(3), ts=h(3), states={"AUSDT": st()})
    screener.record_snapshot(conn, kind="live", bar=h(4), ts=h(4), states={"AUSDT": st("BEARISH")})
    assert len(_events(conn)) == 3                                   # re-onset inside 24 h cooldown: suppressed
    screener.record_snapshot(conn, kind="live", bar=h(5), ts=h(5), states={"AUSDT": st("BULLISH"), "BUSDT": st("BULLISH")})
    ev = _events(conn)
    assert ev[-1] == ("komposit", "AUSDT", 1, h(5)) and len(ev) == 4  # flip allowed; new coin BUSDT = baseline
    r = screener.record_snapshot(conn, kind="live", bar=h(10), ts=h(10), states={"AUSDT": st(mom="BUY")})
    assert r["baseline"] and len(_events(conn)) == 4                 # > 3 h gap -> baseline again
    screener.record_snapshot(conn, kind="live", bar=h(31), ts=h(31), states={"AUSDT": st(mom="BUY")})
    screener.record_snapshot(conn, kind="live", bar=h(32), ts=h(32), states={"AUSDT": st("BEARISH")})
    assert _events(conn)[-1] == ("komposit", "AUSDT", -1, h(32))     # cooldown over -> recorded
    n = conn.execute("SELECT COUNT(*) FROM ledger_screener_snapshots WHERE kind='live'").fetchone()[0]
    assert n == 10


def test_live_snapshot_uses_screener_labels(conn, sample_df):
    from src.services.models import ProcessedResult

    class Proc:
        async def process_all(self):
            return ProcessedResult(data=sample_df, errors=[])

    first = screener.live_snapshot(conn, iso(T0), ts=iso(T0), processor=Proc())
    assert first["baseline"] and first["coins"] == len(sample_df)
    snap = conn.execute("SELECT data_json FROM ledger_screener_snapshots LIMIT 1").fetchone()[0]
    assert '"signal"' in snap and '"tier"' in snap
    assert kv_get(conn, "ledger_live_since") == iso(T0)


def test_reconstruction_is_causal_and_runs_the_pipeline(conn):
    start = T0 + 60 * 86400
    hist = {}
    for k, sym in enumerate(["AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT"]):
        drift = (k - 2.5) * 0.002
        hist[sym] = {
            "1h": bars(start - 30 * 3600, 30 + 72, lambda i, d=drift: 100 * math.exp(d * i), step=3600),
            "1d": bars(start - 80 * 86400, 80, lambda i, d=drift: 100 * math.exp(d * 24 * (i - 80)), step=86400),
            "funding": [{"ts": (start - 8 * 3600 * j) * 1000, "rate": 0.0001 * (k - 3)} for j in range(10)][::-1],
            "ls": [{"ts": (start + 3600 * j) * 1000, "v": 1.0 + 0.1 * k} for j in range(-3, 73)],
            "oi": [{"ts": (start + 3600 * j) * 1000, "v": 1000 + j * (k - 2)} for j in range(-30, 73)],
        }
    rec = screener.build_record("AUSDT", start + 3600, hist["AUSDT"])
    # price = close of the 1h bar that ended at T, never a later one
    assert rec["price"] == pytest.approx(hist["AUSDT"]["1h"][30]["c"])
    assert not math.isnan(rec["momentum_30d"]) and not math.isnan(rec["atr_percent"])
    assert not math.isnan(rec["oi_delta_percent"]) and rec["long_short_ratio"] == pytest.approx(1.0)
    assert screener.build_record("AUSDT", start + 200 * 3600, hist["AUSDT"]) is None   # no data -> no record
    res = screener.reconstruct(conn, list(hist), start + 3600, start + 48 * 3600, hist)
    assert res["hours"] == 48
    assert conn.execute("SELECT COUNT(DISTINCT bar) FROM ledger_screener_snapshots WHERE kind='rekon'").fetchone()[0] == 48
    assert conn.execute("SELECT COUNT(*) FROM ledger_signals WHERE source='screener'").fetchone()[0] == 0


# ── collectors ───────────────────────────────────────────────────────────

def test_collect_lab_watch_skips_pre_creation_trades(conn):
    from src.lab.db import dumps
    conn.execute("INSERT INTO watches (id, template_id, symbol, timeframe, params_json, costs_json, created_at) "
                 "VALUES (1, 'rosyade_family', 'ETHUSDT', '4h', '{}', '{}', '2026-11-09T17:34:26Z')")
    trades = [{"entry_time": "2026-11-01T00:00:00Z", "side": "long", "entry_price": 1},
              {"entry_time": "2026-11-10T04:00:00Z", "side": "short", "entry_price": 2, "exit_time": None}]
    conn.execute("INSERT INTO watch_state (watch_id, computed_at, recent_trades_json, position_json) VALUES (1, 'x', ?, ?)",
                 (dumps(trades), dumps({"side": "long", "entry_price": 3, "entry_time": "2026-11-10T12:00:00Z"})))
    conn.commit()
    ensure_schema(conn)
    assert collect.collect_lab_watches(conn) == 2
    assert collect.collect_lab_watches(conn) == 0                    # idempotent
    rows = conn.execute("SELECT signal_type, direction, ts, ref FROM ledger_signals ORDER BY ts").fetchall()
    assert [tuple(r) for r in rows] == [("rosyade_family_4h", -1, "2026-11-10T04:00:00Z", "watch:1"),
                                        ("rosyade_family_4h", 1, "2026-11-10T12:00:00Z", "watch:1")]


def test_collect_universal_entries_and_flips(conn):
    from src.lab.db import dumps
    ins = "INSERT INTO universal_rebalances (watch_id, bar, targets_json, created_at) VALUES (3, ?, ?, 'x')"
    conn.execute(ins, ("2026-11-01T04:00:00Z", dumps([{"symbol": "SOLUSDT", "weight_pct": 20}, {"symbol": "ETHUSDT", "weight_pct": 10}])))
    conn.execute(ins, ("2026-11-01T08:00:00Z", dumps([{"symbol": "SOLUSDT", "weight_pct": 25}, {"symbol": "ETHUSDT", "weight_pct": -10}])))
    conn.execute(ins, ("2026-11-01T12:00:00Z", dumps([{"symbol": "SOLUSDT", "weight_pct": 25}])))
    conn.commit()
    ensure_schema(conn)
    assert collect.collect_universal(conn) == 3                      # SOL, ETH long, ETH flip short
    assert collect.collect_universal(conn) == 0
    flips = conn.execute("SELECT symbol, direction, ts FROM ledger_signals WHERE symbol='ETHUSDT' ORDER BY ts").fetchall()
    assert [tuple(r) for r in flips] == [("ETHUSDT", 1, "2026-11-01T04:00:00Z"), ("ETHUSDT", -1, "2026-11-01T08:00:00Z")]


def _trading_db(path):
    t = sqlite3.connect(path)
    t.execute("CREATE TABLE trade_logs (id TEXT PRIMARY KEY, user_id TEXT, symbol TEXT, action TEXT, side TEXT, "
              "exchange TEXT, size_value REAL, status TEXT, order_id TEXT, fill_price REAL, filled_quantity REAL, "
              "created_at TEXT, error_details TEXT)")
    rows = [("1", "user-aaaa", "ETH/USDT:USDT", "open", "short", "rejected", None, "2026-11-09T00:00:07.471940+00:00"),
            ("2", "user-bbbb", "ETH/USDT:USDT", "open", "short", "success", 2100.5, "2026-11-09T00:00:09.000000+00:00"),
            ("3", "user-aaaa", "ETH/USDT:USDT", "close", "short", "success", 2000.0, "2026-11-10T00:00:05.000000+00:00"),
            ("4", "user-aaaa", "SOL/USDT:USDT", "open", "long", "failed", None, "2026-11-10T04:00:03.000000+00:00")]
    t.executemany("INSERT INTO trade_logs (id, user_id, symbol, action, side, exchange, size_value, status, fill_price, "
                  "created_at) VALUES (?, ?, ?, ?, ?, 'binance', 50, ?, ?, ?)",
                  [(a, b, c, d, e, f, g, h) for a, b, c, d, e, f, g, h in rows])
    t.commit()
    t.close()


def test_collect_webhook_read_only_and_merged(conn, tmp_path):
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p)
    before = (p.stat().st_mtime_ns, p.read_bytes())
    ensure_schema(conn)
    assert collect.collect_webhook(conn, str(p)) == 2               # ETH short (2 users merged) + SOL long
    assert collect.collect_webhook(conn, str(p)) == 0
    assert (p.stat().st_mtime_ns, p.read_bytes()) == before         # never written
    eth = conn.execute("SELECT * FROM ledger_signals WHERE symbol='ETHUSDT'").fetchone()
    assert eth["direction"] == -1 and eth["ts"] == "2026-11-09T00:00:07Z" and eth["price"] == 2100.5
    assert '"users": 2' in eth["meta_json"] and "rejected" in eth["meta_json"]
    assert collect.collect_webhook(conn, str(tmp_path / "missing.db")) == 0


# ── scheduling / worker ──────────────────────────────────────────────────

def test_schedule_tick_hourly_and_one_backfill(conn, monkeypatch):
    from src.lab.settings import get_lab_settings
    monkeypatch.setenv("LAB_LEDGER_BACKFILL_DAYS", "5")
    s = get_lab_settings()
    now = T0 + 3600 * 5 + 120
    a = schedule.tick(conn, s, now)
    assert len(a) == 2
    kinds = [r[0] for r in conn.execute("SELECT kind FROM lab_jobs ORDER BY id")]
    assert kinds == ["ledger_cycle", "ledger_backfill"]
    assert kv_get(conn, "ledger_cycle_bar") == iso(T0 + 5 * 3600)
    assert schedule.tick(conn, s, now + 60) == []                    # same hour / backfill already queued
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert len(schedule.tick(conn, s, now + 3600)) == 1              # next hour, never a 2nd backfill
    monkeypatch.setenv("LAB_LEDGER_ENABLED", "0")
    assert schedule.tick(conn, s, now + 7200) == []


def test_worker_runs_ledger_jobs_in_screener_venv(lab_env):
    from src.lab.worker import FAST_KINDS, Worker
    w = Worker()
    assert w._cmd(7, "ledger_cycle")[0] == sys.executable
    assert w._cmd(7, "ledger_backfill")[0] == sys.executable
    assert w._cmd(7, "run")[0] == w.settings.engine_python
    assert "ledger_cycle" in FAST_KINDS and "ledger_backfill" not in FAST_KINDS


def test_execute_cycle_with_fakes(conn, tmp_path, monkeypatch, sample_df):
    from src.lab.settings import get_lab_settings
    from src.lab.ledger import jobs
    from src.services.models import ProcessedResult
    p = tmp_path / "bmtm_trading.db"
    _trading_db(p)
    monkeypatch.setenv("LAB_TRADING_DB_PATH", str(p))
    get_lab_settings.cache_clear()

    class Proc:
        async def process_all(self):
            return ProcessedResult(data=sample_df, errors=[])

    jid = q.enqueue(conn, "ledger_cycle", None, {"bar": iso(T0)})
    job = dict(conn.execute("SELECT * FROM lab_jobs WHERE id=?", (jid,)).fetchone())
    out = jobs.execute_cycle(conn, job, processor=Proc(), fetch=lambda s, a, b: [])
    assert out["screener"]["baseline"] and out["collect"]["webhook"] == 2
    assert out["score"]["pending"] == 2
    assert kv_get(conn, "ledger_last_cycle")["bar"] == iso(T0)


def test_execute_backfill_with_fake_api(conn):
    from src.lab.ledger import jobs

    class Api:
        @staticmethod
        def klines(sym, tf, a, b):
            step = {"1h": 3600, "1d": 86400}[tf]
            n = int((b - a) / 1000 // step)
            k = hash(sym) % 7 - 3
            return bars(a // 1000, n, lambda i: 100 + 0.01 * k * i + 0.5 * math.sin(i / 5 + k), step=step)

        @staticmethod
        def funding(sym, a, b):
            return [{"ts": a + 8 * 3_600_000 * j, "rate": 0.0001 * (hash(sym) % 5 - 2)} for j in range(int((b - a) / 28_800_000))]

        @staticmethod
        def long_short_hist(sym, a, b):
            return [{"ts": a + 3_600_000 * j, "v": 1 + 0.2 * math.sin(j / 7 + hash(sym) % 3)} for j in range(int((b - a) / 3_600_000) + 1)]

        @staticmethod
        def open_interest_hist(sym, a, b):
            return [{"ts": a + 3_600_000 * j, "v": 1000 + 5 * math.sin(j / 9)} for j in range(int((b - a) / 3_600_000) + 1)]

    jid = q.enqueue(conn, "ledger_backfill", None, {"days": 2})
    q.claim(conn, "t")
    job = dict(conn.execute("SELECT * FROM lab_jobs WHERE id=?", (jid,)).fetchone())
    syms = [f"C{i}USDT" for i in range(8)]
    state = jobs.execute_backfill(conn, job, api=Api, fetch=lambda s, a, b: [], symbols=syms,
                                  now=T0 + 100 * 86400 + 600)
    assert state["status"] == "done" and state["coins"] == 8 and state["hours"] == 48
    assert kv_get(conn, "ledger_backfill")["status"] == "done"
    assert conn.execute("SELECT COUNT(*) FROM ledger_signals WHERE source NOT IN ('screener_rekon')").fetchone()[0] == 0


def test_norm_symbol():
    assert norm_symbol("BTC/USDT:USDT") == "BTCUSDT"
    assert norm_symbol("ethusdt.p") == "ETHUSDT"
    assert norm_symbol("1000PEPE/USDT:USDT") == "1000PEPEUSDT"


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


def test_api_admin_gate(api):
    plain = api("u-plain")
    for path in ("/api/v1/lab/ledger/meta", "/api/v1/lab/ledger/summary", "/api/v1/lab/ledger/signals"):
        assert plain.get(path).status_code == 403


def test_api_summary_and_signals(api, conn):
    ensure_schema(conn)
    for i in range(12):
        insert_signal(conn, source="screener", signal_type="komposit", symbol="ETHUSDT", direction=1 if i % 2 else -1,
                      ts=iso(T0 + i * 86400), dedupe_key=f"k{i}", meta={"tier": "A"})
    conn.commit()
    scoring.score_pending(conn, lambda s, a, b: bars(T0 - 3600, 30 * 96, lambda i: 100 + i * 0.01),
                          now_s=T0 + 40 * 86400)
    c = api("u-admin")
    m = c.get("/api/v1/lab/ledger/meta").json()
    assert m["horizons"] == list(HORIZONS) and m["symbols"] == ["ETHUSDT"] and m["types"][0]["n"] == 12
    s = c.get("/api/v1/lab/ledger/summary").json()
    g = s["groups"][0]
    assert (g["source"], g["signal_type"], g["n_signals"]) == ("screener", "komposit", 12)
    assert g["horizons"]["1d"]["n"] == 12 and g["horizons"]["1d"]["hit_rate"] == 0.5
    split = c.get("/api/v1/lab/ledger/summary", params={"split": "direction"}).json()["groups"]
    assert {x["direction"] for x in split} == {1, -1}
    assert all(x["horizons"]["4h"]["hit_rate"] == (1.0 if x["direction"] == 1 else 0.0) for x in split)
    r = c.get("/api/v1/lab/ledger/signals", params={"limit": 5, "since": "2026-10-05", "until": "2026-10-08"}).json()
    assert r["total"] == 4 and len(r["items"]) == 4 and r["items"][0]["ts"] == iso(T0 + 7 * 86400)
    assert set(r["items"][0]["outcomes"]) == set(HORIZONS) and r["items"][0]["meta"] == {"tier": "A"}
    assert c.get("/api/v1/lab/ledger/summary", params={"source": "nope"}).status_code == 422
    assert c.get("/api/v1/lab/ledger/signals", params={"since": "bad"}).status_code == 422
    assert c.get("/api/v1/lab/ledger/summary", params={"symbol": "BTC/USDT:USDT"}).json()["groups"] == []


def test_ledger_never_imports_trading():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "lab" / "ledger"
    for f in root.glob("*.py"):
        text = f.read_text()
        assert "from src.trading" not in text and "import src.trading" not in text
        assert "telegram" not in text.lower()
    assert os.path.exists(root / "__init__.py")
