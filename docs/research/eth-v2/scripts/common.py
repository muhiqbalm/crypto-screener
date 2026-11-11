"""Shared setup for the 4H-ETH-v2 research. DEVELOPMENT data only unless a
function says otherwise. Runs on the VPS under /tmp/ethv2 with the bmtm-v2
interpreter (optuna + engine deps):

    cd /tmp/ethv2/crypto-screener/docs/research/eth-v2/scripts
    nice -n 10 /root/bmtm-v2/venv/bin/python <script>.py ...
"""
import json
import math
import os
import sys

EXP = os.environ.get("ETHV2_EXP", "/tmp/ethv2/exp")
os.environ.setdefault("LAB_ENGINE_PATH", "/tmp/ethv2/engine")
os.environ["LAB_DATA_DIR"] = f"{EXP}/data"
os.environ["LAB_DB_PATH"] = f"{EXP}/lab.db"
os.environ["LAB_ARTIFACTS_DIR"] = f"{EXP}/artifacts"
os.environ["LAB_DATA_OFFLINE"] = "1"
os.environ["LAB_TELEGRAM_ENABLED"] = "0"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ.get("ETHV2_REPO", "/tmp/ethv2/crypto-screener"))

import pandas as pd  # noqa: E402

from src.lab import data_cache as dc  # noqa: E402
from src.lab import engine_adapter as ea  # noqa: E402
from src.lab import honesty  # noqa: E402
from src.lab.templates import rosyade_family as T  # noqa: E402

SYM, TF = "ETHUSDT", "4h"
START, END = "2020-01-01", "2026-11-09"          # same range as the 2026-11-11 MTF research
HS = "2025-07-06T04:00:00Z"                      # ETH 4h holdout start used by every earlier look
COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}
BIG_WARMUP = 1600                                # >= any candidate's effective warm-up (1d EMA <= 200)
FIRST_TEST = "2021-07-01"                        # common fold calendar for every variant
OUT = f"{EXP}/out"
os.makedirs(OUT, exist_ok=True)

_cache = {}


def frame():
    """(full_df, dev_df) with BIG_WARMUP rows of head-room; dev_df ends before HS."""
    if "f" not in _cache:
        ohlcv, fund = dc.ensure(SYM, TF, funding=True, offline=True)
        df, es, ee, _ = ea.prepare_frame(ohlcv, fund, TF, START, END, BIG_WARMUP, True)
        hs = pd.Timestamp(HS)
        dev = df[df["timestamp"] < hs].reset_index(drop=True)
        honesty.assert_dev_only(dev["timestamp"].tail(1), HS)
        _cache["f"] = (df, dev)
    return _cache["f"]


def folds():
    """Rolling 12m train / 3m test windows; tests tile [FIRST_TEST, HS)."""
    out, t = [], pd.Timestamp(FIRST_TEST, tz="UTC")
    hs = pd.Timestamp(HS)
    while t + pd.DateOffset(months=3) <= hs:
        out.append((t - pd.DateOffset(months=12), t, t + pd.DateOffset(months=3)))
        t = t + pd.DateOffset(months=3)
    return out


def warm(params):
    return ea.effective_warmup(T.validate_params(params), TF)


def run_window(df, params, t0, t1, cost_mult=1.0):
    p = T.validate_params(params)
    cfg, ecfg = ea.build_configs(p, TF, COSTS)
    w = ecfg.warmup_period
    sl, pre = ea.window(df, t0, t1, w)
    if pre < w:
        raise ValueError(f"not enough warm-up before {t0}: {pre} < {w}")
    if cost_mult != 1.0:
        ecfg = ea.scaled_costs(ecfg, cost_mult)
    res, ind = ea.run(sl, cfg, ecfg, warmup=pre)
    return res, ind, pre, cfg, ecfg


def quarter_returns(res, t0, t1):
    """Return (%) per calendar quarter of the mark-to-market equity curve in [t0, t1)."""
    eq = pd.DataFrame([(e[0], e[1]) for e in res.equity_curve], columns=["ts", "eq"])
    eq["ts"] = pd.to_datetime(eq["ts"], utc=True)
    eq = eq.set_index("ts")["eq"].astype(float)
    out, t = [], pd.Timestamp(t0)
    while t + pd.DateOffset(months=3) <= pd.Timestamp(t1) + pd.Timedelta(days=1):
        a, b = t, t + pd.DateOffset(months=3)
        seg = eq[(eq.index >= a) & (eq.index < b)]
        prev = eq[eq.index < a]
        e0 = float(prev.iloc[-1]) if len(prev) else (float(seg.iloc[0]) if len(seg) else None)
        if len(seg) and e0:
            out.append((float(seg.iloc[-1]) / e0 - 1.0) * 100.0)
        t = b
    return out


def mstat(res):
    m = ea.metrics(res)
    return {k: m.get(k) for k in ("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades",
                                  "win_rate_pct", "liquidations")}


def fnum(x, nd=3):
    if x is None:
        return None
    if isinstance(x, float):
        if math.isinf(x) or math.isnan(x):
            return None
        return round(x, nd)
    return x


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)


def load(path):
    with open(path) as f:
        return json.load(f)
