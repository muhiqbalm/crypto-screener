"""Universal v0: params, causality, accounting, honesty pipeline, paper rebalance,
strength table, alerts (mocked sender — never the real Telegram group), scheduling, API."""
import dataclasses
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.lab import honesty, paper
from src.lab import queue as q
from src.lab.db import dumps, utcnow
from src.lab.settings import get_lab_settings
from src.lab.universal import alerts, live
from src.lab.universal import backtest as B
from src.lab.universal import params as P
from src.lab.universal import runner as R
from src.lab.universal import strategy as S
from src.lab.universal import strength as ST

COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}


@pytest.fixture(autouse=True)
def _no_real_telegram(monkeypatch):
    """Belt and braces: tests can never reach the real BMTM group."""
    monkeypatch.setenv("TRADING_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TRADING_TELEGRAM_DEFAULT_CHAT_ID", "")
    monkeypatch.setenv("LAB_TELEGRAM_CHAT_ID", "")

    def boom(*_a, **_k):
        raise AssertionError("real Telegram sender must not be used in tests")
    monkeypatch.setattr(alerts, "default_sender", boom)


def make_frames(days=600, n=6, seed=1, start="2023-01-01", late=None):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=days * 6, freq="4h", tz="UTC")
    ohlcv, fund = {}, {}
    names = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT"][:n]
    for k, s in enumerate(names):
        drift = (k - n / 2) * 0.0004
        # regime switches so trend/momentum both have something to do
        regime = np.sign(np.sin(np.arange(len(ts)) / (6 * 45) + k))
        r = drift + 0.0006 * regime + rng.normal(0, 0.012, len(ts))
        px = 100 * np.exp(np.cumsum(r))
        df = pd.DataFrame({"timestamp": ts, "open": px, "high": px * 1.01, "low": px * 0.99, "close": px,
                           "volume": 1.0})
        if late and s in late:
            df = df.iloc[late[s]:]
        ohlcv[s] = df.reset_index(drop=True)
        fts = pd.date_range(start, periods=days * 3, freq="8h", tz="UTC")
        fund[s] = pd.DataFrame({"timestamp": fts, "funding_rate": np.full(len(fts), 0.0001)})
    return ohlcv, fund


@pytest.fixture(scope="module")
def panel():
    o, f = make_frames()
    return S.build_panel(o, f)


# ── params ───────────────────────────────────────────────────────────────

def test_params_defaults_and_validation():
    p = P.validate_params({})
    assert p["top_n"] == 5 and p["rebalance"] == "1d" and p["symbols"] == []
    assert P.validate_params({"symbols": ["eth/usdt", "BTCUSDT", "ETHUSDT"]})["symbols"] == ["ETHUSDT", "BTCUSDT"]
    for bad in ({"nope": 1}, {"top_n": 0}, {"top_n": 2.5}, {"rebalance": "1w"}, {"allow_short": "yes"},
                {"mom_short_days": 40, "mom_mid_days": 30}, {"max_weight_pct": 80, "max_gross": 0.5},
                {"symbols": ["BAD"]}):
        with pytest.raises(P.ParamError):
            P.validate_params(bad)
    specs = P.resolve_search({"params": ["top_n"], "ranges": {"top_n": [2, 4]}})
    assert specs[0]["min"] == 2 and specs[0]["max"] == 4
    with pytest.raises(P.ParamError):
        P.resolve_search({"params": ["allow_short"]})


# ── strategy ─────────────────────────────────────────────────────────────

def test_funding_mapped_to_bar_and_listing_mask():
    o, f = make_frames(days=200, n=3, late={"SOLUSDT": 300})
    pn = S.build_panel(o, f)
    j = pn.index_of("SOLUSDT")
    assert pn.first_idx[j] == 300 and not pn.present[:300, j].any()
    # 3 settlements per day of 0.0001 -> 0.0003/day spread over 4H bars
    assert abs(pn.funding[6:12, 0].sum() - 0.0003) < 1e-12
    # settlement at 08:00 belongs to the bar opening 04:00
    k = int(np.flatnonzero(pn.ts == pd.Timestamp("2023-01-02 04:00", tz="UTC"))[0])
    assert pn.funding[k, 0] == pytest.approx(0.0001) and pn.funding[k + 1, 0] == 0


