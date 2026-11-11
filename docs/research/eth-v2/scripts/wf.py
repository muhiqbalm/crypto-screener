"""Walk-forward re-optimisation + robustness scoring for one search VARIANT (dev only).

    python wf.py <variant>          -> $EXP/out/wf_<variant>.json

Steps (all on data before HS = the locked ETH 4h holdout start):
 1. Extended walk-forward: 16 rolling folds (12m train / 3m test, tests tile
    2021-07-01 .. 2025-07-01). On every train window the Lab optimiser
    (engine_adapter.optimize: Optuna TPE, robust_score objective) re-optimises the
    variant's search space; the fold winner is run once on its test window at 1x and
    2x costs. This measures the *procedure* out of sample.
 2. Final optimisation on the whole development segment (same optimiser).
 3. Candidate param sets = top-10 final trials + the per-parameter median of the
    16 fold winners ("consensus") + the variant's base. Each is scored with FIXED
    params on the common window 2021-07-01 .. HS (quarterly returns, 2x costs,
    Monte Carlo DD). Sensitivity (the Lab's +-10/20% grid) is run for the 3 best.

Robust rank of a fixed param set (declared here before any run):
    gates : trades >= 110 on the common window, no liquidation, net at 2x costs > 0,
            fragile params <= 3 (only known for the shortlisted three)
    score : 0.5 * (share of positive quarters, all 16 + share of positive quarters,
            last 8) * sharpe_at_2x_costs * min(1, trades / 110), halved when the
            Monte Carlo 95th-pct DD is deeper than -50%.
"""
import statistics
import sys
import time

from common import *  # noqa: F401,F403

BASIC = T.defaults()
SPEC = {p["key"]: p for p in T.PARAMS}
LITE = ["long_sl_pct", "short_sl_pct", "atr_mult_medium_long", "atr_mult_medium_short", "ema_htf_len",
        "cooldown_bars"]


def spec(key, lo=None, hi=None):
    s = dict(SPEC[key])
    s["tunable"] = True
    if lo is not None:
        s["min"] = lo
    if hi is not None:
        s["max"] = hi
    return s


def all_tunables(htf_hi):
    return [spec(p["key"], *((10, htf_hi) if p["key"] == "ema_htf_len" else (None, None)))
            for p in T.tunable_params()]


VARIANTS = {
    # Lab default search space (13 tunables), HTF EMA on the base timeframe (= 4H-ETH-Basic family).
    "A_all_same": {"base": {}, "specs": all_tunables(400)},
    # Same 13 tunables, trend filter on a true 1d EMA (engine 4b144ce+). 1d EMA-32 ~ 4h EMA-194.
    "B_all_1d": {"base": {"ema_htf_tf": "1d", "ema_htf_len": 32}, "specs": all_tunables(120)},
    # 6 degrees of freedom only (stops, trailing, trend length, cooldown); 1d trend filter.
    "C_lite_1d": {"base": {"ema_htf_tf": "1d", "ema_htf_len": 32},
                  "specs": [spec(k, *((10, 120) if k == "ema_htf_len" else (None, None))) for k in LITE]},
    # Same 6 degrees of freedom, HTF EMA on the base timeframe.
    "D_lite_same": {"base": {}, "specs": [spec(k) for k in LITE]},
    # C + the template's existing volatility gate (ATR % filter, off in Basic).
    "E_lite_1d_atr": {"base": {"ema_htf_tf": "1d", "ema_htf_len": 32, "use_atr_filter": True, "atr_min_pct": 1.0},
                      "specs": [spec(k, *((10, 120) if k == "ema_htf_len" else (None, None))) for k in LITE]
                      + [spec("atr_min_pct", 0.3, 3.0)]},
}

PER_FOLD = int(os.environ.get("ETHV2_PER_FOLD", "30"))
FINAL_TRIALS = int(os.environ.get("ETHV2_FINAL", "120"))
FOLD_MIN_TRADES, MIN_TRADES = 25, 110


def max_warm(base, specs):
    p = dict(base)
    for s in specs:
        if s["key"] == "ema_htf_len":
            p["ema_htf_len"] = s["max"]
    return warm(p)


