#!/usr/bin/env python3
"""Frozen reference numbers ("angka acuan") for the pre-registered baskets.

08-praregistrasi-basket.md §10, procedure fixed in commit 52dccca BEFORE this script ran.
Used for: the DD limit (1.5 x max DD), the secondary drift checks, the time-to-30 estimate.
NOT used for coins, params or PF thresholds.

Light: one engine run per coin x basket (57 runs over ~16 months of 4H bars + warm-up).

    LAB_ENGINE_PATH=<engine 6e2cc34> LAB_DATA_DIR=<Lab perp cache> LAB_DB_PATH=<scratch>/lab.db \
    PYTHONPATH=<this repo> nice -n 10 <engine venv>/bin/python docs/research/basket/scripts/expectation.py \
        --prereg docs/research/basket/prereg-basket-2026-11-12.json --out docs/research/basket/expectation.json

Per coin it runs the strategy exactly like a watch does (engine_adapter.build_configs ->
prepare_frame(start=window start, warm-up before it) -> run -> trades_out), offline from the cache.
The basket is then composed on ONE 10,000 account in time order with the pre-registered sizing:
  A (risk 0.25%):  pnl = balance_at_entry x 0.25 x ROE%/100   (engine risks 1% -> ROE% = R x 1)
  B (VT60 slots):  pnl = balance_at_entry / 28 x ROE%/100     (engine sizes VT60 per coin)
balance_at_entry = realised balance (closed trades only), exits before entries on the same timestamp.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WINDOW_START = "2025-07-06 00:00:00"
SEED = 20261112
N_MC = 1000
N_STARTS = 52
START_BALANCE = 10000.0
DAYS_PER_MONTH = 30.4375
TF_S = {"4h": 14400}


def _epoch(s: str) -> float:
    t = s.replace(" ", "T").replace("Z", "+00:00")
    d = datetime.fromisoformat(t)
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def _iso(e: float) -> str:
    return datetime.fromtimestamp(e, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_coin(symbol: str, basket: dict) -> tuple[list[dict], str]:
    from src.lab import data_cache as dc
    from src.lab import engine_adapter as ea
    costs, tf = basket["costs"], basket["timeframe"]
    ohlcv, fund = dc.ensure(symbol, tf, funding=bool(costs.get("funding", True)), offline=True)
    tm = ea.template(basket["template_id"])
    cfg, ecfg = ea.build_configs(basket["params"], tf, costs, tm.TEMPLATE_ID)
    df, _, _, _ = ea.prepare_frame(ohlcv, fund, tf, WINDOW_START, None, ecfg.warmup_period,
                                   bool(costs.get("funding", True)))
    res, _ = ea.run(df, cfg, ecfg)
    w0 = _epoch(WINDOW_START)
    trades = [dict(t, symbol=symbol) for t in ea.trades_out(res) if _epoch(t["entry_time"]) >= w0]
    return trades, ea._iso(df["timestamp"].iloc[-1])


def max_dd(values: list[float]) -> float:
    peak, worst = None, 0.0
    for v in values:
        peak = v if peak is None or v > peak else peak
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100.0)
    return worst


def compose(trades: list[dict], basket: dict, tf_s: int) -> dict:
    """Run the pre-registered sizing over all coins' trades on one account (closed balance)."""
    sz = basket["sizing"]
    assert sz["mode"] in ("risk", "slot_engine")
    if sz["mode"] == "risk":
        # the engine risks risk_per_trade_pct (1.0) of its equity per trade, so ROE% = R x 1.0; the basket
        # risks risk_pct (0.25) of its balance: pnl = balance x (0.25 / 1.0) x ROE% / 100
        weight = float(sz["risk_pct"]) / float(basket["params"]["risk_per_trade_pct"])
    else:
        weight = 1.0 / int(sz["slots"])
    events = []
    for i, t in enumerate(trades):
        events.append((_epoch(t["entry_time"]) + tf_s, 1, i))          # fill at the signal-bar close
        events.append((_epoch(t["exit_time"]) + tf_s, 0, i))           # exit known at that bar's close
    events.sort()
    bal = START_BALANCE
    stake, notional, pnl, frac = {}, {}, {}, {}
    open_n: dict[int, float] = {}
    curve = [(_epoch(WINDOW_START), bal)]
    max_gross, cap_binds = 0.0, 0
    for ts, kind, i in events:
        t = trades[i]
        if kind == 1:
            stake[i] = bal * weight
            nm = (t["return_on_equity_pct"] / t["pnl_pct"]) if t.get("pnl_pct") else 0.0
            notional[i] = stake[i] * abs(nm)
            open_n[i] = notional[i]
            gross = sum(open_n.values()) / bal if bal > 0 else 0.0
            max_gross = max(max_gross, gross)
            if gross > float(sz["gross_cap_x"]) + 1e-12:
                cap_binds += 1
        else:
            p = stake[i] * float(t["return_on_equity_pct"]) / 100.0
            frac[i] = p / (stake[i] / weight) if stake[i] else 0.0    # pnl / balance at entry
            pnl[i] = p
            bal += p
            open_n.pop(i, None)
            curve.append((ts, bal))
    order = sorted(pnl, key=lambda i: _epoch(trades[i]["exit_time"]))
    pnls = [pnl[i] for i in order]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    n = len(pnls)
    end_s = max(ts for ts, _ in curve)
    months = (end_s - _epoch(WINDOW_START)) / 86400 / DAYS_PER_MONTH
    net = (bal / START_BALANCE - 1) * 100.0
    # daily closed equity -> Sharpe (same maths as arena.stats.sharpe_daily, sqrt(365), rf = 0)
    days, k, last = [], 0, START_BALANCE
    d0 = int(_epoch(WINDOW_START) // 86400)
    pts = sorted(curve)
    for d in range(d0, int(end_s // 86400) + 1):
        while k < len(pts) and pts[k][0] < (d + 1) * 86400:
            last = pts[k][1]
            k += 1
        days.append(last)
    rets = [(b - a) / a for a, b in zip(days, days[1:]) if a > 0]
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (statistics.mean(rets) / statistics.stdev(rets) * math.sqrt(365)) if len(rets) > 30 and sd > 0 else None
    # trade-order Monte Carlo of the per-trade return on the balance at entry
    rng = random.Random(SEED)
    fr = [frac[i] for i in order]
    dds = []
    for _ in range(N_MC):
        rng.shuffle(fr)
        eq, path = 1.0, [1.0]
        for f in fr:
            eq *= 1.0 + f
            path.append(eq)
        dds.append(max_dd(path))
    dds.sort()
    mc95 = dds[int(0.05 * N_MC)] if dds else None
    per_coin: dict[str, int] = {}
    for t in trades:
        per_coin[t["symbol"]] = per_coin.get(t["symbol"], 0) + 1
    return {
        "trades": n, "months": months, "trades_per_month": n / months if months > 0 else None,
        "win_rate_pct": len(wins) / n * 100.0 if n else None,
        "profit_factor": (sum(wins) / -sum(losses)) if losses else None,
        "net_return_pct": net, "per_trade_ret_pct": ((bal / START_BALANCE) ** (1.0 / n) - 1) * 100.0 if n else None,
        "max_dd_pct": max_dd([v for _, v in sorted(curve)]), "mc_dd_p95_pct": mc95, "sharpe": sharpe,
        "avg_hold_days": statistics.mean(t["bars_held"] for t in trades) * tf_s / 86400 if trades else None,
        "max_gross_x": max_gross, "gross_cap_binds": cap_binds, "coins_traded": len(per_coin),
        "per_coin_trades": dict(sorted(per_coin.items())), "end_balance": bal,
    }


def time_to_30(trades: list[dict], tf_s: int, window_end_s: float) -> dict:
    """Days from a start date to the 30th closed trade and to checkpoint 1, over 52 weekly
    starts. Only NEW signals count after a start (signal bar closed after it), as in paper."""
    from src.lab.basket import rules
    w0 = _epoch(WINDOW_START)
    to30, cp1 = [], []
    for k in range(N_STARTS):
        s = w0 + k * 7 * 86400
        elig = [t for t in trades if _epoch(t["entry_time"]) + tf_s > s]
        elig.sort(key=lambda t: _epoch(t["exit_time"]))
        if len(elig) >= 30 and _epoch(elig[29]["exit_time"]) + tf_s <= window_end_s:
            to30.append((_epoch(elig[29]["exit_time"]) + tf_s - s) / 86400)
        pts = [{"symbol": t["symbol"], "entry_s": _epoch(t["entry_time"]), "exit_s": _epoch(t["exit_time"]) + tf_s}
               for t in elig if _epoch(t["exit_time"]) + tf_s <= window_end_s]
        due = rules.checkpoint_due(pts, s, 1)
        if due is not None and due["due_s"] <= window_end_s:
            cp1.append((due["due_s"] - s) / 86400)

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None
    return {"starts": N_STARTS, "reached_30": len(to30), "days_to_30_median": q(to30, 0.5),
            "days_to_30_p10": q(to30, 0.1), "days_to_30_p90": q(to30, 0.9),
            "reached_checkpoint1": len(cp1), "days_to_checkpoint1_median": q(cp1, 0.5),
            "days_to_checkpoint1_p10": q(cp1, 0.1), "days_to_checkpoint1_p90": q(cp1, 0.9)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine-commit", default=None, help="when the engine is an exported tree (git archive)")
    a = ap.parse_args(argv)
    from src.lab import engine_adapter as ea
    from src.lab.settings import get_lab_settings
    prereg = json.loads(Path(a.prereg).read_text())
    out = {"prereg_id": prereg["id"], "procedure_commit": "52dccca", "computed_at": _iso(time.time()),
           "engine_commit": a.engine_commit or ea.engine_commit(), "data_dir": get_lab_settings().data_dir,
           "window_start": WINDOW_START.replace(" ", "T") + "Z", "baskets": {}}
    for b in prereg["baskets"]:
        tf_s = TF_S[b["timeframe"]]
        t0 = time.time()
        trades, ends = [], []
        for sym in b["symbols"]:
            tr, end = run_coin(sym, b)
            trades.extend(tr)
            ends.append(end)
        end_s = min(_epoch(e) for e in ends) + tf_s
        c = compose(trades, b, tf_s)
        ttt = time_to_30(trades, tf_s, end_s)
        a_risk = b["sizing"]["mode"] == "risk"
        out["baskets"][b["name"]] = {
            **c, **ttt, "start": out["window_start"], "end": _iso(end_s), "data_end_min": min(ends),
            "data_end_max": max(ends), "runtime_s": round(time.time() - t0, 1),
            "sizing_rule": ("risk 0.25% per trade at the strategy stop, one 10k account" if a_risk
                            else "VT60 per coin x balance/28 slots, one 10k account"),
            "contaminated": not a_risk,
            "source_note": ("Donchian default chosen on data up to 2025-07-06: window is clean" if a_risk else
                            "Rosyade Basic was built on all ETH history and this window was viewed for ETH/BTC/SOL:"
                            " not clean"),
        }
        print(f"{b['name']}: {c['trades']} trades, {ttt['days_to_30_median']} d to 30, "
              f"{round(time.time() - t0, 1)} s", file=sys.stderr)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