def test_no_lookahead(panel):
    p = P.validate_params({"allow_short": True})
    feat = S.compute_features(panel, p)
    t = 2500
    w = S.target_weights(feat, panel, t, p)
    tampered = dataclasses.replace(panel, close=panel.close.copy())
    tampered.close[t + 1:] *= np.linspace(0.2, 5, panel.close.shape[1])[None, :]
    feat2 = S.compute_features(tampered, p)
    assert np.allclose(S.target_weights(feat2, tampered, t, p), w)


def test_weights_respect_caps_and_trend(panel):
    p = P.validate_params({"top_n": 3, "max_weight_pct": 30, "max_gross": 0.9, "target_vol_pct": 150})
    feat = S.compute_features(panel, p)
    for t in range(1000, len(panel.ts), 97):
        w = S.target_weights(feat, panel, t, p)
        assert (w >= 0).all() and np.abs(w).max() <= 0.30 + 1e-9 and np.abs(w).sum() <= 0.9 + 1e-9
        assert np.count_nonzero(w) <= 3
        assert all(feat.up[t, i] and feat.eligible[t, i] and feat.score[t, i] > 0 for i in np.flatnonzero(w))


def test_rebalance_mask_daily(panel):
    m = S.rebalance_mask(panel, "1d")
    assert set(np.asarray(panel.ts[m].hour)) == {20} and S.rebalance_mask(panel, "4h").all()


# ── backtest accounting ──────────────────────────────────────────────────

def _one_coin(days=60, step=0.001, funding=0.0, crash_at=None):
    ts = pd.date_range("2024-01-01", periods=days * 6, freq="4h", tz="UTC")
    px = 100 * np.exp(step * np.arange(len(ts)))
    if crash_at is not None:
        px[crash_at:] *= 0.6
    o = {"BTCUSDT": pd.DataFrame({"timestamp": ts, "close": px})}
    f = {"BTCUSDT": pd.DataFrame({"timestamp": pd.date_range("2024-01-01 08:00", periods=days * 3, freq="8h",
                                                               tz="UTC"), "funding_rate": funding})}
    return S.build_panel(o, f)


def test_simulate_constant_weight_costs_and_funding():
    pn = _one_coin(funding=0.0001)
    p = P.validate_params({"min_trade_pct": 0.0})
    feat = S.compute_features(pn, {**p, "vol_days": 7, "mom_short_days": 2, "mom_mid_days": 3, "mom_long_days": 5})
    rebal = np.zeros(len(pn.ts), dtype=bool)
    rebal[0] = True
    end = len(pn.ts) - 1
    free = B.simulate(pn, feat, p, {"commission_pct": 0, "slippage_pct": 0, "funding": False}, 0, end, rebal,
                      weight_fn=lambda t: np.array([1.0]))
    growth = pn.close[end, 0] / pn.close[0, 0]
    assert free.equity[-1] == pytest.approx(10000 * growth, rel=1e-9)
    paid = B.simulate(pn, feat, p, COSTS, 0, end, rebal, weight_fn=lambda t: np.array([1.0]))
    assert paid.fees.sum() == pytest.approx(10000 * 0.0005) and paid.slippage.sum() == pytest.approx(5.0)
    assert paid.funding.sum() > 0 and paid.equity[-1] < free.equity[-1]   # long pays positive funding
    short = B.simulate(pn, feat, p, {"commission_pct": 0, "slippage_pct": 0, "funding": True}, 0, end, rebal,
                       weight_fn=lambda t: np.array([-0.5]))
    assert short.funding.sum() < 0                                        # short receives
    assert len(paid.episodes) == 1 and paid.episodes[0]["open_at_end"]
    m = B.metrics(paid, pn)
    assert m["trades"] == 1 and m["net_return_pct"] > 0 and m["liquidations"] == 0


