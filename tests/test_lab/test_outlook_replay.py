"""Outlook replay on a REAL engine (skipped where the engine or its deps are missing).

The trace hook must report, at every bar, exactly what an engine run truncated at that bar
reports as its open position (no look-ahead), and the replay must turn a synthetic history
into evaluated calls. No fastapi import, so it also runs under the engine interpreter:

    LAB_ENGINE_PATH=<engine> <engine python> -m pytest -q --confcutdir=tests/test_lab tests/test_lab/test_outlook_replay.py
"""
import os
import random
import sys
from pathlib import Path

import pytest


def _engine():
    eng = Path(os.environ.get("LAB_ENGINE_PATH", "/root/bmtm-v2"))
    if not (eng / "backtest_engine" / "engine" / "backtest_loop.py").exists():
        pytest.skip("engine not available")
    for m in ("loguru", "pyarrow"):
        pytest.importorskip(m)
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))


def _synthetic(lab_env, symbol="ETHUSDT", n=6 * 365 * 3):
    import numpy as np
    import pandas as pd
    from src.lab import data_cache as dc
    rng = np.random.default_rng(7)
    vol = 0.012 * np.exp(np.cumsum(rng.normal(0, 0.05, n)).clip(-1.5, 1.5))
    close = 1500 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol + 0.0003 * np.sin(np.arange(n) / 200)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 1, n)) * vol * close
    ts = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_, close) + spread,
                       "low": np.minimum(open_, close) - spread, "close": close, "volume": rng.lognormal(10, 0.5, n)})
    dc.data_dir().mkdir(parents=True, exist_ok=True)
    df.to_parquet(dc.ohlcv_path(symbol, "4h"), index=False)
    # 1H and 1D views of the same path (for the MTF factors)
    h = df.set_index("timestamp")
    h1 = h.resample("1h").ffill().reset_index()
    h1.to_parquet(dc.ohlcv_path(symbol, "1h"), index=False)
    d1 = h.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    d1.reset_index().to_parquet(dc.ohlcv_path(symbol, "1d"), index=False)
    d1.reset_index().to_parquet(dc.ohlcv_path("BTCUSDT", "1d"), index=False)
    fund = pd.DataFrame({"timestamp": pd.date_range("2022-01-01", periods=n // 2, freq="8h", tz="UTC"),
                         "funding_rate": 0.0001})
    fund.to_parquet(dc.funding_path(symbol), index=False)


def test_trace_equals_truncated_runs_and_replay_produces_cases(lab_env, monkeypatch):
    _engine()
    monkeypatch.setenv("LAB_DATA_OFFLINE", "1")
    _synthetic(lab_env)
    from src.lab import regime as R
    from src.lab import data_cache as dc
    from src.lab.outlook import replay as RP
    from src.lab.presets import DEFAULT_COSTS
    from src.lab.templates import get_template
    d1, _ = dc.ensure("BTCUSDT", "1d", funding=False, offline=True)
    data = RP.CoinData("ETHUSDT", True, R.RegimeIndex(R.label_series(d1)))
    t = get_template("rosyade_family")
    cfg = RP.Cfg("ETHUSDT", "rosyade_family", "4h", t.defaults(), dict(DEFAULT_COSTS), "belum_diuji", names=["default"])
    cases, info = RP.replay_config(cfg, data)
    assert info["trades"] > 0 and info["cases"] == len(cases) and cases
    assert {c.status for c in cases} <= {"tp", "sl", "batal", "expired", "open"}
    assert all(c.fase in ("baru", "berjalan") and c.align in ("searah", "campuran", "berlawanan") for c in cases)
    # the state at sampled bars equals runs truncated at those bars
    from src.lab import engine_adapter as ea
    scfg, ecfg = ea.build_configs(cfg.params, "4h", cfg.costs, cfg.template_id)
    df, _, _, _ = ea.prepare_frame(data.frame("4h"), data.funding, "4h", None, None, ecfg.warmup_period, True)
    res, _, trace = RP.traced_run(df, scfg, ecfg)
    pos = RP.positions_by_bar(res, trace, len(df))
    inpos = [i for i, p in enumerate(pos) if p is not None]
    flat = [i for i, p in enumerate(pos) if p is None and i > ecfg.warmup_period + 50]
    random.seed(3)
    sample = sorted(random.sample(inpos, min(3, len(inpos))) + random.sample(flat, min(1, len(flat))))
    checks = RP.verify_trace(cfg, data, sample)
    assert checks and all(c["match"] for c in checks), checks
    out = RP.summarise(cases, [info])
    assert out["counts"]["cases"] == len(cases) and "pool|long|*|*" in out["buckets"] or "pool|short|*|*" in out["buckets"]