def fixed_eval(dev, params, mc=True):
    t0 = pd.Timestamp(FIRST_TEST, tz="UTC")
    hs = pd.Timestamp(HS)
    res, ind, pre, cfg, ecfg = run_window(dev, params, t0, hs)
    q = quarter_returns(res, t0, hs)
    st, _ = ea.run(*_stress_args(dev, params, t0, hs))
    q2 = quarter_returns(st, t0, hs)
    m, m2 = mstat(res), mstat(st)
    out = {"m": m, "m2x": m2, "quarters": [round(x, 2) for x in q], "quarters_2x": [round(x, 2) for x in q2],
           "pos_q": sum(1 for x in q if x > 0) / len(q), "pos_q_last8": sum(1 for x in q[-8:] if x > 0) / 8,
           "pos_q2x": sum(1 for x in q2 if x > 0) / len(q2), "worst_q": min(q), "median_q": statistics.median(q),
           "last8_net_pct": (math.prod(1 + x / 100 for x in q[-8:]) - 1) * 100,
           "last8_net_2x_pct": (math.prod(1 + x / 100 for x in q2[-8:]) - 1) * 100}
    if mc:
        out["mc"] = ea.monte_carlo(res)
    return out


def _stress_args(dev, params, t0, t1):
    p = T.validate_params(params)
    cfg, ecfg = ea.build_configs(p, TF, COSTS)
    sl, pre = ea.window(dev, t0, t1, ecfg.warmup_period)
    return sl, cfg, ea.scaled_costs(ecfg, 2.0, warmup_period=pre)


def robust_rank(e, unstable=None):
    m, m2 = e["m"], e["m2x"]
    gates = {"trades": m["trades"] >= MIN_TRADES, "no_liq": not m["liquidations"],
             "net2x_pos": (m2["net_return_pct"] or -1) > 0,
             "sensitivity": True if unstable is None else unstable <= 3}
    s2 = m2["sharpe"] or 0.0
    score = 0.5 * (e["pos_q"] + e["pos_q_last8"]) * s2 * min(1.0, m["trades"] / MIN_TRADES)
    if e.get("mc") and (e["mc"]["dd_p95"] or -100) < -50:
        score *= 0.5
    return {"score": round(score, 4), "gates": gates, "passes": all(gates.values())}


def sensitivity(dev, params):
    p = T.validate_params(params)
    cfg, ecfg = ea.build_configs(p, TF, COSTS)
    t0 = pd.Timestamp(FIRST_TEST, tz="UTC")
    sl, pre = ea.window(dev, t0, pd.Timestamp(HS), ecfg.warmup_period)
    ind = ea._engine()["precompute"](sl, cfg)
    from dataclasses import replace
    s = ea.sensitivity(ind, cfg, replace(ecfg, warmup_period=pre))
    return {"unstable": s["unstable"], "tested": len(s["params"]),
            "mean_stability": statistics.mean(r["stability"] for r in s["params"] if r["stability"] is not None),
            "fragile": [r["param"] for r in s["params"] if r["fragile"]],
            "min_profitable_fraction": min(r["profitable_fraction"] for r in s["params"])}