def test_episode_pnl_sums_to_total(panel):
    p = P.validate_params({"rebalance": "4h", "allow_short": True})
    feat = S.compute_features(panel, p)
    a = S.first_tradable_index(feat, p)
    sim = B.simulate(panel, feat, p, COSTS, a, len(panel.ts) - 1)
    tot = sum(e["pnl"] for e in sim.episodes)
    assert tot == pytest.approx(sim.equity[-1] - sim.initial, rel=1e-6, abs=1e-6)
    assert sim.contrib.sum() == pytest.approx(sim.equity[-1] - sim.initial, rel=1e-6, abs=1e-6)
    assert sum(r["pnl"] for r in B.contributions(sim, panel)) == pytest.approx(tot, rel=1e-6, abs=1e-6)


def test_blown_account_counts_as_liquidation():
    pn = _one_coin(crash_at=100)
    p = P.validate_params({"max_gross": 3.0, "max_weight_pct": 100})
    feat = S.compute_features(pn, {**p, "vol_days": 7, "mom_short_days": 2, "mom_mid_days": 3, "mom_long_days": 5})
    rebal = np.zeros(len(pn.ts), dtype=bool)
    rebal[0] = True
    sim = B.simulate(pn, feat, p, COSTS, 0, len(pn.ts) - 1, rebal, weight_fn=lambda t: np.array([3.0]))
    assert sim.blown and B.metrics(sim, pn)["liquidations"] == 1


# ── honesty helpers ──────────────────────────────────────────────────────

def test_stability_and_monte_carlo():
    assert R.stability_score(-5, [10, 20])[0] == 0.0
    s, prof = R.stability_score(50, [45, 55, 50, 48])
    assert 0.8 < s <= 1 and prof == 1
    rng = np.random.default_rng(0)
    mc = R.monte_carlo(rng.normal(0.001, 0.03, 500), n_sims=200)
    assert mc["n_simulations"] == 200 and mc["dd_p99"] <= mc["dd_p95"] < 0
    assert R.monte_carlo(np.zeros(5))["dd_p95"] is None


def test_evaluate_all_validate_keeps_holdout_out_of_dev(panel, monkeypatch):
    p = P.validate_params({})
    seen = []
    real = R.run_segment

    def spy(pn, *a, **k):
        seen.append(pn.ts[-1])
        return real(pn, *a, **k)
    monkeypatch.setattr(R, "run_segment", spy)
    feat = S.compute_features(panel, p)
    a, b = R.eval_range(panel, feat, p, None, None)
    hs = honesty.proposed_holdout_start(B.iso(panel.ts[a]), B.iso(panel.ts[b]), S.BAR_S)
    res = R.evaluate_all(panel, p, COSTS, "validate", None, None, holdout_start=hs)
    assert seen and max(seen) < pd.Timestamp(hs)
    assert {c["name"] for c in res["checks"]} == {"oos_profit_factor", "oos_net_return", "mc_dd_p95",
                                                   "min_oos_trades", "cost_stress", "sensitivity", "no_liquidation"}
    assert res["verdict"] in ("PASS", "FAIL") and res["verdict"] == honesty.verdict(res["checks"])
    assert res["oos"]["start"] == hs and res["metrics"]["walk_forward"]["folds"]
    assert {x["segment"] for x in res["equity"]} >= {"is", "holdout"}
    assert res["metrics"]["monte_carlo"]["method"] == "block_bootstrap_daily"


