"""Universal v0 Lab run (engine child process). Same honesty rules as single-coin runs:

  * locked holdout per (universal_v0, UNIVERSE, 4h): last 20% of the evaluated range,
    set on first use, never moved; every holdout evaluation increments `touches`
  * everything that chooses parameters (optimizer, walk-forward, sensitivity) only sees a
    panel physically cut at the holdout start
  * walk-forward: rolling train 12m / test 3m windows on the development segment
    (validate: fixed params; optimize: params re-optimised on every train window)
  * Monte Carlo: stationary block bootstrap (mean block 20 days) of the full-range daily
    portfolio returns, 1000 paths -> 95th-percentile drawdown. Trade reshuffling (used for
    single-coin runs) is not valid for a portfolio with overlapping positions.
  * cost stress: holdout re-run with 2x commission + slippage
  * sensitivity: each tunable param +-10/20% on the development segment, same stability
    score formula as the engine (log-growth dispersion x profitable share, fragile <= 0.5)
  * verdict: the same HONESTY_VERSION checks/thresholds as every other Lab run
"""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

from .. import db as labdb
from .. import honesty
from . import BAR_TF, TEMPLATE_ID, UNIVERSE_SYMBOL
from . import backtest as B
from . import params as P
from . import strategy as S

MC_SIMS = 1000
MC_BLOCK_DAYS = 20
SENS_STEPS = (-0.2, -0.1, 0.1, 0.2)
STABILITY_THRESHOLD = 0.5
SENS_PARAMS = ("top_n", "mom_short_days", "mom_mid_days", "mom_long_days", "vol_days", "trend_ema_days",
               "target_vol_pct", "min_trade_pct")
OBJECTIVE = ("sharpe x share of profitable sub-periods (4 equal slices) x min(1, trades/min_trades); "
             "-1 if max DD deeper than -50%; blown -> -1e9. Development data only (never the holdout).")


# ── data ─────────────────────────────────────────────────────────────────

def universe_symbols(params: dict) -> list[str]:
    from ..data_cache import cached_datasets
    if params.get("symbols"):
        return list(params["symbols"])
    if params.get("universe_mode") == "liquidity":
        from . import pit_data
        return pit_data.pit_symbols(pit_data.default_dir(), BAR_TF)
    return sorted({v["symbol"] for v in cached_datasets().values() if v["timeframe"] == BAR_TF})


def load_universe_panel(params: dict, funding: bool = True, refresh: bool = False, offline: bool = True,
                        progress: Optional[Callable] = None, end=None) -> S.Panel:
    """Panel for a Lab run. universe_mode=liquidity reads the separate point-in-time directory
    (delisted coins included) and never refreshes into the main cache; static = load_panel."""
    if params.get("universe_mode") == "liquidity":
        from . import pit_data
        d = pit_data.default_dir()
        if progress:
            progress("data", 0, 1)
        ohlcv, fund = pit_data.load(d, params.get("symbols") or None, BAR_TF, funding=funding)
        if not ohlcv:
            raise ValueError(f"no point-in-time data in {d} (run python -m src.lab.universal.pit_data)")
        return S.build_panel(ohlcv, fund if funding else None, end=end)
    return load_panel(universe_symbols(params), funding=funding, refresh=refresh, offline=offline,
                      progress=progress, end=end)


def load_panel(symbols: list[str], funding: bool = True, refresh: bool = False, offline: bool = True,
               progress: Optional[Callable] = None, end=None) -> S.Panel:
    from .. import data_cache as dc
    ohlcv, fund = {}, {}
    for k, s in enumerate(symbols):
        if progress:
            progress("data", k, len(symbols))
        if refresh:
            try:
                o, f = dc.ensure(s, BAR_TF, funding=funding, offline=offline, max_stale_bars=0)
            except Exception as e:  # noqa: BLE001 - one bad coin must not kill the portfolio
                print(f"data refresh failed for {s}: {e}")
                o, f = dc.load_ohlcv(s, BAR_TF), (dc.load_funding(s) if funding else None)
        else:
            o, f = dc.load_ohlcv(s, BAR_TF), (dc.load_funding(s) if funding else None)
        if o is not None and len(o):
            ohlcv[s] = o
            if f is not None:
                fund[s] = f
    if not ohlcv:
        raise ValueError("no cached 4h data for the selected universe")
    return S.build_panel(ohlcv, fund if funding else None, end=end)


