"""The ONLY module that imports bmtm-v2 (backtest_engine).

Runs inside the engine child process (bmtm-v2 venv). The engine location is
LAB_ENGINE_PATH; it is put on sys.path lazily so importing this module in the
API process is harmless (the API never calls these functions).
"""
from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from .data_cache import TF_SECONDS
from .settings import get_lab_settings
from .templates import rosyade_family as T

HTF_SECONDS = {**TF_SECONDS, "1w": 7 * 86400}
_TF_RANK = {tf: sec for tf, sec in HTF_SECONDS.items()}
# TradingView input.timeframe spellings -> lab timeframe
_TV_TF = {"15": "15m", "30": "30m", "60": "1h", "240": "4h", "D": "1d", "1D": "1d", "W": "1w", "1W": "1w"}
MAX_EQUITY_POINTS = 4000


def _ensure_path() -> None:
    p = str(Path(get_lab_settings().engine_path).resolve())
    if p not in sys.path:
        sys.path.insert(0, p)


@lru_cache(maxsize=1)
def engine_commit() -> str:
    path = get_lab_settings().engine_path
    try:
        out = subprocess.run(["git", "-c", "safe.directory=*", "-C", path, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        sha = out.stdout.strip()
        dirty = subprocess.run(["git", "-c", "safe.directory=*", "-C", path, "status", "--porcelain",
                                "--untracked-files=no"], capture_output=True, text=True, timeout=10)
        return sha + ("-dirty" if dirty.stdout.strip() else "") if sha else "unknown"
    except Exception:
        return "unknown"


def _engine():
    _ensure_path()
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    from backtest_engine.config.strategy_config import StrategyConfig
    from backtest_engine.config.engine_config import EngineConfig
    from backtest_engine.indicators.precompute import precompute_all_indicators
    from backtest_engine.engine.backtest_loop import run_backtest
    from backtest_engine.validation.pipeline import compute_sharpe
    from backtest_engine.validation import robustness
    from backtest_engine.data.gap_handler import detect_and_mark_gaps
    from backtest_engine.data.funding import attach_funding
    return {
        "StrategyConfig": StrategyConfig, "EngineConfig": EngineConfig,
        "precompute": precompute_all_indicators, "run_backtest": run_backtest,
        "sharpe": compute_sharpe, "robustness": robustness,
        "gaps": detect_and_mark_gaps, "attach_funding": attach_funding,
    }


# ── config translation ───────────────────────────────────────────────────

def _htf(value: str, tf: str) -> str:
    if value in (None, "", "same"):
        return tf
    v = _TV_TF.get(value, value)
    return v if _TF_RANK.get(v, 0) > _TF_RANK[tf] else tf


HTF_WARMUP_MARGIN = 1.25  # covers sensitivity / optimiser nudges of ema_htf_len


def effective_warmup(p: dict, tf: str) -> int:
    """Warm-up bars on the base timeframe. With a true higher-timeframe EMA
    filter (e.g. EMA-194 on 4H while trading 15m) the engine needs ~len closed
    HTF bars before the filter is defined, i.e. len x (HTF/TF) base bars."""
    w = int(p["warmup_bars"])
    htf = _htf(p.get("ema_htf_tf"), tf)
    if p.get("use_ema_htf") and htf != tf:
        ratio = HTF_SECONDS[htf] / TF_SECONDS[tf]
        w = max(w, int(math.ceil((p["ema_htf_len"] * HTF_WARMUP_MARGIN + 1) * ratio)))
    return w


def build_configs(params: dict, tf: str, costs: dict):
    E = _engine()
    p = T.validate_params(params)
    T.validate_for_timeframe(p, tf)
    strat = {k: v for k, v in p.items() if k not in T.ENGINE_KEYS}
    if not T.is_mtf(p):  # plain runs pass exactly the pre-MTF StrategyConfig fields
        strat = {k: v for k, v in strat.items() if k not in T.MTF_KEYS}
    strat["ema_htf_tf"] = _htf(strat["ema_htf_tf"], tf)
    strat["dcb_htf_input"] = _htf(strat["dcb_htf_input"], tf)
    strat["base_timeframe"] = tf
    strat["initial_capital"] = 100.0
    cfg = E["StrategyConfig"](**strat)
    ecfg = E["EngineConfig"](
        warmup_period=effective_warmup(p, tf),
        commission_pct=float(costs.get("commission_pct", 0.05)),
        slippage_pct=float(costs.get("slippage_pct", 0.05)),
        maintenance_margin_pct=float(p["maintenance_margin_pct"]),
        use_liquidation=True,
    )
    if T.is_mtf(p):
        ecfg = replace(ecfg, maker_commission_pct=float(p["maker_fee_pct"]))
    return cfg, ecfg


def scaled_costs(ecfg, mult: float, **kw):
    """EngineConfig with commission, slippage and (if set) the maker fee x mult."""
    extra = {}
    if getattr(ecfg, "maker_commission_pct", None) is not None:
        extra["maker_commission_pct"] = ecfg.maker_commission_pct * mult
    return replace(ecfg, commission_pct=ecfg.commission_pct * mult, slippage_pct=ecfg.slippage_pct * mult,
                   slippage_bps=None, **extra, **kw)


def attach_entry_bars(ohlcv, ltf_ohlcv, tf: str, entry_tf: str):
    """Embed the lower-TF (entry timeframe) OHLC sub-bars in the signal-TF rows."""
    _ensure_path()
    from backtest_engine.data.ltf_bars import attach_ltf_bars
    return attach_ltf_bars(ohlcv, ltf_ohlcv, tf, entry_tf)


# ── data ─────────────────────────────────────────────────────────────────

def prepare_frame(ohlcv, funding_df, tf: str, start: Optional[str], end: Optional[str],
                  warmup: int, use_funding: bool):
    """Slice [start-warmup, end), mark gaps, attach funding.

    Returns (raw_df, eval_start_ts, eval_end_ts, warmup_effective).
    """
    import pandas as pd
    E = _engine()
    df = ohlcv.copy()
    if start:
        i0 = int(df["timestamp"].searchsorted(pd.Timestamp(start, tz="UTC")))
        df = df.iloc[max(0, i0 - warmup):]
    if end:
        df = df[df["timestamp"] < pd.Timestamp(end, tz="UTC")]
    df = df.reset_index(drop=True)
    if len(df) <= warmup + 50:
        raise ValueError(f"not enough bars ({len(df)}) for warm-up {warmup} + 50")
    df = E["gaps"](df, expected_interval_s=TF_SECONDS[tf])
    if use_funding and funding_df is not None and len(funding_df):
        df = E["attach_funding"](df, funding_df)
    eval_start = df["timestamp"].iloc[warmup]
    eval_end = df["timestamp"].iloc[-1] + pd.Timedelta(seconds=TF_SECONDS[tf])
    return df, eval_start, eval_end, warmup


def window(df, t0, t1, warmup: int):
    """Rows with t0 <= ts < t1 plus up to `warmup` preceding rows (indicator warm-up only)."""
    import pandas as pd
    ts = df["timestamp"]
    i0 = int(ts.searchsorted(pd.Timestamp(t0))) if t0 is not None else 0
    i1 = int(ts.searchsorted(pd.Timestamp(t1))) if t1 is not None else len(df)
    pre = min(i0, warmup)
    sl = df.iloc[i0 - pre:i1].reset_index(drop=True)
    return sl, pre


# ── backtest ─────────────────────────────────────────────────────────────

def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return v


def run(df, cfg, ecfg, warmup: Optional[int] = None, indicators=None):
    E = _engine()
    ec = ecfg if warmup is None else replace(ecfg, warmup_period=warmup)
    ind = indicators if indicators is not None else E["precompute"](df, cfg)
    return E["run_backtest"](ind, cfg, ec), ind


def metrics(res) -> dict:
    E = _engine()
    trades = res.trades
    gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = -sum(t.net_pnl for t in trades if t.net_pnl <= 0)
    pf = res.profit_factor
    return {
        "net_return_pct": _f(res.net_profit_pct),
        "profit_factor": None if pf == float("inf") else _f(pf),
        "max_dd_pct": _f(res.max_drawdown_pct),
        "max_dd_intrabar_pct": _f(res.max_drawdown_intrabar_pct),
        "trades": int(res.total_trades),
        "win_rate_pct": _f(res.win_rate),
        "sharpe": _f(E["sharpe"](res.equity_curve)),
        "liquidations": int(res.liquidations),
        "funding_paid": _f(res.total_funding_paid),
        "fees_paid": _f(sum(t.fees for t in trades)),
        "final_equity": _f(res.final_equity),
        "gross_profit": _f(gross_win),
        "gross_loss": _f(gross_loss),
        "account_blown": bool(res.account_blown),
        "longs": sum(1 for t in trades if t.direction == "long"),
        "shorts": sum(1 for t in trades if t.direction == "short"),
        **({"entry": _entry_stats(res.entry_stats)} if getattr(res, "entry_stats", None) else {}),
    }


def _entry_stats(st: dict) -> dict:
    return {k: (_f(v) if isinstance(v, float) else v) for k, v in st.items()}


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    try:
        import pandas as pd
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ts)


def trades_out(res) -> list[dict]:
    return [{
        "entry_time": _iso(t.entry_timestamp),
        "exit_time": _iso(t.exit_timestamp),
        "side": t.direction,
        "entry_price": _f(t.entry_price),
        "exit_price": _f(t.exit_price),
        "pnl_pct": _f(t.net_pnl_pct),
        "return_on_equity_pct": _f(t.return_on_equity_pct),
        "exit_reason": t.exit_reason,
        "fees": _f(t.fees),
        "funding": _f(t.funding),
        "bars_held": int(t.bars_held),
        **({"signal_price": _f(t.signal_price), "entry_kind": t.entry_kind}
           if getattr(t, "entry_kind", "bar_close") != "bar_close" else {}),
    } for t in res.trades]


def equity_out(res, holdout_start=None, oos_windows=None) -> list[dict]:
    """[{t, equity, segment}] downsampled to MAX_EQUITY_POINTS (keeps last point)."""
    import pandas as pd
    hs = pd.Timestamp(holdout_start) if holdout_start else None
    wins = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in (oos_windows or [])]
    eq = res.equity_curve
    n = len(eq)
    step = max(1, math.ceil(n / MAX_EQUITY_POINTS))
    out = []
    for i in list(range(0, n, step)) + ([n - 1] if n and (n - 1) % step else []):
        ts, val = eq[i]
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        seg = "is"
        if hs is not None and t >= hs:
            seg = "holdout"
        elif any(a <= t < b for a, b in wins):
            seg = "oos"
        out.append({"t": _iso(t), "equity": _f(val), "segment": seg})
    return out