def test_optimize_random_fallback_only_sees_dev(panel, monkeypatch):
    monkeypatch.setitem(sys.modules, "optuna", None)  # force the random-search path
    p = P.validate_params({})
    feat = S.compute_features(panel, p)
    a, b = R.eval_range(panel, feat, p, None, None)
    hs = honesty.proposed_holdout_start(B.iso(panel.ts[a]), B.iso(panel.ts[b]), S.BAR_S)
    specs = P.resolve_search({"params": ["top_n"], "ranges": {"top_n": [2, 4]}})
    res = R.evaluate_all(panel, p, COSTS, "optimize", None, None, holdout_start=hs, n_trials=4, specs=specs)
    assert res["optimizer"]["sampler"] == "random" and res["optimizer"]["trials"] == 4
    assert 2 <= res["params"]["top_n"] <= 4


# ── run job through the real runner (DB, lock, immutability) ─────────────

def _insert_run(conn, mode, params=None):
    from src.api.lab_routes import create_run
    run_id, job_id = create_run(conn, template_id="universal_v0", symbol="UNIVERSE", timeframe="4h", mode=mode,
                                params=P.validate_params(params or {}), costs=COSTS, start=None, end=None)
    conn.commit()
    return run_id, job_id


def test_runner_validate_writes_verdict_and_locks_holdout(conn, panel, monkeypatch):
    from src.lab import runner
    monkeypatch.setattr(R, "load_panel", lambda *a, **k: panel)
    monkeypatch.setattr(R, "universe_symbols", lambda p: list(panel.symbols))
    run_id, job_id = _insert_run(conn, "validate")
    job = q.claim(conn, "w")
    assert job["id"] == job_id
    runner.execute_run(conn, job)
    r = dict(conn.execute("SELECT * FROM lab_runs WHERE id=?", (run_id,)).fetchone())
    assert r["verdict"] in ("PASS", "FAIL") and r["holdout_touches"] == 1 and r["holdout_start"]
    lock = honesty.get_lock(conn, "universal_v0", "UNIVERSE", "4h")
    assert lock["holdout_start"] == r["holdout_start"]
    with pytest.raises(Exception):
        conn.execute("UPDATE lab_runs SET verdict='PASS' WHERE id=?", (run_id,))
    art = runner.artifacts_dir(run_id)
    assert (art / "equity.json").exists() and (art / "contrib.json").exists()
    # second run reuses the same lock and counts another touch
    run2, _ = _insert_run(conn, "validate", {"top_n": 3})
    runner.execute_run(conn, q.claim(conn, "w"))
    r2 = conn.execute("SELECT holdout_start, holdout_touches FROM lab_runs WHERE id=?", (run2,)).fetchone()
    assert r2["holdout_start"] == r["holdout_start"] and r2["holdout_touches"] == 2


def test_runner_backtest_mode(conn, panel, monkeypatch):
    from src.lab import runner
    monkeypatch.setattr(R, "load_panel", lambda *a, **k: panel)
    monkeypatch.setattr(R, "universe_symbols", lambda p: list(panel.symbols))
    run_id, _ = _insert_run(conn, "backtest")
    runner.execute_run(conn, q.claim(conn, "w"))
    r = conn.execute("SELECT verdict, trades, metrics_json FROM lab_runs WHERE id=?", (run_id,)).fetchone()
    assert r["verdict"] is None and r["trades"] > 0 and "benchmarks" in r["metrics_json"]


# ── paper rebalance / watch ──────────────────────────────────────────────

def _watch(conn, acct, params=None, telegram=1):
    wid = conn.execute(
        "INSERT INTO universal_watches (name, params_json, costs_json, account_id, autopaper_enabled, telegram_enabled, "
        "active, created_at) VALUES ('U', ?, ?, ?, 1, ?, 1, ?)",
        (dumps(P.validate_params(params or {})), dumps(COSTS), acct, telegram, utcnow())).lastrowid
    conn.commit()
    return dict(conn.execute("SELECT * FROM universal_watches WHERE id=?", (wid,)).fetchone())


