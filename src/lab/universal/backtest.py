"""Universal v0 portfolio simulator + metrics.

Execution model (per 4H bar t, from start to end inclusive):
  1. weights held since the previous close earn bar t's return; funding settled
     inside bar t is charged on the same weights (longs pay positive rates)
  2. weights drift with prices
  3. on a rebalance bar the target weights are computed from data <= close_t and
     traded at close_t: commission + slippage are charged on |delta weight| x equity
Trades that would change a held weight by less than min_trade_pct are skipped
(opening a new position smaller than that is skipped too). Equity <= 0 = blown.

A "trade" (for profit factor / win rate / Monte Carlo counts) is one holding
episode of one coin: from the bar its weight leaves 0 (or flips sign) until it
returns to 0 (or flips). Its PnL includes the price PnL of every bar held,
funding and the costs of every rebalance trade on that coin (entry, resizes, exit).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import strategy as S

MAX_EQUITY_POINTS = 4000


@dataclass
class SimResult:
    start: int
    end: int
    equity: np.ndarray            # equity after bar t, index t-start
    gross: np.ndarray             # gross exposure after bar t
    npos: np.ndarray
    initial: float
    contrib: np.ndarray           # N, PnL per coin (incl. costs + funding)
    fees: np.ndarray              # N, commission
    slippage: np.ndarray          # N, slippage cost
    funding: np.ndarray           # N, funding paid (+) / received (-)
    turnover: float               # sum |delta w|
    rebalances: int
    episodes: list = field(default_factory=list)
    blown: bool = False
    last_weights: Optional[np.ndarray] = None


def simulate(panel: S.Panel, feat: S.Features, p: dict, costs: dict, start: int, end: int,
             rebal: Optional[np.ndarray] = None, weight_fn=None) -> SimResult:
    """Simulate bars [start, end] (inclusive). The portfolio starts flat at the close of `start`."""
    N = panel.n
    if rebal is None:
        rebal = S.rebalance_mask(panel, p["rebalance"])
    wfn = weight_fn or (lambda t: S.target_weights(feat, panel, t, p))
    comm = float(costs.get("commission_pct", 0.05)) / 100.0
    slip = float(costs.get("slippage_pct", 0.05)) / 100.0
    use_funding = bool(costs.get("funding", True))
    min_trade = float(p.get("min_trade_pct", 0.0)) / 100.0
    E = float(p.get("initial_capital", 10000.0))
    initial = E
    w = np.zeros(N)
    L = end - start + 1
    eq, gross, npos = np.empty(L), np.empty(L), np.empty(L, dtype=int)
    contrib, fees, slp, fund = np.zeros(N), np.zeros(N), np.zeros(N), np.zeros(N)
    turnover, nreb, blown = 0.0, 0, False
    # episode state
    ep_start = np.full(N, -1)
    ep_c0 = np.zeros(N)
    ep_e0 = np.zeros(N)
    ep_side = np.zeros(N)
    ep_fee0 = np.zeros(N)
    ep_fund0 = np.zeros(N)
    episodes: list[dict] = []
    close = panel.close

    def close_episode(i: int, t: int, open_at_end: bool = False) -> None:
        s0 = int(ep_start[i])
        pnl = float(contrib[i] - ep_c0[i])
        episodes.append({
            "symbol": panel.symbols[i], "side": "long" if ep_side[i] > 0 else "short",
            "entry_idx": s0, "exit_idx": t, "entry_price": float(close[s0, i]), "exit_price": float(close[t, i]),
            "pnl": pnl, "return_on_equity_pct": pnl / ep_e0[i] * 100.0 if ep_e0[i] > 0 else 0.0,
            "fees": float(fees[i] - ep_fee0[i]), "funding": float(fund[i] - ep_fund0[i]),
            "bars_held": t - s0, "open_at_end": open_at_end,
        })
        ep_start[i] = -1

    t_last = start
    for t in range(start, end + 1):
        k = t - start
        if t > start:
            r = feat.ret[t]
            f = panel.funding[t] if use_funding else 0.0
            exp = E * w
            pnl = exp * r - exp * f
            E_new = E + float(pnl.sum())
            contrib += pnl
            fund += exp * f
            if E_new <= 0:
                blown = True
                E = 0.0
                eq[k:], gross[k:], npos[k:] = 0.0, 0.0, 0
                t_last = t
                for i in np.flatnonzero(ep_start >= 0):
                    close_episode(int(i), t, open_at_end=True)
                break
            w = w * (1.0 + r) * (E / E_new)
            E = E_new
        if rebal[t] and t < end:
            tgt = np.asarray(wfn(t), dtype=float)
            d = tgt - w
            same = (np.sign(tgt) == np.sign(w)) & (tgt != 0)
            keep = same & (np.abs(d) < min_trade)
            tgt = np.where(keep, w, tgt)
            tgt = np.where((w == 0) & (np.abs(tgt) < min_trade), 0.0, tgt)
            d = tgt - w
            traded = np.abs(d)
            if traded.sum() > 0:
                nreb += 1
                turnover += float(traded.sum())
                c_fee = E * traded * comm
                c_slip = E * traded * slip
                # close / flip episodes before charging (exit cost belongs to the closing episode)
                flip = (ep_start >= 0) & ((tgt == 0) | (np.sign(tgt) != ep_side))
                contrib -= c_fee + c_slip
                fees += c_fee
                slp += c_slip
                cost = float((c_fee + c_slip).sum())
                if flip.any():
                    # exit share of the cost: |w| part of the trade belongs to the old episode
                    exit_part = np.where(flip, np.minimum(np.abs(w), traded) / np.maximum(traded, 1e-18), 0.0)
                    entry_part = np.where(flip, 1.0 - exit_part, 0.0)
                    for i in np.flatnonzero(flip):
                        # move the entry share of this bar's cost back so the old episode only sees its exit cost
                        share = (c_fee[i] + c_slip[i]) * entry_part[i]
                        contrib[i] += share
                        fees[i] -= c_fee[i] * entry_part[i]
                        close_episode(int(i), t)
                        contrib[i] -= share
                        fees[i] += c_fee[i] * entry_part[i]
                E_pre = E
                E -= cost
                opened = (tgt != 0) & (ep_start < 0)
                for i in np.flatnonzero(opened):
                    ep_start[i] = t
                    ep_side[i] = np.sign(tgt[i])
                    ep_e0[i] = E_pre
                    # entry cost (this bar) is charged to the new episode
                    ep_c0[i] = contrib[i] + (c_fee[i] + c_slip[i]) * (1.0 if not flip[i] else entry_part[i])
                    ep_fee0[i] = fees[i] - c_fee[i] * (1.0 if not flip[i] else entry_part[i])
                    ep_fund0[i] = fund[i]
                w = tgt * (E_pre / E) if E > 0 else tgt
        eq[k] = E
        gross[k] = float(np.abs(w).sum())
        npos[k] = int(np.count_nonzero(w))
        t_last = t
    if not blown:
        for i in np.flatnonzero(ep_start >= 0):
            close_episode(int(i), end, open_at_end=True)
    return SimResult(start=start, end=t_last if blown else end, equity=eq, gross=gross, npos=npos, initial=initial,
                     contrib=contrib, fees=fees, slippage=slp, funding=fund, turnover=turnover, rebalances=nreb,
                     episodes=episodes, blown=blown, last_weights=w)


# ── metrics ──────────────────────────────────────────────────────────────

def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else v


def max_drawdown_pct(eq: np.ndarray) -> float:
    if not len(eq):
        return 0.0
    peak = np.maximum.accumulate(eq)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, (eq - peak) / peak * 100.0, -100.0)
    return float(dd.min())


def daily_returns(sim: SimResult, panel: S.Panel) -> np.ndarray:
    """Close-to-close daily returns (00:00 UTC closes) of the equity curve."""
    ts = panel.ts[sim.start: sim.start + len(sim.equity)]
    eq = np.concatenate([[sim.initial], sim.equity])
    hours = np.asarray(ts.hour)
    idx = np.flatnonzero(hours == 20) + 1  # +1 for the prepended initial point
    pts = np.concatenate([[0], idx, [len(eq) - 1]])
    pts = np.unique(pts)
    vals = eq[pts]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = vals[1:] / vals[:-1] - 1.0
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=-1.0)


def metrics(sim: SimResult, panel: S.Panel) -> dict:
    eq = sim.equity
    final = float(eq[-1]) if len(eq) else sim.initial
    eps = sim.episodes
    pnls = np.array([e["pnl"] for e in eps], dtype=float)
    gw = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    gl = float(-pnls[pnls <= 0].sum()) if len(pnls) else 0.0
    dr = daily_returns(sim, panel)
    sd = float(np.std(dr, ddof=1)) if len(dr) > 2 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(365)) if sd > 0 else None
    bars = len(eq)
    years = bars / S.BARS_PER_YEAR
    growth = final / sim.initial if sim.initial > 0 else 0.0
    cagr = (growth ** (1 / years) - 1) * 100.0 if years > 0.05 and growth > 0 else None
    return {
        "net_return_pct": _f((growth - 1.0) * 100.0),
        "cagr_pct": _f(cagr),
        "profit_factor": _f(gw / gl) if gl > 0 else None,
        "max_dd_pct": _f(max_drawdown_pct(np.concatenate([[sim.initial], eq]))),
        "trades": int(len(eps)),
        "win_rate_pct": _f(float((pnls > 0).mean() * 100.0)) if len(pnls) else None,
        "sharpe": _f(sharpe),
        "ann_vol_pct": _f(sd * math.sqrt(365) * 100.0) if sd > 0 else None,
        "liquidations": 1 if sim.blown else 0,
        "account_blown": bool(sim.blown),
        "fees_paid": _f(sim.fees.sum()),
        "slippage_paid": _f(sim.slippage.sum()),
        "funding_paid": _f(sim.funding.sum()),
        "final_equity": _f(final),
        "gross_profit": _f(gw),
        "gross_loss": _f(gl),
        "longs": sum(1 for e in eps if e["side"] == "long"),
        "shorts": sum(1 for e in eps if e["side"] == "short"),
        "turnover_per_year": _f(sim.turnover / years) if years > 0 else None,
        "avg_gross_exposure": _f(float(np.mean(sim.gross))) if bars else None,
        "avg_positions": _f(float(np.mean(sim.npos))) if bars else None,
        "time_in_market_pct": _f(float(np.mean(sim.npos > 0) * 100.0)) if bars else None,
        "rebalances": int(sim.rebalances),
        "bars": int(bars),
        "years": _f(years),
    }


def iso(ts) -> str:
    import pandas as pd
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def equity_out(sim: SimResult, panel: S.Panel, holdout_idx: Optional[int] = None,
               oos_ranges: Optional[list] = None) -> list[dict]:
    """[{t, equity, segment}] at bar CLOSE times, downsampled to MAX_EQUITY_POINTS."""
    import pandas as pd
    n = len(sim.equity)
    step = max(1, math.ceil(n / MAX_EQUITY_POINTS))
    out = []
    for k in list(range(0, n, step)) + ([n - 1] if n and (n - 1) % step else []):
        t = sim.start + k
        seg = "is"
        if holdout_idx is not None and t >= holdout_idx:
            seg = "holdout"
        elif oos_ranges and any(a <= t < b for a, b in oos_ranges):
            seg = "oos"
        out.append({"t": iso(panel.ts[t] + pd.Timedelta(hours=4)), "equity": _f(sim.equity[k]), "segment": seg})
    return out


def trades_out(sim: SimResult, panel: S.Panel) -> list[dict]:
    import pandas as pd
    out = []
    for e in sim.episodes:
        out.append({
            "symbol": e["symbol"], "side": e["side"],
            "entry_time": iso(panel.ts[e["entry_idx"]] + pd.Timedelta(hours=4)),
            "exit_time": iso(panel.ts[e["exit_idx"]] + pd.Timedelta(hours=4)),
            "entry_price": _f(e["entry_price"]), "exit_price": _f(e["exit_price"]),
            "pnl": _f(e["pnl"]), "pnl_pct": _f(e["return_on_equity_pct"]),
            "return_on_equity_pct": _f(e["return_on_equity_pct"]),
            "exit_reason": "open_at_end" if e["open_at_end"] else "rebalance",
            "fees": _f(e["fees"]), "funding": _f(e["funding"]), "bars_held": int(e["bars_held"]),
        })
    return out


def contributions(sim: SimResult, panel: S.Panel) -> list[dict]:
    rows = []
    for i, s in enumerate(panel.symbols):
        eps = [e for e in sim.episodes if e["symbol"] == s]
        if not eps and sim.contrib[i] == 0:
            continue
        wins = sum(1 for e in eps if e["pnl"] > 0)
        rows.append({
            "symbol": s, "pnl": _f(sim.contrib[i]), "pnl_pct_of_initial": _f(sim.contrib[i] / sim.initial * 100.0),
            "trades": len(eps), "win_rate_pct": _f(wins / len(eps) * 100.0) if eps else None,
            "fees": _f(sim.fees[i]), "slippage": _f(sim.slippage[i]), "funding": _f(sim.funding[i]),
            "bars_held": int(sum(e["bars_held"] for e in eps)),
            "longs": sum(1 for e in eps if e["side"] == "long"),
            "shorts": sum(1 for e in eps if e["side"] == "short"),
        })
    rows.sort(key=lambda r: -(r["pnl"] or 0.0))
    return rows


def benchmarks(panel: S.Panel, feat: S.Features, start: int, end: int) -> dict:
    """Context, not a check: BTC buy & hold and an equal-weight basket of eligible coins
    (daily rebalanced, no costs) over the same bars."""
    out: dict = {}
    b = panel.index_of("BTCUSDT")
    if b is not None and np.isfinite(panel.close[start, b]):
        px = panel.close[start: end + 1, b]
        out["btc_buy_hold"] = {"net_return_pct": _f((px[-1] / px[0] - 1.0) * 100.0),
                               "max_dd_pct": _f(max_drawdown_pct(px))}
    eq, E, w = [], 1.0, None
    hours = np.asarray(panel.ts.hour)
    for t in range(start, end + 1):
        if t > start and w is not None:
            E *= 1.0 + float(np.sum(w * feat.ret[t]))
        if t == start or hours[t] == 20:
            el = feat.eligible[t]
            w = el / el.sum() if el.sum() else np.zeros(panel.n)
        eq.append(E)
    eqa = np.array(eq)
    out["equal_weight"] = {"net_return_pct": _f((eqa[-1] - 1.0) * 100.0),
                           "max_dd_pct": _f(max_drawdown_pct(eqa))}
    return out
