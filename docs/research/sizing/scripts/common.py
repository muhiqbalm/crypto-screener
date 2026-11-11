"""Shared setup for the position-sizing research (2026-11-11). DEVELOPMENT data only
unless a function says otherwise. Runs on the VPS under /tmp/sizing with the bmtm-v2
interpreter and the engine of branch feat/sizing-research (sizing_mode etc.):

    cd /tmp/sizing/crypto-screener/docs/research/sizing/scripts
    nice -n 10 /root/bmtm-v2/venv/bin/python <script>.py
"""
import json
import math
import os
import sys
from dataclasses import replace

EXP = os.environ.get("SIZING_EXP", "/tmp/sizing/exp")
os.environ.setdefault("LAB_ENGINE_PATH", "/tmp/sizing/engine")
os.environ["LAB_DATA_DIR"] = f"{EXP}/data"
os.environ["LAB_DB_PATH"] = f"{EXP}/lab.db"
os.environ["LAB_ARTIFACTS_DIR"] = f"{EXP}/artifacts"
os.environ["LAB_DATA_OFFLINE"] = "1"
os.environ["LAB_TELEGRAM_ENABLED"] = "0"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
REPO = os.environ.get("SIZING_REPO", "/tmp/sizing/crypto-screener")
sys.path.insert(0, REPO)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.lab import data_cache as dc  # noqa: E402
from src.lab import engine_adapter as ea  # noqa: E402
from src.lab import honesty  # noqa: E402
from src.lab.templates import rosyade_family as T  # noqa: E402

TF = "4h"
START, END = "2020-01-01", "2026-11-09"          # same range as the eth-v2 / MTF research
COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}
BIG_WARMUP = 1600
OUT = f"{EXP}/out"
os.makedirs(OUT, exist_ok=True)

# Holdout starts used by every earlier look (MTF + eth-v2 research). Dev = strictly before.
HS = {"ETHUSDT": "2025-07-06T04:00:00Z", "BTCUSDT": "2025-07-06T04:00:00Z", "SOLUSDT": "2025-08-26T12:00:00Z"}


def _manifest():
    with open(os.path.join(REPO, "ops", "lab_presets_seed.json")) as f:
        return {e["name"]: e for e in json.load(f)["presets"]}


def presets():
    """{name: (symbol, full validated params)} of the four paper presets (production params)."""
    m = _manifest()
    out = {}
    for name in ("4H-ETH-Basic", "4H-ETH-v2", "4H-BTC-Opt", "4H-SOL-Opt"):
        e = m[name]
        p = T.defaults() if e.get("live_reference") else T.validate_params(e["params"])
        out[name] = (e["symbol"], p)
    return out


# ── sizing rules (engine StrategyConfig fields) ───────────────────────────
def rule_fields(rule: dict) -> dict:
    """rule = {"family": fixed|risk|vt, "level": x, ["dd": pct, "dd_mult": m], ["lookback": n]}."""
    f = rule["family"]
    out = {}
    if f == "fixed":                       # k x equity notional via margin% at the template's 4x leverage
        out = {"sizing_mode": "margin", "portfolio_risk": 25.0 * float(rule["level"])}
    elif f == "risk":
        out = {"sizing_mode": "risk", "risk_per_trade_pct": float(rule["level"]),
               "max_notional_mult": float(rule.get("cap", 2.0))}
    elif f == "vt":
        out = {"sizing_mode": "vol_target", "vol_target_pct": float(rule["level"]),
               "vol_lookback": int(rule.get("lookback", 60)), "max_notional_mult": float(rule.get("cap", 2.0))}
    else:
        raise ValueError(f)
    if rule.get("dd"):
        out.update(dd_derisk_pct=float(rule["dd"]), dd_derisk_mult=float(rule.get("dd_mult", 0.5)))
    return out


def rule_name(rule: dict) -> str:
    f, x = rule["family"], rule["level"]
    s = {"fixed": f"{x:g}x notional", "risk": f"{x:g}% risk/trade", "vt": f"VT {x:g}%"}[f]
    if f == "vt" and rule.get("lookback", 60) != 60:
        s += f" lb{rule['lookback']}"
    if rule.get("dd"):
        s += f" +DD{rule['dd']:g}/{rule.get('dd_mult', 0.5):g}"
    return s


_frames = {}


def frame(symbol):
    """(full_df, dev_df) with BIG_WARMUP rows of head-room; dev_df ends before HS[symbol]."""
    if symbol not in _frames:
        ohlcv, fund = dc.ensure(symbol, TF, funding=True, offline=True)
        df, _, _, _ = ea.prepare_frame(ohlcv, fund, TF, START, END, BIG_WARMUP, True)
        dev = df[df["timestamp"] < pd.Timestamp(HS[symbol])].reset_index(drop=True)
        honesty.assert_dev_only(dev["timestamp"].tail(1), HS[symbol])
        _frames[symbol] = (df, dev)
    return _frames[symbol]


def configs(params, rule=None, cost_mult=1.0):
    cfg, ecfg = ea.build_configs(params, TF, COSTS)
    if rule is not None:
        cfg = replace(cfg, **rule_fields(rule))
    if cost_mult != 1.0:
        ecfg = ea.scaled_costs(ecfg, cost_mult)
    return cfg, ecfg


def run(df, params, rule=None, cost_mult=1.0, t0=None, t1=None):
    """Backtest over [t0, t1) (default: whole df after BIG_WARMUP). Indicators use the full warm-up."""
    cfg, ecfg = configs(params, rule, cost_mult)
    w = ecfg.warmup_period
    if t0 is None:
        t0 = df["timestamp"].iloc[BIG_WARMUP]
    sl, pre = ea.window(df, t0, t1, BIG_WARMUP)
    if pre < w:
        raise ValueError("not enough warm-up")
    res, _ = ea.run(sl, cfg, ecfg, warmup=pre)
    return res