def test_rebalance_paper_open_resize_close(conn):
    acct = paper.create_account(conn, "u", 10000, leverage_max=2)
    w = _watch(conn, acct)
    prices = {"BTCUSDT": 100.0, "ETHUSDT": 10.0, "SOLUSDT": 1.0}
    p = P.validate_params({"min_trade_pct": 2.0})
    orders, eq = live.rebalance_paper(conn, w, {"BTCUSDT": 0.3, "ETHUSDT": 0.2, "SOLUSDT": 0.01}, prices.get, p, COSTS)
    assert eq == pytest.approx(10000) and {o["symbol"] for o in orders} == {"BTCUSDT", "ETHUSDT"}  # SOL < min trade
    pos = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM paper_positions WHERE status='open'")}
    assert pos["BTCUSDT"]["qty"] == pytest.approx(30.0) and pos["BTCUSDT"]["source"] == "paper_auto"
    assert pos["BTCUSDT"]["strategy_ref"] == f"universal:{w['id']}" and pos["BTCUSDT"]["sl"] is None
    # BTC up 10%: reduce BTC, close ETH, add nothing below band
    prices["BTCUSDT"] = 110.0
    orders, _ = live.rebalance_paper(conn, w, {"BTCUSDT": 0.15}, prices.get, p, COSTS)
    acts = {o["symbol"]: o["action"] for o in orders}
    assert acts == {"BTCUSDT": "reduce", "ETHUSDT": "close"}
    j = [dict(r) for r in conn.execute("SELECT * FROM journal_entries ORDER BY id")]
    assert len(j) == 2 and all(e["source"] == "paper_auto" and e["strategy_ref"] == f"universal:{w['id']}" for e in j)
    btc_leg = [e for e in j if e["symbol"] == "BTCUSDT"][0]
    assert btc_leg["pnl"] > 0
    a = paper.get_account(conn, acct)
    assert a["balance"] == pytest.approx(10000 + sum(e["pnl"] for e in j))
    # flip to short
    orders, _ = live.rebalance_paper(conn, w, {"BTCUSDT": -0.1}, prices.get, p, COSTS)
    assert [o["action"] for o in orders] == ["close", "open"] and orders[1]["side"] == "short"


def test_evaluate_watch_due_once_per_boundary_and_alert(conn, panel):
    acct = paper.create_account(conn, "u", 10000, leverage_max=2)
    w = _watch(conn, acct)
    last_close = panel.ts[-1] + pd.Timedelta(hours=4)
    px = {s: float(panel.close[-1, i]) for i, s in enumerate(panel.symbols)}
    r1 = live.evaluate_watch(conn, w, panel, px.get, now=last_close)
    assert r1["due"]
    st = conn.execute("SELECT * FROM universal_state WHERE watch_id=?", (w["id"],)).fetchone()
    assert st["error"] is None and st["next_rebalance"]
    w = dict(conn.execute("SELECT * FROM universal_watches WHERE id=?", (w["id"],)).fetchone())
    r2 = live.evaluate_watch(conn, w, panel, px.get, now=last_close)
    assert not r2["due"]
    n_reb = conn.execute("SELECT COUNT(*) FROM universal_rebalances WHERE watch_id=?", (w["id"],)).fetchone()[0]
    assert n_reb == 1
    al = conn.execute("SELECT * FROM lab_alerts").fetchall()
    assert len(al) == 1 and "[PAPER]" in al[0]["text"] and "BUKAN order nyata" in al[0]["text"]
    if r1["targets"]:
        held = conn.execute("SELECT COUNT(*) FROM paper_positions WHERE status='open'").fetchone()[0]
        assert held >= 1


def test_evaluate_watch_refuses_stale_data(conn, panel):
    acct = paper.create_account(conn, "u", 10000)
    w = _watch(conn, acct)
    with pytest.raises(RuntimeError, match="stale"):
        live.evaluate_watch(conn, w, panel, lambda s: 1.0, now=panel.ts[-1] + pd.Timedelta(days=3))


