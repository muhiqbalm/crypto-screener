"""DEVELOPMENT-ONLY scan of the new templates. No bar at/after the dev cutoff is ever handed to the engine:
cutoff per coin/TF = min(2025-07-06T04:00Z [holdout start of every earlier ETH/BTC look],
                         Lab rule: start of the last 20% of the coin's own range).
Backtest mode only, Lab costs (0.05% fee + 0.05% slippage per side, funding on).

    python devscan.py grid  -> candidate defaults on 29 coins x 4H (pick by median dev Sharpe)
    python devscan.py scan  -> chosen defaults, 29 coins x 4H + 1D, + daily-return correlations
"""
import json, math, sys, multiprocessing as mp
from common import *  # noqa
import numpy as np
import pandas as pd
from src.lab import honesty
from src.lab.templates import TEMPLATES

HS_GLOBAL = pd.Timestamp("2025-07-06T04:00:00Z")
EVAL_FROM = pd.Timestamp("2020-03-01T00:00:00Z")
MIN_DEV_DAYS = 365
COINS = sorted({p.name.split("_PERP_")[0] for p in dc.data_dir().glob("*_PERP_4h.parquet")})

D = "donchian_breakout"; M = "mean_reversion_range"; R = "rosyade_family"
GRID = {
    "D1 N55/M20/k3 HTF1d50": (D, {}),
    "D2 N55/M20/k3 noHTF": (D, {"use_ema_htf": False}),
    "D3 N20/M10/k2.5 HTF1d50": (D, {"dc_entry_len": 20, "dc_exit_len": 10, "dc_atr_mult": 2.5}),
    "D4 N100/M50/k4 HTF1d50": (D, {"dc_entry_len": 100, "dc_exit_len": 50, "dc_atr_mult": 4.0}),
    "D5 N55/M20/k3 HTF same200": (D, {"ema_htf_tf": "same", "ema_htf_len": 200}),
    "M1 bb20x2 reenter adx<20": (M, {}),
    "M2 bb20x2 outside adx<20": (M, {"mr_trigger": "outside"}),
    "M3 bb20x2 reenter chop>55": (M, {"mr_regime": "chop"}),
    "M4 kc20x2 reenter adx<20": (M, {"mr_band": "kc"}),
    "M5 bb20x2.5 reenter adx<25": (M, {"mr_mult": 2.5, "mr_adx_max": 25.0}),
    "M6 bb20x2 reenter adx<20 rsi30/70": (M, {"mr_use_rsi": True}),
}

RISK1 = {"sizing_mode": "risk", "risk_per_trade_pct": 1.0, "max_notional_mult": 2.0}
D4 = {"dc_entry_len": 100, "dc_exit_len": 50, "dc_atr_mult": 4.0}
GRID2 = {
    "D4 zero-cost": (D, {**D4, "_zero": True}),
    "D4 risk1%": (D, {**D4, **RISK1}),
    "D1 risk1%": (D, RISK1),
    "D6 N100/M50/k4 noHTF": (D, {**D4, "use_ema_htf": False}),
    "D7 N200/M100/k4 HTF1d50": (D, {"dc_entry_len": 200, "dc_exit_len": 100, "dc_atr_mult": 4.0}),
    "D8 N100/M50/k4 long-only": (D, {**D4, "enable_short": False}),
    "D4 @1d": (D, {**D4, "_tf": "1d"}),
    "D3 @1d": (D, {"dc_entry_len": 20, "dc_exit_len": 10, "dc_atr_mult": 2.5, "_tf": "1d"}),
    "D1 @1d": (D, {"_tf": "1d"}),
    "M3 zero-cost": (M, {"mr_regime": "chop", "_zero": True}),
    "M1 zero-cost": (M, {"_zero": True}),
    "M3 risk1%": (M, {"mr_regime": "chop", **RISK1}),
    "M7 kc20x2 reenter chop>55": (M, {"mr_regime": "chop", "mr_band": "kc"}),
    "M8 bb20x2 reenter chop>60": (M, {"mr_regime": "chop", "mr_chop_min": 60.0}),
    "M9 bb20x2 reenter adx<25&chop>55": (M, {"mr_regime": "adx_chop", "mr_adx_max": 25.0}),
    "M10 bb20x2 reenter chop>55 stop3 t40": (M, {"mr_regime": "chop", "mr_stop_atr_mult": 3.0, "mr_max_bars": 40}),
    "M3 @1d": (M, {"mr_regime": "chop", "_tf": "1d"}),
}