def cost_profile(df, warmup: int, cfg, ecfg, m_net: dict, indicators=None) -> dict:
    """How much of the edge the costs eat on this timeframe: the same window
    re-run with zero commission/slippage, plus the round-trip cost relative to
    the average bar range (the lower the timeframe, the larger this burden)."""
    zero = scaled_costs(ecfg, 0.0, warmup_period=warmup)
    res0, _ = run(df, cfg, zero, indicators=indicators)
    m0 = metrics(res0)
    ev = df.iloc[warmup:]
    rng = ((ev["high"] - ev["low"]) / ev["close"]).mean() * 100.0 if len(ev) else None
    rt = 2.0 * (float(ecfg.commission_pct) + float(ecfg.slippage_pct))
    days = (ev["timestamp"].iloc[-1] - ev["timestamp"].iloc[0]).total_seconds() / 86400.0 if len(ev) > 1 else 0
    net, gross = m_net.get("net_return_pct"), m0.get("net_return_pct")
    return {
        "round_trip_cost_pct": _f(rt),
        "avg_bar_range_pct": _f(rng),
        "cost_to_bar_range": _f(rt / rng) if rng else None,
        "zero_cost_net_return_pct": _f(gross),
        "zero_cost_profit_factor": m0.get("profit_factor"),
        "cost_drag_pct": _f(gross - net) if gross is not None and net is not None else None,
        "fees_paid": m_net.get("fees_paid"),
        "trades_per_month": _f(m_net["trades"] / (days / 30.44)) if days > 0 else None,
    }