def main(name):
    v = VARIANTS[name]
    base = T.validate_params({**BASIC, **v["base"]})
    specs = v["specs"]
    keys = [s["key"] for s in specs]
    full, dev = frame()
    W = max_warm(base, specs)
    t_start = time.time()

    # 1. extended walk-forward (re-optimised per fold)
    wf, growth, growth2 = [], 1.0, 1.0
    for k, (a, b, c) in enumerate(folds()):
        tr, tw = ea.window(dev, a, b, W)
        assert tw == W, (k, tw, W)
        opt = ea.optimize(tr, tw, base, TF, COSTS, PER_FOLD, HS, seed=42 + k, specs=specs,
                          min_trades=FOLD_MIN_TRADES, top_n=1)
        bp = opt["best_params"]
        te, sw = ea.window(dev, b, c, W)
        cfg, ecfg = ea.build_configs(bp, TF, COSTS)
        r1, ind = ea.run(te, cfg, ecfg, warmup=sw)
        r2, _ = ea.run(te, cfg, ea.scaled_costs(ecfg, 2.0, warmup_period=sw), indicators=ind)
        m1, m2 = mstat(r1), mstat(r2)
        growth *= 1 + (m1["net_return_pct"] or 0) / 100
        growth2 *= 1 + (m2["net_return_pct"] or 0) / 100
        wf.append({"fold": k, "train": [honesty.iso(a), honesty.iso(b)], "test": [honesty.iso(b), honesty.iso(c)],
                   "train_score": opt["best_score"], "test": m1, "test_2x": m2,
                   "best": {x: bp[x] for x in keys}})
        print(name, "fold", k, honesty.iso(b)[:10], "net", fnum(m1["net_return_pct"], 1), "2x",
              fnum(m2["net_return_pct"], 1), "n", m1["trades"], flush=True)
    pos = [f for f in wf if (f["test"]["net_return_pct"] or 0) > 0]
    pfs = [f["test"]["profit_factor"] for f in wf if f["test"]["profit_factor"] not in (None, float("inf"))]
    wf_sum = {"folds": len(wf), "oos_compounded_net_pct": (growth - 1) * 100,
              "oos_compounded_net_2x_pct": (growth2 - 1) * 100, "consistency": len(pos) / len(wf),
              "consistency_last8": sum(1 for f in wf[-8:] if (f["test"]["net_return_pct"] or 0) > 0) / 8,
              "oos_last8_net_pct": (math.prod(1 + (f["test"]["net_return_pct"] or 0) / 100 for f in wf[-8:]) - 1) * 100,
              "oos_median_pf": statistics.median(pfs) if pfs else None,
              "oos_trades": sum(f["test"]["trades"] for f in wf),
              "worst_fold_net_pct": min(f["test"]["net_return_pct"] or 0 for f in wf)}
    # parameter drift across folds (coefficient of variation per key)
    drift = {}
    for x in keys:
        vals = [f["best"][x] for f in wf]
        mu = statistics.mean(vals)
        drift[x] = {"median": statistics.median(vals), "cv": (statistics.pstdev(vals) / abs(mu)) if mu else None}
    print(name, "WF", {k: fnum(v, 2) for k, v in wf_sum.items()}, flush=True)

    # 2. final optimisation on the development segment
    t_dev0 = dev["timestamp"].iloc[W]
    dv, dw = ea.window(dev, t_dev0, None, W)
    fin = ea.optimize(dv, dw, base, TF, COSTS, FINAL_TRIALS, HS, seed=42, specs=specs, min_trades=130, top_n=10)

    # 3. candidates with fixed params
    cands = {"base": base}
    for t in fin["top_trials"]:
        if t.get("score") is not None:
            cands[f"final_r{t['rank']}"] = T.validate_params({**base, **t["params"]})
    cons = {}
    for x in keys:
        med = drift[x]["median"]
        cons[x] = int(round(med)) if SPEC[x]["type"] == "int" else round(
            round(med / (SPEC[x]["step"] or 0.1)) * (SPEC[x]["step"] or 0.1), 6)
    cands["consensus"] = T.validate_params({**base, **cons})
    evals = {}
    for cn, cp in cands.items():
        e = fixed_eval(dev, cp)
        e["rank"] = robust_rank(e)
        e["params_changed"] = {x: cp[x] for x in cp if cp[x] != BASIC.get(x)}
        evals[cn] = e
        print(name, cn, "score", e["rank"]["score"], "pass", e["rank"]["passes"], "n", e["m"]["trades"],
              "pf", fnum(e["m"]["profit_factor"], 2), "2x", fnum(e["m2x"]["net_return_pct"], 0),
              "posq", round(e["pos_q"], 2), "l8", round(e["pos_q_last8"], 2), "mc", fnum(e["mc"]["dd_p95"], 1),
              flush=True)
    short = sorted((c for c in evals if evals[c]["rank"]["passes"]), key=lambda c: -evals[c]["rank"]["score"])[:3]
    for cn in short:
        s = sensitivity(dev, cands[cn])
        evals[cn]["sensitivity"] = s
        evals[cn]["rank"] = robust_rank(evals[cn], s["unstable"])
        print(name, cn, "sens", s["unstable"], round(s["mean_stability"], 3), s["fragile"], flush=True)
    out = {"variant": name, "base_overrides": v["base"], "searched": [{"key": s["key"], "min": s["min"],
                                                                        "max": s["max"]} for s in specs],
           "warmup": W, "per_fold_trials": PER_FOLD, "final_trials": FINAL_TRIALS, "walk_forward": wf_sum,
           "folds": wf, "param_drift": drift, "final": {k: v for k, v in fin.items() if k != "best_params"},
           "candidates": {cn: {"params": cands[cn], **evals[cn]} for cn in cands}, "shortlist": short,
           "seconds": time.time() - t_start}
    dump(f"{OUT}/wf_{name}{os.environ.get('ETHV2_TAG', '')}.json", out)
    print(name, "done", round(time.time() - t_start), "s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