def fnum(x, nd=3):
    if x is None:
        return None
    x = float(x)
    if math.isinf(x) or math.isnan(x):
        return None
    return round(x, nd)


def cagr(res):
    eq = res.equity_curve
    if len(eq) < 2:
        return None
    t0, t1 = pd.Timestamp(eq[0][0]), pd.Timestamp(eq[-1][0])
    yrs = (t1 - t0).total_seconds() / (365.25 * 86400)
    e0, e1 = 100.0, float(eq[-1][1])
    if e1 <= 0 or yrs <= 0:
        return -100.0
    return ((e1 / e0) ** (1 / yrs) - 1) * 100


def unit_trades(res):
    """Per trade: (return per 1x-equity notional, notional multiple at entry). ROE = r * m."""
    out = []
    for t in res.trades:
        eq = t.equity_at_entry
        notional = t.quantity * t.entry_price
        m = notional / eq if eq > 0 else 0.0
        roe = (t.return_on_equity_pct / 100.0) if t.return_on_equity_pct else (t.net_pnl / eq if eq > 0 else 0.0)
        out.append((roe / m if m > 0 else 0.0, m))
    return np.array(out, dtype=float).reshape(-1, 2)


def mc_rule(res, dd_pct=0.0, dd_mult=0.5, n=1000, seed=42, ruin=50.0):
    """Trade-order Monte Carlo that RE-APPLIES the drawdown de-risk rule along every reshuffled path
    (a plain ROE reshuffle would freeze the historical de-risk decisions). dd_pct=0 -> equals the
    engine's monte_carlo_trades up to the -100% floor."""
    ut = unit_trades(res)
    rng = np.random.RandomState(seed)
    if len(ut) == 0:
        return {"dd_p95": 0.0, "dd_p99": 0.0, "p_dd50": 0.0, "p_dd30": 0.0}
    dds = np.empty(n)
    base_m = ut[:, 1].copy()
    if dd_pct:
        # the engine's sizes already include the historical de-risk; undo it to get the base size
        eq_path = np.cumprod(np.r_[1.0, 1.0 + ut[:-1, 0] * ut[:-1, 1]])
        peak = np.maximum.accumulate(eq_path)
        derisked = eq_path < peak * (1 - dd_pct / 100.0)
        base_m = np.where(derisked, base_m / dd_mult, base_m)
    for k in range(n):
        idx = rng.permutation(len(ut))
        r, m = ut[idx, 0], base_m[idx]
        eq, peak, mdd = 1.0, 1.0, 0.0
        for j in range(len(r)):
            mm = m[j] * (dd_mult if dd_pct and eq < peak * (1 - dd_pct / 100.0) else 1.0)
            eq *= max(1.0 + r[j] * mm, 0.0)
            peak = max(peak, eq)
            mdd = min(mdd, (eq - peak) / peak * 100 if peak > 0 else -100.0)
        dds[k] = mdd
    return {"dd_p95": float(np.percentile(dds, 5)), "dd_p99": float(np.percentile(dds, 1)),
            "p_dd50": float(np.mean(dds <= -ruin)), "p_dd30": float(np.mean(dds <= -30.0))}


def stats(res, res2x=None, rule=None):
    m = ea.metrics(res)
    mc = ea.monte_carlo(res)
    ut = unit_trades(res)
    out = {
        "trades": m["trades"], "net_pct": fnum(m["net_return_pct"], 1), "cagr_pct": fnum(cagr(res), 2),
        "max_dd_pct": fnum(m["max_dd_pct"], 2), "max_dd_intrabar_pct": fnum(m["max_dd_intrabar_pct"], 2),
        "sharpe": fnum(m["sharpe"], 3), "pf": fnum(m["profit_factor"], 3), "liquidations": m["liquidations"],
        "mc_dd95": fnum(mc["dd_p95"], 2), "mc_dd99": fnum(mc["dd_p99"], 2),
        "p_dd50": fnum(mc["prob_dd_beyond_50pct"], 4),
        "avg_notional_x": fnum(ut[:, 1].mean() if len(ut) else 0, 3),
        "max_notional_x": fnum(ut[:, 1].max() if len(ut) else 0, 3),
        "worst_trade_roe_pct": fnum(min((t.return_on_equity_pct for t in res.trades), default=0), 2),
    }
    c = cagr(res)
    out["calmar"] = fnum(c / abs(m["max_dd_pct"]) if m["max_dd_pct"] else None, 3)
    out["mc_calmar"] = fnum(c / abs(mc["dd_p95"]) if mc["dd_p95"] else None, 3)
    if rule and rule.get("dd"):
        mr = mc_rule(res, rule["dd"], rule.get("dd_mult", 0.5))
        out.update(mc_dd95=fnum(mr["dd_p95"], 2), mc_dd99=fnum(mr["dd_p99"], 2), p_dd50=fnum(mr["p_dd50"], 4),
                   mc_note="rule-aware MC (de-risk re-applied on each reshuffle)")
        out["mc_calmar"] = fnum(c / abs(mr["dd_p95"]) if mr["dd_p95"] else None, 3)
    if res2x is not None:
        m2 = ea.metrics(res2x)
        out.update(net2x_pct=fnum(m2["net_return_pct"], 1), sharpe2x=fnum(m2["sharpe"], 3),
                   cagr2x_pct=fnum(cagr(res2x), 2))
    return out


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)


def load(path):
    with open(path) as f:
        return json.load(f)