# ── robustness ───────────────────────────────────────────────────────────

def monte_carlo(res) -> dict:
    E = _engine()
    mc = E["robustness"].monte_carlo_trades(res)
    return {"dd_p95": _f(mc.dd_p95), "dd_p99": _f(mc.dd_p99), "prob_dd_beyond_50pct": _f(mc.prob_ruin),
            "n_simulations": mc.n_simulations, "original_trade_path_dd": _f(mc.original_max_dd)}


SENS_STEPS = (-0.2, -0.1, 0.1, 0.2)


def sensitivity_names(cfg) -> list[str]:
    rb = _engine()["robustness"]
    return [g[0] for g in rb.build_sensitivity_grid(cfg, rel_steps=SENS_STEPS)]


def sensitivity(ind, cfg, ecfg, progress: Optional[Callable] = None) -> dict:
    E = _engine()
    rb = E["robustness"]
    grid = rb.build_sensitivity_grid(cfg, rel_steps=SENS_STEPS)
    rows = []
    for k, item in enumerate(grid):
        r = rb.parameter_sensitivity(ind, cfg, ecfg, params=[item])[0]
        rows.append({
            "param": r.param_name, "base": r.base_value,
            "stability": _f(r.stability_score), "profitable_fraction": _f(r.profitable_fraction),
            "fragile": bool(r.stability_score <= rb.STABILITY_THRESHOLD),
            "variations": [{"value": v[0], "net_pct": _f(v[1]), "pf": _f(v[3]), "trades": int(v[4])}
                           for v in r.variations],
        })
        if progress:
            progress(k + 1, len(grid))
    return {"params": rows, "unstable": sum(1 for r in rows if r["fragile"]),
            "threshold": rb.STABILITY_THRESHOLD, "steps": list(SENS_STEPS)}