def test_execute_refresh_runs_strength_and_watches(conn, lab_env, panel, monkeypatch):
    monkeypatch.setenv("LAB_DATA_OFFLINE", "1")
    monkeypatch.setattr(live, "load_panel", lambda *a, **k: panel)
    monkeypatch.setattr(live, "universe_symbols", lambda p: list(panel.symbols))
    acct = paper.create_account(conn, "u", 10000)
    _watch(conn, acct, telegram=0)
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: panel.ts[-1] + pd.Timedelta(hours=4)))
    jid = q.enqueue(conn, "universe_refresh")
    out = live.execute_refresh(conn, {"id": jid}, price_fn=lambda s: 100.0)
    data = ST.load()
    assert data and data["rows"] and out["watches"]
    ranks = [r["rank"] for r in data["rows"] if r["rank"] is not None]
    assert ranks == sorted(ranks) and ranks[0] == 1
    assert all(len(r["spark"]) <= ST.SPARK_DAYS for r in data["rows"])
    assert conn.execute("SELECT COUNT(*) FROM lab_alerts").fetchone()[0] == 0  # telegram off


# ── alerts (mock sender only) ────────────────────────────────────────────

def _tg_settings(**kw):
    base = {"telegram_enabled": True, "telegram_bot_token": "TEST", "telegram_chat_id": "-100"}
    return dataclasses.replace(get_lab_settings(), **{**base, **kw})


def test_alerts_coalesce_and_rate_limit(conn):
    sent = []
    s = _tg_settings(telegram_min_interval_s=300, telegram_max_per_hour=2)
    alerts.enqueue(conn, "universal:1", "old")
    alerts.enqueue(conn, "universal:1", "new")
    now = datetime.now(timezone.utc)
    assert alerts.send_pending(conn, s, sender=sent.append, now=now) == 1
    assert sent == ["new"]
    st = {r["text"]: r["status"] for r in conn.execute("SELECT * FROM lab_alerts")}
    assert st == {"old": "superseded", "new": "sent"}
    alerts.enqueue(conn, "universal:1", "too soon")
    assert alerts.send_pending(conn, s, sender=sent.append, now=now + timedelta(seconds=60)) == 0
    assert alerts.send_pending(conn, s, sender=sent.append, now=now + timedelta(seconds=400)) == 1
    alerts.enqueue(conn, "universal:2", "cap")
    assert alerts.send_pending(conn, s, sender=sent.append, now=now + timedelta(seconds=500)) == 0  # 2/hour cap
    assert sent == ["new", "too soon"]


def test_alerts_disabled_or_unconfigured_are_skipped(conn):
    sent = []
    alerts.enqueue(conn, "universal:1", "x")
    alerts.send_pending(conn, _tg_settings(telegram_enabled=False), sender=sent.append)
    assert sent == [] and conn.execute("SELECT status FROM lab_alerts").fetchone()[0] == "skipped"
    alerts.enqueue(conn, "universal:1", "y")
    alerts.send_pending(conn, get_lab_settings(), sender=sent.append)  # fixture env: no token
    assert sent == []


def test_alert_sender_error_is_recorded(conn):
    def bad(_):
        raise ConnectionError("down")
    alerts.enqueue(conn, "universal:1", "x")
    assert alerts.send_pending(conn, _tg_settings(), sender=bad) == 0
    assert conn.execute("SELECT status FROM lab_alerts").fetchone()[0] == "error"


def test_notifier_loads_without_trading_package():
    alerts._notifier_cls = None
    cls = alerts._load_notifier()
    assert cls.__name__ == "TelegramNotifier"


def test_settings_never_repr_token(monkeypatch):
    s = _tg_settings()
    assert "TEST" not in repr(s)


# ── scheduler / worker ───────────────────────────────────────────────────