_cache = {}


def dev_frame(sym, tf, warm):
    """(df, t0, cutoff): rows strictly before the cutoff only, enough warm-up before EVAL_FROM."""
    key = (sym, tf)
    if key not in _cache:
        ohlcv, fund = dc.ensure(sym, tf, funding=True, offline=True)
        bar = ea.TF_SECONDS[tf]
        first = ohlcv["timestamp"].iloc[min(len(ohlcv) - 1, 300)]
        end = ohlcv["timestamp"].iloc[-1] + pd.Timedelta(seconds=bar)
        prop = pd.Timestamp(honesty.proposed_holdout_start(first, end, bar))
        cutoff = min(HS_GLOBAL, prop)
        ohlcv = ohlcv[ohlcv["timestamp"] < cutoff].reset_index(drop=True)
        df, *_ = ea.prepare_frame(ohlcv, fund, tf, None, None, 0, True)
        honesty.assert_dev_only(df["timestamp"].tail(1), honesty.iso(cutoff))
        _cache[key] = (df, cutoff)
    df, cutoff = _cache[key]
    t0 = max(EVAL_FROM, df["timestamp"].iloc[min(len(df) - 1, warm)])
    return df, t0, cutoff


def run_one(args):
    label, tid, over, sym, tf = args
    over = dict(over)
    zero = over.pop("_zero", False)
    tf = over.pop("_tf", tf)
    t = TEMPLATES[tid]
    p = t.validate_params(over)
    try:
        costs = {**COSTS, "commission_pct": 0.0, "slippage_pct": 0.0, "funding": False} if zero else COSTS
        cfg, ecfg = ea.build_configs(p, tf, costs, tid)
        warm = ecfg.warmup_period
        df, t0, cutoff = dev_frame(sym, tf, warm)
        if (cutoff - t0).days < MIN_DEV_DAYS:
            return {"label": label, "sym": sym, "tf": tf, "skip": f"dev < {MIN_DEV_DAYS}d"}
        sl, pre = ea.window(df, t0, None, warm)
        if zero:
            sl = sl.drop(columns=["funding_rate"], errors="ignore")
        if pre < warm:
            return {"label": label, "sym": sym, "tf": tf, "skip": "warm-up"}
        res, _ = ea.run(sl, cfg, ecfg, warmup=pre)
        m = ea.metrics(res)
        eq = pd.Series([v for _, v in res.equity_curve], index=pd.to_datetime([x for x, _ in res.equity_curve], utc=True))
        yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
        cagr = ((eq.iloc[-1] / 100.0) ** (1 / yrs) - 1) * 100 if eq.iloc[-1] > 0 and yrs > 0 else -100.0
        daily = eq.resample("1D").last().ffill()
        return {"label": label, "tid": tid, "sym": sym, "tf": tf, "start": str(t0), "dev_end": str(cutoff),
                "trades": m["trades"], "net": m["net_return_pct"], "cagr": cagr, "sharpe": m["sharpe"],
                "dd": m["max_dd_pct"], "pf": m["profit_factor"], "wr": m["win_rate_pct"],
                "liq": m["liquidations"], "fees": m["fees_paid"], "funding": m["funding_paid"],
                "longs": m["longs"], "shorts": m["shorts"],
                "daily": {d.strftime("%Y-%m-%d"): float(v) for d, v in daily.items()}}
    except Exception as e:  # noqa: BLE001
        return {"label": label, "sym": sym, "tf": tf, "error": f"{type(e).__name__}: {e}"[:300]}