# ── optimisation ─────────────────────────────────────────────────────────

OBJECTIVE = ("sharpe x share of profitable sub-periods (4 equal time slices) x min(1, trades/min_trades); "
             "-1 if max DD deeper than -50%; liquidation/blown -> -1e9. Evaluated on the development "
             "data only (never the holdout).")
N_SEGMENTS = 4


def segment_returns(res, n: int = N_SEGMENTS) -> list[float]:
    """Return (%) of each of n equal time slices of the mark-to-market equity curve."""
    eq = res.equity_curve
    if len(eq) < n + 1:
        return []
    idx = [round(i * (len(eq) - 1) / n) for i in range(n + 1)]
    out = []
    for a, b in zip(idx[:-1], idx[1:]):
        e0, e1 = float(eq[a][1]), float(eq[b][1])
        out.append((e1 / e0 - 1.0) * 100.0 if e0 > 0 else -100.0)
    return out


def robust_score(m: dict, segs: list[float], min_trades: int) -> float:
    if m.get("liquidations", 0) > 0 or m.get("account_blown") or m.get("net_return_pct") is None:
        return -1e9
    sharpe = m.get("sharpe") or 0.0
    trade_f = min(1.0, m["trades"] / max(1, min_trades))
    pos_f = (sum(1 for x in segs if x > 0) / len(segs)) if segs else 0.0
    if sharpe > 0:
        score = sharpe * pos_f * trade_f
    else:
        score = sharpe - (1.0 - trade_f)
    if (m.get("max_dd_pct") or 0.0) < -50.0:
        score -= 1.0
    return float(score)