def test_schedule_universe_once_per_bar(conn):
    from src.lab.scheduler import schedule_universe
    s = get_lab_settings()
    now = datetime(2026, 11, 10, 4, 1, tzinfo=timezone.utc).timestamp()
    assert schedule_universe(conn, s, now) is not None
    assert schedule_universe(conn, s, now + 60) is None
    q.finish(conn, conn.execute("SELECT id FROM lab_jobs").fetchone()[0], "done")
    assert schedule_universe(conn, s, now + 4 * 3600) is not None
    off = dataclasses.replace(s, strength_refresh=False)
    assert schedule_universe(conn, off, now + 8 * 3600) is None  # no watches + refresh off


def test_worker_fast_lane_runs_refresh_next_to_long_job(lab_env):
    from src.lab import db as labdb
    from src.lab.worker import Worker
    c = labdb.connect()
    q.enqueue(c, "run", None)
    q.enqueue(c, "universe_refresh", None)
    c.commit()
    w = Worker(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        w.tick(c)
        kinds = sorted(r.job["kind"] for r in w.running.values())
        assert kinds == ["run", "universe_refresh"]
    finally:
        for r in list(w.running.values()):
            w._kill(r, "test")
        c.close()


# ── API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_client(lab_env):
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


def test_api_universal_flow(admin_client):
    c = admin_client("u-admin")
    sch = c.get("/api/v1/lab/universal/schema").json()
    assert sch["id"] == "universal_v0" and sch["defaults"]["top_n"] == 5 and sch["holdout_lock"] is None
    r = c.post("/api/v1/lab/universal/runs", json={"mode": "validate", "params": {"top_n": 4}})
    assert r.status_code == 200
    run = c.get(f"/api/v1/lab/runs/{r.json()['run_id']}").json()
    assert run["template_id"] == "universal_v0" and run["symbol"] == "UNIVERSE" and run["params"]["top_n"] == 4
    assert c.post("/api/v1/lab/universal/runs", json={"params": {"top_n": 99}}).status_code == 422
    assert c.post("/api/v1/lab/universal/runs", json={"mode": "validate", "search": {"params": ["top_n"]}}
                  ).status_code == 422
    assert c.get(f"/api/v1/lab/universal/runs/{r.json()['run_id']}/contrib").json() == {"full": [], "holdout": None}
    wr = c.post("/api/v1/lab/universal/watches", json={"name": "Uni", "params": {}}).json()
    assert wr["account_id"]
    lst = c.get("/api/v1/lab/universal/watches").json()
    assert lst[0]["telegram"] is True and lst[0]["autopaper"] is True and lst[0]["account"]["balance"] == 10000
    p = c.patch(f"/api/v1/lab/universal/watches/{wr['watch_id']}", json={"telegram": False}).json()
    assert p["telegram"] is False
    assert c.get(f"/api/v1/lab/universal/watches/{wr['watch_id']}/rebalances").json() == []
    st = c.get("/api/v1/lab/strength").json()
    assert st["rows"] == [] and st["refresh"]["status"] == "queued"
    j1 = c.post("/api/v1/lab/strength/refresh").json()["job_id"]
    assert j1 == st["refresh"]["job_id"]  # no duplicate refresh jobs
    assert c.delete(f"/api/v1/lab/universal/watches/{wr['watch_id']}").json()["active"] is False
    assert c.get("/api/v1/lab/universal/watches").json() == []
    assert c.get("/api/v1/lab/universal/alerts").status_code == 200


def test_api_universal_admin_only(admin_client):
    c = admin_client("u-plain")
    for path in ("/api/v1/lab/universal/schema", "/api/v1/lab/strength", "/api/v1/lab/universal/watches"):
        assert c.get(path).status_code == 403
    assert c.post("/api/v1/lab/universal/runs", json={}).status_code == 403
    assert c.post("/api/v1/lab/strength/refresh").status_code == 403
