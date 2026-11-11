"""Universal robustness research helpers (offline research only, never used by live/paper code).

Every experiment here runs on a panel that the caller has already cut at the locked holdout
start (``S.slice_panel``), except ``holdout_once`` which is the single, pre-registered holdout
evaluation. Used to produce docs/universal-robustness-2026-11.md.

    python -m src.lab.universal.robustness --source static --data /path/cache --out dev_static.json
    python -m src.lab.universal.robustness --source pit    --data /path/perp_pit --out dev_pit.json
"""
from __future__ import annotations

import json
import math
from typing import Iterable, Optional

import numpy as np

from . import backtest as B
from . import params as P
from . import runner as R
from . import strategy as S

HOLDOUT_START = "2025-07-24T04:00:00Z"   # locked by the first Universal v0 validation (2026-11-10)
EVAL_START = "2020-05-16T08:00:00Z"      # first tradable bar of the original report
COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}


# ── loading ──────────────────────────────────────────────────────────────

def load_static(data_dir: str, symbols: Optional[Iterable[str]] = None) -> S.Panel:
    """The 29-coin survivor cache (same files the original report used)."""
    import pandas as pd
    from pathlib import Path
    d = Path(data_dir)
    syms = list(symbols) if symbols else sorted(p.name.split("_PERP_")[0] for p in d.glob("*_PERP_4h.parquet"))
    o, f = {}, {}
    for s in syms:
        df = pd.read_parquet(d / f"{s}_PERP_4h.parquet")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        o[s] = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
        fp = d / f"{s}_PERP_funding.parquet"
        if fp.exists():
            fu = pd.read_parquet(fp)
            fu["timestamp"] = pd.to_datetime(fu["timestamp"], utc=True)
            f[s] = fu.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    return S.build_panel(o, f)


def load_pit(data_dir: str, end=None) -> S.Panel:
    from . import pit_data
    o, f = pit_data.load(data_dir)
    return S.build_panel(o, f, end=end)


def drop_empty(panel: S.Panel) -> S.Panel:
    """Drop coins without a single real bar in the panel (e.g. listed after the holdout start)."""
    return S.subset_panel(panel, np.flatnonzero(panel.present.any(axis=0)))


def dev_panel(panel: S.Panel) -> S.Panel:
    return S.slice_panel(panel, R.bar_index(panel, HOLDOUT_START))


# ── one run ──────────────────────────────────────────────────────────────

def rebal_mask(panel: S.Panel, hour_close: Optional[int]) -> Optional[np.ndarray]:
    """Daily rebalance at the bar CLOSING at `hour_close` UTC (0 = the default 00:00 close)."""
    if hour_close is None:
        return None
    return np.asarray(panel.ts.hour) == (hour_close - 4) % 24


def year_returns(sim: B.SimResult, panel: S.Panel) -> dict:
    import pandas as pd
    ts = panel.ts[sim.start: sim.start + len(sim.equity)] + pd.Timedelta(hours=4)
    eq = pd.Series(sim.equity, index=ts)
    out, prev = {}, sim.initial
    for y, g in eq.groupby(eq.index.year):
        out[str(y)] = float(g.iloc[-1] / prev - 1.0) * 100.0
        prev = float(g.iloc[-1])
    return out


