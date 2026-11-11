"""End-to-end Lab runs (backtest / validate / optimize + watch) for the family templates on a REAL
engine with strategy families. Skipped where the engine or its deps (loguru, optuna, pyarrow) are
missing. No fastapi import, so it also runs under the engine interpreter:

    LAB_ENGINE_PATH=<engine> <engine python> -m pytest -q --confcutdir=tests/test_lab tests/test_lab/test_family_e2e.py
"""
import os
import sys
from pathlib import Path

import pytest

from src.lab.templates import TEMPLATES

COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}


def _engine_with_families():
    eng = Path(os.environ.get("LAB_ENGINE_PATH", "/root/bmtm-v2"))
    cfg_py = eng / "backtest_engine" / "config" / "strategy_config.py"
    if not cfg_py.exists() or "strategy_family" not in cfg_py.read_text():
        pytest.skip("engine without strategy families")
    for m in ("loguru", "optuna", "pyarrow"):
        pytest.importorskip(m)
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))


def _create_run(conn, tid, mode, params, costs, n_trials):
    """Same rows as src.api.lab_routes.create_run (kept fastapi-free)."""
    from src.lab import db as labdb, queue as q
    now = labdb.utcnow()
    cfg = conn.execute("INSERT INTO strategy_configs (template_id, params_json, created_at) VALUES (?, ?, ?)",
                       (tid, labdb.dumps(params), now)).lastrowid
    rid = conn.execute(
        "INSERT INTO lab_runs (scan_id, config_id, template_id, symbol, timeframe, mode, status, start_date, "
        "end_date, params_json, costs_json, search_json, n_trials, created_at) "
        "VALUES (NULL, ?, ?, 'ETHUSDT', '4h', ?, 'queued', NULL, NULL, ?, ?, NULL, ?, ?)",
        (cfg, tid, mode, labdb.dumps(params), labdb.dumps(costs), n_trials, now)).lastrowid
    jid = q.enqueue(conn, "run", rid, {"n_trials": n_trials} if n_trials else {})
    conn.execute("UPDATE lab_runs SET job_id=? WHERE id=?", (jid, rid))
    conn.commit()
    return int(rid)


def _synthetic_cache(lab_env, symbol="ETHUSDT", n=6 * 365 * 3):
    import numpy as np
    import pandas as pd
    from src.lab import data_cache as dc
    rng = np.random.default_rng(5)
    vol = 0.012 * np.exp(np.cumsum(rng.normal(0, 0.05, n)).clip(-1.5, 1.5))
    close = 1500 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol + 0.0003 * np.sin(np.arange(n) / 200)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 1, n)) * vol * close
    ts = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_, close) + spread,
                       "low": np.minimum(open_, close) - spread, "close": close,
                       "volume": rng.lognormal(10, 0.5, n)})
    dc.data_dir().mkdir(parents=True, exist_ok=True)
    df.to_parquet(dc.ohlcv_path(symbol, "4h"), index=False)
    fund = pd.DataFrame({"timestamp": pd.date_range("2022-01-01", periods=n // 2, freq="8h", tz="UTC"),
                         "funding_rate": 0.0001})
    fund.to_parquet(dc.funding_path(symbol), index=False)


@pytest.mark.parametrize("tid", ["donchian_breakout", "mean_reversion_range"])
def test_runner_end_to_end(conn, lab_env, monkeypatch, tid):
    _engine_with_families()
    monkeypatch.setenv("LAB_DATA_OFFLINE", "1")
    _synthetic_cache(lab_env)
    from src.lab import db as labdb, queue as q, runner, watch_eval
    t = TEMPLATES[tid]
    costs = COSTS
    for mode in ("backtest", "validate", "optimize"):
        rid = _create_run(conn, tid, mode, t.validate_params({}), costs, 6 if mode == "optimize" else None)
        runner.execute_run(conn, q.claim(conn, "w"))
        r = dict(conn.execute("SELECT * FROM lab_runs WHERE id=?", (rid,)).fetchone())
        m = labdb.loads(r["metrics_json"])
        assert r["status"] != "error" and r["trades"] is not None, (mode, r)
        assert r["trades"] > 0 or mode == "optimize", (mode, r)  # a 6-trial search may pick a 0-trade corner
        if mode != "backtest":
            assert r["verdict"] in ("PASS", "FAIL") and r["holdout_touches"] >= 1 and r["holdout_start"]
            assert m["sensitivity"]["tested"] >= 4 and m["monte_carlo"]["n_simulations"] > 0
            oos = labdb.loads(r["oos_metrics_json"])
            assert oos["stress_net_return_pct"] is not None and oos["start"] == r["holdout_start"]
        if mode == "optimize":
            assert m["walk_forward"]["folds"] and labdb.loads(r["best_params_json"])["dc_entry_len" if
                                                                                    tid.startswith("don") else "mr_len"]
            assert labdb.loads(r["extra_json"])["sensitivity"]["params"][0]["param"] in \
                (("dc_entry_len",) if tid.startswith("don") else ("mr_len",))
    state = watch_eval.evaluate({"template_id": tid, "symbol": "ETHUSDT", "timeframe": "4h",
                                 "params_json": labdb.dumps(t.validate_params({})), "costs_json": labdb.dumps(costs),
                                 "created_at": "2024-06-01T00:00:00Z"}, offline=True)
    assert state["recent_trades"]