def bar_index(panel: S.Panel, when, side: str = "left") -> int:
    import pandas as pd
    t = pd.Timestamp(when)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return int(panel.ts.searchsorted(t, side=side))


def eval_range(panel: S.Panel, feat: S.Features, p: dict, start: Optional[str], end: Optional[str]) -> tuple[int, int]:
    first = S.first_tradable_index(feat, p)
    a = first if not start else max(first, bar_index(panel, start))
    last = S.last_complete_index(panel)
    b = last if not end else min(last, bar_index(panel, end, "right") - 1)
    if b - a < S.BARS_PER_DAY * 90:
        raise ValueError("evaluation range shorter than 90 days")
    return a, b


# ── one evaluation ───────────────────────────────────────────────────────

def run_segment(panel: S.Panel, p: dict, costs: dict, a: int, b: int, feat: Optional[S.Features] = None):
    feat = feat or S.compute_features(panel, p)
    sim = B.simulate(panel, feat, p, costs, a, b)
    return sim, B.metrics(sim, panel), feat


def segment_returns(sim: B.SimResult, n: int = 4) -> list[float]:
    eq = np.concatenate([[sim.initial], sim.equity])
    cuts = np.linspace(0, len(eq) - 1, n + 1).astype(int)
    return [float(eq[cuts[i + 1]] / eq[cuts[i]] - 1.0) if eq[cuts[i]] > 0 else -1.0 for i in range(n)]


def robust_score(m: dict, segs: list[float], min_trades: int) -> float:
    if m.get("account_blown"):
        return -1e9
    if (m.get("max_dd_pct") or 0) < -50:
        return -1.0
    sh = m.get("sharpe")
    if sh is None:
        return -1.0
    prof = sum(1 for s in segs if s > 0) / max(1, len(segs))
    return float(sh * prof * min(1.0, (m.get("trades") or 0) / max(1, min_trades)))


# ── Monte Carlo ──────────────────────────────────────────────────────────