def regimes(panel: S.Panel, sim: B.SimResult) -> dict:
    """BTC regime per day (descriptive, uses the BTC daily close): bull = above 200d SMA and the SMA
    rising over 20 days, bear = below and falling, chop = everything else."""
    b = panel.index_of("BTCUSDT")
    if b is None:
        return {}
    hours = np.asarray(panel.ts.hour)
    dclose_idx = np.flatnonzero(hours == 20)
    px = panel.close[dclose_idx, b]
    import pandas as pd
    sma = pd.Series(px).rolling(200, min_periods=200).mean().to_numpy()
    rising = sma > np.roll(sma, 20)
    rising[:220] = False
    lab = np.where(np.isfinite(sma) & (px > sma) & rising, "bull",
                   np.where(np.isfinite(sma) & (px < sma) & ~rising, "bear", "chop"))
    lab_by_bar = dict(zip(dclose_idx.tolist(), lab.tolist()))
    # daily strategy returns aligned to the daily closes inside the simulation
    eq = sim.equity
    idx = [t for t in dclose_idx if sim.start <= t <= sim.start + len(eq) - 1]
    vals = np.array([sim.initial if t == sim.start else eq[t - sim.start] for t in idx])
    r = vals[1:] / vals[:-1] - 1.0
    regs = np.array([lab_by_bar[t] for t in idx[1:]])
    out = {}
    for g in ("bull", "bear", "chop"):
        x = r[regs == g]
        if len(x) < 5:
            continue
        sd = float(np.std(x, ddof=1))
        out[g] = {"days": int(len(x)), "share_pct": float(len(x) / len(r) * 100.0),
                  "cum_pct": float((np.prod(1 + x) - 1) * 100.0),
                  "ann_ret_pct": float(np.mean(x) * 365 * 100.0),
                  "sharpe": float(np.mean(x) / sd * math.sqrt(365)) if sd > 0 else None}
    return out


def run(panel: S.Panel, overrides: Optional[dict] = None, costs: Optional[dict] = None, drop: Iterable[str] = (),
        hour_close: Optional[int] = None, start: str = EVAL_START, end_idx: Optional[int] = None,
        mc: bool = True, detail: bool = False) -> dict:
    p = P.validate_params(dict(overrides or {}))
    if drop:
        keep = [i for i, s in enumerate(panel.symbols) if s not in set(drop)]
        panel = S.subset_panel(panel, keep)
    feat = S.compute_features(panel, p)
    a = max(S.first_tradable_index(feat, p), R.bar_index(panel, start))
    b = (end_idx if end_idx is not None else S.last_complete_index(panel))
    sim = B.simulate(panel, feat, p, costs or COSTS, a, b, rebal=rebal_mask(panel, hour_close))
    m = B.metrics(sim, panel)
    out = {k: m[k] for k in ("net_return_pct", "cagr_pct", "max_dd_pct", "sharpe", "profit_factor", "trades",
                             "win_rate_pct", "turnover_per_year", "avg_gross_exposure", "avg_positions",
                             "fees_paid", "slippage_paid", "funding_paid", "final_equity")}
    out["start"], out["end"] = B.iso(panel.ts[a]), B.iso(panel.ts[sim.end])
    if mc:
        out["mc_dd_p95"] = R.monte_carlo(B.daily_returns(sim, panel))["dd_p95"]
    contrib = B.contributions(sim, panel)
    tot = sum(c["pnl"] for c in contrib)
    pos = sorted((c for c in contrib if c["pnl"] > 0), key=lambda c: -c["pnl"])
    out["top1"] = pos[0]["symbol"] if pos else None
    out["top1_share_pct"] = pos[0]["pnl"] / tot * 100.0 if pos and tot > 0 else None
    out["top3_share_pct"] = sum(c["pnl"] for c in pos[:3]) / tot * 100.0 if pos and tot > 0 else None
    out["years"] = year_returns(sim, panel)
    if detail:
        out["contrib"] = [{"symbol": c["symbol"], "pnl": c["pnl"], "trades": c["trades"]} for c in contrib]
        out["regimes"] = regimes(panel, sim)
        out["held_symbols"] = sorted({e["symbol"] for e in sim.episodes})
        # PnL by the coin's age (days since its first bar) when the holding episode started
        # (coins whose data starts on the panel's first bar were listed before the data begins -> "pre-data")
        buckets = {"<180d": 0.0, "180-365d": 0.0, "1-2y": 0.0, ">2y": 0.0, "pre-data": 0.0}
        for e in sim.episodes:
            fi = panel.first_idx[panel.symbols.index(e["symbol"])]
            age = (e["entry_idx"] - fi) / S.BARS_PER_DAY
            k = ("pre-data" if fi <= S.BARS_PER_DAY else "<180d" if age < 180 else "180-365d" if age < 365
                 else "1-2y" if age < 730 else ">2y")
            buckets[k] += e["pnl"]
        out["pnl_by_age"] = buckets
    return out