def objective_score(m: dict, min_trades: int) -> float:  # kept for callers without an equity curve
    return robust_score(m, [], min_trades)


def _suggest(trial, spec: dict, base):
    if spec["type"] == "int":
        return trial.suggest_int(spec["key"], int(spec["min"]), int(spec["max"]), step=int(spec["step"] or 1))
    lo, hi, st = float(spec["min"]), float(spec["max"]), spec["step"]
    if st:
        hi = lo + math.floor((hi - lo) / st + 1e-9) * st
        return round(trial.suggest_float(spec["key"], lo, hi, step=float(st)), 6)
    return trial.suggest_float(spec["key"], lo, hi)


def _clamp_to_spec(v, spec):
    v = min(max(v, spec["min"]), spec["max"])
    return int(round(v)) if spec["type"] == "int" else float(v)


def optimize(df, warmup: int, base_params: dict, tf: str, costs: dict, n_trials: int,
             holdout_start, seed: int = 42, progress: Optional[Callable] = None,
             min_trades: int = 10, specs: Optional[list[dict]] = None, top_n: int = 5) -> dict:
    """Optuna TPE over `specs` (default: all tunables) on `df`, which must be
    development data only (asserted against the locked holdout). Other params stay
    at base_params. Objective: robust_score (see OBJECTIVE)."""
    import optuna
    from .honesty import assert_dev_only
    assert_dev_only([df["timestamp"].iloc[-1]], holdout_start)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    specs = specs or T.tunable_params()
    base = T.validate_params(base_params)
    keys = [s["key"] for s in specs]

    def obj(trial):
        p = dict(base)
        for s in specs:
            p[s["key"]] = _suggest(trial, s, base[s["key"]])
        try:
            p = T.validate_params(p)
            cfg, ecfg = build_configs(p, tf, costs)
            res, _ = run(df, cfg, ecfg, warmup=warmup)
            m = metrics(res)
            segs = segment_returns(res)
            score = robust_score(m, segs, min_trades)
            trial.set_user_attr("m", {**{k: m[k] for k in ("net_return_pct", "profit_factor", "max_dd_pct",
                                                           "trades", "sharpe")},
                                      "profitable_segments": sum(1 for x in segs if x > 0),
                                      "segments": len(segs)})
        except Exception as e:  # noqa: BLE001
            trial.set_user_attr("error", f"{type(e).__name__}: {e}"[:200])
            score = -1e9
        if progress:
            progress(trial.number + 1, n_trials)
        return score

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial({s["key"]: _clamp_to_spec(base[s["key"]], s) for s in specs})  # start near given params
    study.optimize(obj, n_trials=n_trials, show_progress_bar=False)

    def _params(t):
        return {k: (round(v, 8) if isinstance(v, float) else v) for k, v in t.params.items() if k in keys}

    done = [t for t in study.trials if t.value is not None]
    ranked = sorted(done, key=lambda t: t.value, reverse=True)
    top = [{"rank": i + 1, "trial": t.number, "score": _f(t.value) if t.value > -1e8 else None,
            "params": _params(t), "metrics": t.user_attrs.get("m"), "error": t.user_attrs.get("error")}
           for i, t in enumerate(ranked[:top_n])]
    best = dict(base)
    best.update(_params(study.best_trial))
    best = T.validate_params(best)
    return {"best_params": best, "best_score": _f(study.best_value) if study.best_value > -1e8 else None,
            "best_metrics": study.best_trial.user_attrs.get("m"), "trials": len(done), "top_trials": top,
            "searched": [{"key": s["key"], "min": s["min"], "max": s["max"]} for s in specs],
            "objective": OBJECTIVE, "min_trades": min_trades}