def summarise(rows, label):
    ok = [r for r in rows if r["label"] == label and "net" in r]
    if not ok:
        return {}
    sh = np.array([r["sharpe"] if r["sharpe"] is not None else np.nan for r in ok], dtype=float)
    cg = np.array([r["cagr"] for r in ok]); dd = np.array([r["dd"] for r in ok])
    pf = np.array([r["pf"] if r["pf"] is not None else np.nan for r in ok], dtype=float)
    return {"n": len(ok), "sharpe_med": float(np.nanmedian(sh)), "sharpe_q25": float(np.nanpercentile(sh, 25)),
            "sharpe_q75": float(np.nanpercentile(sh, 75)), "share_cagr_pos": float(np.mean(cg > 0)),
            "cagr_med": float(np.median(cg)), "dd_med": float(np.median(dd)), "pf_med": float(np.nanmedian(pf)),
            "trades_med": float(np.median([r["trades"] for r in ok])), "liq": int(sum(r["liq"] for r in ok))}


def corr(a, b):
    s = pd.concat([pd.Series(a), pd.Series(b)], axis=1, join="inner").dropna()
    r = s.pct_change().dropna()
    r = r[(r.iloc[:, 0] != 0) | (r.iloc[:, 1] != 0)] if len(r) else r
    return (float(r.iloc[:, 0].corr(r.iloc[:, 1])), int(len(r))) if len(r) > 30 else (None, int(len(r)))


def main():
    mode = sys.argv[1]
    if mode in ("grid", "grid2"):
        g = GRID if mode == "grid" else GRID2
        tasks = [(lab, tid, over, s, "4h") for lab, (tid, over) in g.items() for s in COINS]
    else:
        tasks = [(f"{tid}", tid, {}, s, tf) for tid in (D, M) for s in COINS for tf in ("4h", "1d")]
        tasks += [("4H-ETH-Basic", R, {}, s, "4h") for s in ("ETHUSDT", "BTCUSDT")]
        tasks += [("4H-ETH-Basic", R, {}, "ETHUSDT", "1d")]
    with mp.Pool(3) as pool:
        rows = list(pool.imap_unordered(run_one, tasks, chunksize=1))
    labels = sorted({t[0] for t in tasks})
    summ = {lab: summarise(rows, lab) for lab in labels}
    if mode == "scan":
        summ = {f"{lab}|{tf}": summarise([r for r in rows if r["tf"] == tf], lab) for lab in labels for tf in ("4h", "1d")}
        base = next(r for r in rows if r["label"] == "4H-ETH-Basic" and r["sym"] == "ETHUSDT" and r["tf"] == "4h")
        cors = {}
        for r in rows:
            if "daily" in r and r["sym"] in ("ETHUSDT", "BTCUSDT") and r["label"] != "4H-ETH-Basic":
                cors[f"{r['label']}|{r['sym']}|{r['tf']}"] = corr(r["daily"], base["daily"])
        dm = [r for r in rows if r["label"] == D and r["tf"] == "4h" and "daily" in r]
        mm = {r["sym"]: r for r in rows if r["label"] == M and r["tf"] == "4h" and "daily" in r}
        pair = [corr(r["daily"], mm[r["sym"]]["daily"])[0] for r in dm if r["sym"] in mm]
        cors["donchian_vs_meanrev_same_coin_4h_median"] = (float(np.nanmedian([x for x in pair if x is not None])), len(pair))
        summ["correlations_vs_4H-ETH-Basic"] = cors
    for r in rows:
        r.pop("daily", None)
    with open(f"{EXP}/out/{mode}.json", "w") as f:
        json.dump({"summary": summ, "rows": sorted(rows, key=lambda r: (r["label"], r["tf"], r["sym"]))}, f, indent=1,
                  default=str)
    print(json.dumps(summ, indent=1, default=str))
    errs = [r for r in rows if "error" in r]
    print("errors", len(errs), errs[:3], "skipped", sum(1 for r in rows if "skip" in r))


if __name__ == "__main__":
    main()