def monte_carlo(daily: np.ndarray, n_sims: int = MC_SIMS, block: int = MC_BLOCK_DAYS, seed: int = 42) -> dict:
    """Stationary block bootstrap of daily returns -> drawdown distribution."""
    r = np.asarray(daily, dtype=float)
    n = len(r)
    if n < 30:
        return {"dd_p95": None, "dd_p99": None, "prob_dd_beyond_50pct": None, "n_simulations": 0,
                "method": "block_bootstrap_daily", "original_dd": None}
    rng = np.random.default_rng(seed)
    p_new = 1.0 / block
    idx = np.empty((n_sims, n), dtype=int)
    idx[:, 0] = rng.integers(0, n, n_sims)
    jumps = rng.random((n_sims, n)) < p_new
    fresh = rng.integers(0, n, (n_sims, n))
    for k in range(1, n):
        idx[:, k] = np.where(jumps[:, k], fresh[:, k], (idx[:, k - 1] + 1) % n)
    paths = np.cumprod(1.0 + np.maximum(r[idx], -1.0), axis=1)
    paths = np.concatenate([np.ones((n_sims, 1)), paths], axis=1)
    peak = np.maximum.accumulate(paths, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.nan_to_num((paths - peak) / peak * 100.0, nan=-100.0).min(axis=1)
    orig = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    return {"dd_p95": float(np.percentile(dd, 5)), "dd_p99": float(np.percentile(dd, 1)),
            "prob_dd_beyond_50pct": float(np.mean(dd <= -50.0)), "n_simulations": n_sims,
            "median_dd": float(np.median(dd)), "block_days": block, "method": "block_bootstrap_daily",
            "original_dd": B.max_drawdown_pct(orig)}


# ── sensitivity ──────────────────────────────────────────────────────────

def stability_score(base_net: Optional[float], nets: list[float]) -> tuple[float, float]:
    """Same formula as bmtm-v2 backtest_engine.validation.robustness.stability_score."""
    v = np.asarray(nets, dtype=float)
    if not len(v):
        return 0.0, 0.0
    prof = float(np.mean(v > 0))
    if base_net is None or base_net <= 0:
        return 0.0, prof
    g = np.log1p(np.maximum(v, -99.99) / 100.0)
    gb = math.log1p(base_net / 100.0)
    disp = float(np.std(g)) / max(abs(gb), 1e-9)
    return float(max(0.0, min(1.0, 1.0 - disp)) * prof), prof


def _vary(spec: dict, base, step: float):
    v = base * (1 + step)
    if spec["type"] == "int":
        v = int(round(v))
        if v == base:
            v = base + (1 if step > 0 else -1)
    v = max(spec["min"], min(spec["max"], v))
    return v


def sensitivity(panel: S.Panel, p: dict, costs: dict, a: int, b: int, base_net: Optional[float],
                progress: Optional[Callable] = None) -> dict:
    rows = []
    for k, key in enumerate(SENS_PARAMS):
        spec = P.PARAM_INDEX[key]
        base = p[key]
        vals = []
        for st in SENS_STEPS:
            v = _vary(spec, base, st)
            if v != base and v not in vals:
                vals.append(v)
        variations = []
        for v in vals:
            q = {**p, key: v}
            try:
                q = P.validate_params({**{kk: vv for kk, vv in q.items() if kk != "symbols"},
                                       "symbols": p.get("symbols") or []})
            except P.ParamError:
                continue
            _, m, _ = run_segment(panel, q, costs, a, b)
            variations.append({"value": v, "net_pct": m["net_return_pct"], "pf": m["profit_factor"],
                               "trades": m["trades"], "sharpe": m["sharpe"]})
        score, prof = stability_score(base_net, [x["net_pct"] or 0.0 for x in variations])
        rows.append({"param": key, "base": base, "stability": score, "profitable_fraction": prof,
                     "fragile": bool(score <= STABILITY_THRESHOLD), "variations": variations})
        if progress:
            progress(k + 1, len(SENS_PARAMS))
    return {"params": rows, "unstable": sum(1 for r in rows if r["fragile"]), "threshold": STABILITY_THRESHOLD,
            "steps": list(SENS_STEPS)}


# ── optimisation ─────────────────────────────────────────────────────────

def optimize(panel: S.Panel, base: dict, costs: dict, a: int, b: int, specs: list[dict], n_trials: int,
             seed: int = 42, min_trades: int = 30, progress: Optional[Callable] = None) -> dict:
    """TPE (optuna, if installed) or seeded random search over `specs` on bars [a, b] only."""
    trials: list[dict] = []
    rng = np.random.default_rng(seed)

    def evaluate(cand: dict) -> float:
        q = {**base, **cand}
        try:
            q = P.validate_params({**{k: v for k, v in q.items() if k != "symbols"},
                                   "symbols": base.get("symbols") or []})
        except P.ParamError as e:
            trials.append({"params": cand, "score": None, "metrics": None, "error": str(e)})
            return -1e9
        sim, m, _ = run_segment(panel, q, costs, a, b)
        segs = segment_returns(sim)
        sc = robust_score(m, segs, min_trades)
        trials.append({"params": cand, "score": sc, "metrics": {
            "net_return_pct": m["net_return_pct"], "profit_factor": m["profit_factor"], "max_dd_pct": m["max_dd_pct"],
            "trades": m["trades"], "sharpe": m["sharpe"], "profitable_segments": sum(1 for s in segs if s > 0),
            "segments": len(segs)}})
        if progress:
            progress(len(trials), n_trials)
        return sc

    def suggest_random(spec):
        if spec["type"] == "int":
            step = int(spec.get("step") or 1)
            return int(rng.integers(int(spec["min"]) // step, int(spec["max"]) // step + 1) * step)
        step = float(spec.get("step") or 0)
        v = float(rng.uniform(spec["min"], spec["max"]))
        return round(round(v / step) * step, 6) if step else v

    try:
        import optuna  # type: ignore
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))

        def obj(trial):
            cand = {}
            for s in specs:
                if s["type"] == "int":
                    cand[s["key"]] = trial.suggest_int(s["key"], int(s["min"]), int(s["max"]),
                                                       step=int(s.get("step") or 1))
                else:
                    cand[s["key"]] = trial.suggest_float(s["key"], float(s["min"]), float(s["max"]),
                                                         step=float(s["step"]) if s.get("step") else None)
            return evaluate(cand)
        study.enqueue_trial({s["key"]: base[s["key"]] for s in specs if s["min"] <= base[s["key"]] <= s["max"]})
        study.optimize(obj, n_trials=n_trials)
        sampler = "optuna-tpe"
    except ImportError:
        evaluate({s["key"]: base[s["key"]] for s in specs})
        while len(trials) < n_trials:
            evaluate({s["key"]: suggest_random(s) for s in specs})
        sampler = "random"
    scored = [t for t in trials if t["score"] is not None]
    scored.sort(key=lambda t: -t["score"])
    best = scored[0] if scored else {"params": {}, "score": None, "metrics": None}
    best_params = {**base, **best["params"]}
    top = [{"rank": i + 1, "trial": trials.index(t), **t} for i, t in enumerate(scored[:10])]
    return {"best_params": best_params, "best_score": best["score"], "best_metrics": best["metrics"],
            "trials": len(trials), "top_trials": top, "sampler": sampler, "objective": OBJECTIVE}


# ── walk-forward ─────────────────────────────────────────────────────────

def wf_windows(panel: S.Panel, a: int, b: int) -> tuple[list[tuple[int, int, int]], int, int]:
    import pandas as pd
    first, last = panel.ts[a], panel.ts[b]
    span_m = (last - first).days / 30.44
    train_m, test_m = (12, 3) if span_m >= 18 else (6, 3)
    out = []
    t = first + pd.DateOffset(months=train_m)
    while t + pd.DateOffset(months=test_m) <= last + pd.Timedelta(days=1):
        tr = bar_index(panel, t - pd.DateOffset(months=train_m))
        ts_ = bar_index(panel, t)
        te = min(b, bar_index(panel, t + pd.DateOffset(months=test_m)) - 1)
        out.append((max(a, tr), ts_, te))
        t = t + pd.DateOffset(months=test_m)
    return out[-6:], train_m, test_m


def walk_forward(panel: S.Panel, p: dict, costs: dict, a: int, b: int, optimize_specs: Optional[list] = None,
                 per_fold: int = 10, progress: Optional[Callable] = None) -> dict:
    windows, train_m, test_m = wf_windows(panel, a, b)
    feat = S.compute_features(panel, p)
    folds, growth, pfs, trials = [], 1.0, [], 0
    for k, (x, y, z) in enumerate(windows):
        if z - y < S.BARS_PER_DAY * 20:
            continue
        q, train_m_ = p, None
        if optimize_specs:
            opt = optimize(panel, p, costs, x, y - 1, optimize_specs, per_fold, seed=42 + k,
                           min_trades=max(10, int(30 * (y - x) / max(1, b - a))),
                           progress=(lambda d, t, k=k: progress(k, d, t)) if progress else None)
            trials += opt["trials"]
            q = opt["best_params"]
            train_m_ = opt["best_metrics"]
            fk = S.compute_features(panel, q)
        else:
            fk = feat
            _, train_m_, _ = run_segment(panel, q, costs, x, y - 1, fk)
            if progress:
                progress(k, 1, 1)
        sim = B.simulate(panel, fk, q, costs, y, z)
        mt = B.metrics(sim, panel)
        growth *= 1 + (mt["net_return_pct"] or 0.0) / 100.0
        if mt["profit_factor"] is not None:
            pfs.append(mt["profit_factor"])
        folds.append({"fold": k, "train_start": B.iso(panel.ts[x]), "train_end": B.iso(panel.ts[y]),
                      "test_start": B.iso(panel.ts[y]), "test_end": B.iso(panel.ts[z]), "train": train_m_,
                      "test": mt, "best_params": ({s["key"]: q[s["key"]] for s in optimize_specs}
                                                  if optimize_specs else None),
                      "_range": [y, z]})
    prof = sum(1 for f in folds if (f["test"]["net_return_pct"] or 0) > 0)
    scheme = (f"rolling train {train_m}m / test {test_m}m, " +
              (f"re-optimised per fold ({per_fold} trials)" if optimize_specs else "fixed params (no re-fit)"))
    return {"scheme": scheme, "folds": folds, "trials_done": trials,
            "oos_compounded_net_pct": (growth - 1.0) * 100.0 if folds else None,
            "oos_avg_pf": sum(pfs) / len(pfs) if pfs else None,
            "oos_trades": sum(f["test"]["trades"] for f in folds),
            "consistency": prof / len(folds) if folds else None}


# ── full pipeline ────────────────────────────────────────────────────────

def evaluate_all(panel: S.Panel, p: dict, costs: dict, mode: str, start: Optional[str], end: Optional[str],
                 holdout_start: Optional[str] = None, n_trials: int = 30, specs: Optional[list] = None,
                 progress: Optional[Callable] = None, lock_cb: Optional[Callable] = None) -> dict:
    """Pure computation (no DB). lock_cb(eval_start_iso, eval_end_iso) -> holdout_start ISO
    (resolves the locked holdout); holdout_start may be given directly instead (tests/research)."""
    prog = progress or (lambda *a, **k: None)
    feat = S.compute_features(panel, p)
    a, b = eval_range(panel, feat, p, start, end)
    data_info = {"eval_start": B.iso(panel.ts[a]), "eval_end": B.iso(panel.ts[b]), "bars": int(b - a + 1),
                 "symbols": list(panel.symbols), "n_symbols": panel.n,
                 "funding_attached": bool(np.any(panel.funding != 0))}
    if mode == "backtest":
        prog("backtest", 0, 1)
        sim = B.simulate(panel, feat, p, costs, a, b)
        m = B.metrics(sim, panel)
        return {"mode": mode, "params": p, "data": data_info, "metrics": {**m, "data": data_info},
                "equity": B.equity_out(sim, panel), "trades": B.trades_out(sim, panel),
                "contrib": B.contributions(sim, panel), "benchmarks": B.benchmarks(panel, feat, a, b)}

    hs = holdout_start or lock_cb(B.iso(panel.ts[a]), B.iso(panel.ts[b]))
    h = bar_index(panel, hs)
    if not (a < h <= b):
        raise honesty.HoldoutError(f"locked holdout {hs} is outside the evaluated range")
    # development panel physically ends before the holdout
    dev = S.slice_panel(panel, h)
    honesty.assert_dev_only([B.iso(dev.ts[-1])], hs)
    dev_b = h - 1

    best_info = None
    if mode == "optimize":
        specs = specs or P.resolve_search(None)
        windows, _, _ = wf_windows(dev, a, dev_b)
        per_fold = max(5, n_trials // 3)
        total_trials = len(windows) * per_fold + n_trials

        def on_wf(k, d, t):
            prog(f"walk-forward fold {k + 1}/{len(windows)}", k * per_fold + d, total_trials,
                 trials_done=k * per_fold + d, trials_total=total_trials)
        wf = walk_forward(dev, p, costs, a, dev_b, specs, per_fold, on_wf)
        base_done = wf["trials_done"]
        best_info = optimize(dev, p, costs, a, dev_b, specs, n_trials, min_trades=30,
                             progress=lambda d, t: prog("optimise on development segment", base_done + d,
                                                        total_trials, trials_done=base_done + d,
                                                        trials_total=total_trials))
        p = P.validate_params({**{k: v for k, v in best_info["best_params"].items() if k != "symbols"},
                               "symbols": p.get("symbols") or []})
    else:
        prog("walk_forward", 0, 1)
        wf = walk_forward(dev, p, costs, a, dev_b)
    dev_feat = S.compute_features(dev, p)
    prog("in-sample backtest", 0, 1)
    sim_is = B.simulate(dev, dev_feat, p, costs, a, dev_b)
    m_is = B.metrics(sim_is, dev)
    prog("sensitivity", 0, len(SENS_PARAMS))
    sens = sensitivity(dev, p, costs, a, dev_b, m_is["net_return_pct"],
                       progress=lambda d, t: prog("sensitivity", d, t))

    # holdout: evaluated once, after every choice has been made
    prog("holdout", 0, 1)
    feat = S.compute_features(panel, p)
    sim_oos = B.simulate(panel, feat, p, costs, h, b)
    m_oos = B.metrics(sim_oos, panel)
    mult = honesty.THRESHOLDS["cost_stress_mult"]
    stress_costs = {**costs, "commission_pct": float(costs.get("commission_pct", 0.05)) * mult,
                    "slippage_pct": float(costs.get("slippage_pct", 0.05)) * mult}
    m_stress = B.metrics(B.simulate(panel, feat, p, stress_costs, h, b), panel)

    prog("full range + Monte Carlo", 0, 1)
    sim_full = B.simulate(panel, feat, p, costs, a, b)
    m_full = B.metrics(sim_full, panel)
    mc = monte_carlo(B.daily_returns(sim_full, panel))

    checks = honesty.build_checks(honesty.HonestyInputs(
        oos_profit_factor=m_oos["profit_factor"] if m_oos["trades"] else None,
        oos_net_return_pct=m_oos["net_return_pct"], oos_trades=m_oos["trades"], mc_dd_p95_pct=mc["dd_p95"],
        stress_net_return_pct=m_stress["net_return_pct"], unstable_params=sens["unstable"],
        liquidations=m_full["liquidations"]))
    verdict = honesty.verdict(checks)
    oos_ranges = [tuple(f.pop("_range")) for f in wf["folds"]]
    bench_full = B.benchmarks(panel, feat, a, b)
    bench_oos = B.benchmarks(panel, feat, h, b)
    metrics = {**m_is, "segment": "in_sample", "start": data_info["eval_start"], "end": hs, "data": data_info,
               "full_range": m_full, "monte_carlo": mc, "walk_forward": wf,
               "sensitivity": {"unstable": sens["unstable"], "tested": len(sens["params"])},
               "benchmarks": {"full_range": bench_full, "holdout": bench_oos}}
    oos = {**m_oos, "start": hs, "end": data_info["eval_end"], "stress_net_return_pct": m_stress["net_return_pct"],
           "stress_multiplier": mult}
    return {"mode": mode, "params": p, "data": data_info, "holdout_start": hs, "metrics": metrics, "oos": oos,
            "checks": checks, "verdict": verdict, "sensitivity": sens,
            "optimizer": best_info and {k: v for k, v in best_info.items() if k != "best_params"},
            "equity": B.equity_out(sim_full, panel, holdout_idx=h, oos_ranges=oos_ranges),
            "trades": B.trades_out(sim_full, panel), "contrib": B.contributions(sim_full, panel),
            "contrib_holdout": B.contributions(sim_oos, panel), "m_is": m_is}


def execute_universal_run(conn, job: dict, run: dict, prog) -> None:
    """Called by src.lab.runner for lab_runs with template_id == universal_v0."""
    import os
    from ..runner import _write_json, artifacts_dir
    run_id, mode = run["id"], run["mode"]
    p = P.validate_params(labdb.loads(run["params_json"], {}))
    costs = labdb.loads(run["costs_json"], {}) or {}
    offline = os.environ.get("LAB_DATA_OFFLINE") == "1"
    prog("data", 0, 1, force=True)
    panel = load_universe_panel(p, funding=bool(costs.get("funding", True)), refresh=not offline, offline=offline,
                                progress=lambda st, d, t: prog(st, d, t))
    specs = P.resolve_search(labdb.loads(run.get("search_json"))) if mode == "optimize" else None
    from ..settings import get_lab_settings
    n_trials = max(1, min(int(run.get("n_trials") or 30), get_lab_settings().optuna_max_trials))

    def lock(ev_start, ev_end):
        return honesty.resolve_holdout(conn, TEMPLATE_ID, UNIVERSE_SYMBOL, BAR_TF, ev_start, ev_end, S.BAR_S)

    res = evaluate_all(panel, p, costs, mode, run["start_date"], run["end_date"], n_trials=n_trials, specs=specs,
                       progress=lambda st, d=0, t=0, **kw: prog(st, d, t, **kw), lock_cb=lock)
    out = artifacts_dir(run_id)
    _write_json(out / "equity.json", res["equity"])
    _write_json(out / "trades.json", res["trades"])
    _write_json(out / "contrib.json", {"full": res["contrib"], "holdout": res.get("contrib_holdout")})
    if mode == "backtest":
        m = res["metrics"]
        conn.execute(
            "UPDATE lab_runs SET metrics_json=?, extra_json=?, net_return_pct=?, profit_factor=?, max_dd_pct=?, "
            "trades=? WHERE id=?",
            (labdb.dumps({**m, "benchmarks": {"full_range": res["benchmarks"]}}), labdb.dumps({}),
             m["net_return_pct"], m["profit_factor"], m["max_dd_pct"], m["trades"], run_id))
        conn.commit()
        return
    conn.execute("UPDATE lab_runs SET holdout_start=? WHERE id=?", (res["holdout_start"], run_id))
    touches = honesty.touch_holdout(conn, TEMPLATE_ID, UNIVERSE_SYMBOL, BAR_TF)
    m_is = res["m_is"]
    if mode == "optimize" and res["optimizer"]:
        conn.execute("UPDATE lab_runs SET trials_done=?, top_trials_json=? WHERE id=?",
                     (res["optimizer"]["trials"] + res["metrics"]["walk_forward"]["trials_done"],
                      labdb.dumps(res["optimizer"]["top_trials"]), run_id))
    conn.execute(
        "UPDATE lab_runs SET verdict=?, checks_json=?, honesty_version=?, metrics_json=?, oos_metrics_json=?, "
        "best_params_json=?, extra_json=?, holdout_touches=?, net_return_pct=?, profit_factor=?, max_dd_pct=?, "
        "trades=? WHERE id=?",
        (res["verdict"], labdb.dumps(res["checks"]), honesty.HONESTY_VERSION, labdb.dumps(res["metrics"]),
         labdb.dumps(res["oos"]), labdb.dumps(res["params"]) if mode == "optimize" else None,
         labdb.dumps({"sensitivity": res["sensitivity"], "optimizer": res["optimizer"]}), touches,
         m_is["net_return_pct"], m_is["profit_factor"], m_is["max_dd_pct"], m_is["trades"], run_id))
    conn.commit()