# ── the experiment grid (development segment only) ─────────────────────

def dev_grid(panel: S.Panel, base: Optional[dict] = None, log=print) -> dict:
    base = dict(base or {})
    dev = dev_panel(panel)
    res: dict = {}

    def go(name, **kw):
        ov = {**base, **kw.pop("ov", {})}
        res[name] = run(dev, ov, **kw)
        r = res[name]
        log(f"{name:28s} net {r['net_return_pct']:9.1f}%  dd {r['max_dd_pct']:6.1f}  sh {r['sharpe'] or 0:5.2f}  "
            f"pf {r['profit_factor'] or 0:4.2f}  mc95 {r.get('mc_dd_p95') or 0:6.1f}  top1 {r['top1']} "
            f"{r['top1_share_pct'] or 0:5.1f}%")

    go("baseline", detail=True)
    contrib = res["baseline"]["contrib"]
    top = [c["symbol"] for c in contrib if c["pnl"] > 0][:3]
    go("drop_top1", drop=top[:1])
    go("drop_top3", drop=top[:3])
    for cap in (25.0, 20.0, 15.0, 10.0):
        go(f"cap_{int(cap)}", ov={"max_weight_pct": cap})
    for n in (10, 15):
        go(f"top_{n}", ov={"top_n": n})
        go(f"top_{n}_cap_15", ov={"top_n": n, "max_weight_pct": 15.0})
    go("min_hist_365", ov={"min_history_days": 365})
    # same comparison from 2021 (min_hist_365 cannot trade anything before ~2021-01 because the data starts 2020-01)
    go("baseline_from_2021", start="2021-01-01T00:00:00Z")
    go("min_hist_365_from_2021", ov={"min_history_days": 365}, start="2021-01-01T00:00:00Z")
    for h in (4, 8, 12, 16, 20):
        go(f"rebal_close_{h:02d}h", hour_close=h)
    for mult in (2, 3):
        go(f"cost_{mult}x", costs={**COSTS, "commission_pct": 0.05 * mult, "slippage_pct": 0.05 * mult})
    go("cost_0", costs={"commission_pct": 0.0, "slippage_pct": 0.0, "funding": False}, mc=False)
    return {"top_contributors": top, "runs": res}


# ── the single holdout evaluation ────────────────────────────────────────

def holdout_once(panel: S.Panel, prereg_path: str, out_path: str, log=print) -> dict:
    """Evaluate the pre-registered variants on the locked holdout, exactly once.

    Refuses to run without a pre-registration file or if results already exist. For each variant:
    the full Lab honesty pipeline (R.evaluate_all 'validate' with the locked holdout start, same
    7 checks) plus a diagnostic breakdown of the holdout (per-coin contribution, without the top coin)."""
    import hashlib
    import os
    from datetime import datetime, timezone
    if os.path.exists(out_path):
        raise SystemExit(f"{out_path} exists: the holdout has already been evaluated for this pre-registration")
    raw = open(prereg_path, "rb").read()
    prereg = json.loads(raw)
    res = {"prereg_sha256": hashlib.sha256(raw).hexdigest(), "prereg": prereg,
           "evaluated_at": datetime.now(timezone.utc).isoformat(), "variants": {}}
    for name, spec in prereg["variants"].items():
        p = P.validate_params(spec["params"])
        log(f"holdout: {name} {spec['params']}")
        r = R.evaluate_all(panel, p, COSTS, "validate", EVAL_START, None, holdout_start=HOLDOUT_START)
        h = R.bar_index(panel, HOLDOUT_START)
        b = S.last_complete_index(panel)
        oos = run(panel, spec["params"], start=HOLDOUT_START, end_idx=b, mc=False, detail=True)
        top = oos["top1"]
        wo = run(panel, spec["params"], start=HOLDOUT_START, end_idx=b, mc=False, drop=[top]) if top else None
        feat = S.compute_features(panel, p)
        res["variants"][name] = {
            "verdict": r["verdict"], "checks": r["checks"],
            "oos": {k: r["oos"].get(k) for k in ("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades",
                                                 "stress_net_return_pct", "win_rate_pct", "start", "end")},
            "in_sample": {k: r["m_is"].get(k) for k in ("net_return_pct", "max_dd_pct", "sharpe", "profit_factor")},
            "full_range": {k: r["metrics"]["full_range"].get(k) for k in ("net_return_pct", "max_dd_pct", "sharpe")},
            "monte_carlo": r["metrics"]["monte_carlo"], "walk_forward": {
                k: r["metrics"]["walk_forward"].get(k) for k in ("oos_compounded_net_pct", "oos_avg_pf",
                                                                 "consistency")},
            "sensitivity_unstable": r["sensitivity"]["unstable"],
            "holdout_contrib": oos["contrib"][:8] + oos["contrib"][-5:], "holdout_top1": top,
            "holdout_top1_share_pct": oos["top1_share_pct"],
            "holdout_without_top1": wo and {k: wo[k] for k in ("net_return_pct", "max_dd_pct", "profit_factor")},
            "holdout_held_symbols": oos["held_symbols"], "holdout_regimes": oos["regimes"],
            "benchmarks_holdout": B.benchmarks(panel, feat, h, b),
        }
        log(json.dumps(res["variants"][name]["oos"], default=float))
    with open(out_path, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    return res


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["static", "pit"], required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--universe-size", type=int, default=30)
    ap.add_argument("--static-symbols", default="", help="comma list of the static universe (for decomposition)")
    ap.add_argument("--holdout-prereg", default=None,
                    help="pre-registration JSON: evaluate its variants on the locked holdout ONCE")
    a = ap.parse_args(argv)
    if a.holdout_prereg:
        panel = load_static(a.data) if a.source == "static" else drop_empty(load_pit(a.data))
        holdout_once(panel, a.holdout_prereg, a.out)
        return 0
    if a.source == "static":
        panel, base = load_static(a.data), {}
    else:
        base = {"universe_mode": "liquidity", "universe_size": a.universe_size}
        # exploration never even loads holdout bars
        panel = drop_empty(load_pit(a.data, end=HOLDOUT_START))
        print(f"PIT dev panel: {panel.n} coins with data before {HOLDOUT_START}")
    out = dev_grid(panel, base)
    if a.source == "pit":
        dev = dev_panel(panel)
        extra = {}
        for k in (20, 50):
            extra[f"universe_{k}"] = run(dev, {**base, "universe_size": k})
        # decomposition: drop every coin that is no longer trading today (hindsight, on purpose)
        from pathlib import Path
        man = json.loads((Path(a.data) / "_manifest.json").read_text())
        last = max(v["last"] for v in man.values() if v.get("last"))
        import pandas as pd
        cutoff = pd.Timestamp(last) - pd.Timedelta(days=3)
        dead = sorted(s_ for s_, v in man.items() if v.get("last") and pd.Timestamp(v["last"]) < cutoff)
        extra["survivors_only"] = run(dev, base, drop=dead, detail=True)
        extra["survivors_only"]["n_dropped"] = len(dead)
        # the 29 cached survivors, but chosen point-in-time by liquidity like the PIT run
        static29 = a.static_symbols.split(",") if a.static_symbols else []
        if static29:
            extra["static29_liquidity"] = run(dev, base, drop=[x for x in dev.symbols if x not in static29])
        out["extra"] = extra
        out["dead_symbols"] = dead
        for kk, r in extra.items():
            print(f"{kk:28s} net {r['net_return_pct']:9.1f}%  dd {r['max_dd_pct']:6.1f}  sh {r['sharpe'] or 0:5.2f}"
                  f"  pf {r['profit_factor'] or 0:4.2f}  mc95 {r.get('mc_dd_p95') or 0:6.1f}")
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
