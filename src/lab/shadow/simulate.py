"""Shadow execution maths (stdlib, pure apart from the injected ``market``).

Conventions: ``d`` = +1 when the order buys, -1 when it sells. Every bps figure is
signed so that POSITIVE = good for us, except ``slippage/drift/impact`` which are
COSTS (positive = paid more than the reference).

Limit placement: at the alert arrival, price ``L = close - d * k * ATR``. k > 0 rests
further on the passive side; k < 0 sits on the aggressive side of the close and is
rejected as post-only (Binance GTX) when it would cross the first public trade
after arrival (our proxy for the touch).

Fill rule: TRADE-THROUGH only, i.e. a public trade strictly better than L
(buy: p < L, sell: p > L). Trades AT L are ignored, so an unknown queue position
never flatters the result. 1m klines locate the first minute whose extreme goes
through L; aggTrades of that minute give the exact trade. Without trades for the
placement minute (vision file not out yet), the whole placement minute counts and
fill times fall back to the minute open (``data_basis = klines_1m``, optimistic).

Policy per time-to-live (ttl): rest the limit for ttl minutes, then chase with a
market order at the price at expiry.
  filled    saving = d * (ref - L) / ref + (taker - maker) fee difference
  missed    saving = -d * (end - ref) / ref   (chasing: both legs pay taker)
  postonly  saving = 0                       (rejected, market order straight away)
``ref`` = the actual market fill from trade_logs when there is one, else the first
public trade after arrival (``ref_basis = proxy``: no own slippage on top).
"""
from __future__ import annotations

from typing import Optional

from ..ledger.store import iso
from .market import TF_MS, Unavailable

MIN_MS = 60_000


def bps(x: float, ref: float) -> float:
    return x / ref * 1e4


def atr(bars: list[dict], n: int = 14) -> Optional[float]:
    """Wilder ATR over ``bars`` (oldest first); None when fewer than n + 1 bars."""
    if len(bars) < n + 1:
        return None
    trs = [max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])) for p, b in zip(bars, bars[1:])]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def limit_price(close: float, d: int, k: float, atr_v: float) -> float:
    return close - d * k * atr_v


def _through(d: int, px: float, lim: float) -> bool:
    return d * (lim - px) > 0


def _bar_through(d: int, bar: dict, lim: float) -> bool:
    return _through(d, bar["l"] if d > 0 else bar["h"], lim)


def signal_bar(market, symbol: str, tf: str, bar_close_ms: int, n_atr: int = 14) -> tuple[Optional[float], Optional[float]]:
    """(close of the bar that closed at bar_close_ms, ATR(n) at that bar)."""
    step = TF_MS[tf]
    bars = market.klines(symbol, tf, bar_close_ms - (n_atr + 30) * step, bar_close_ms)
    bars = [b for b in bars if b["ts"] + step <= bar_close_ms]
    if not bars or bars[-1]["ts"] + step != bar_close_ms:
        return None, None
    return bars[-1]["c"], atr(bars, n_atr)


def evaluate(sig: dict, market, ks: tuple, ttls_min: tuple, fee_diff_bps: float, now_ms: int) -> dict:
    """Actual execution quality + shadow limit outcomes for one signal.

    ``sig``: symbol, trade_dir, tf, bar_close_s, arrival_s, fill_price, fill_s.
    Returns {"actual": {...}, "results": [...], "complete": bool, "status": str}.
    """
    d, sym = int(sig["trade_dir"]), sig["symbol"]
    bar_close_ms = int(sig["bar_close_s"] * 1000)
    place = int(sig["arrival_s"] * 1000)
    close, atr_v = signal_bar(market, sym, sig["tf"], bar_close_ms)
    if close is None:
        return {"status": "no_data", "error": "signal bar not available", "actual": {}, "results": [],
                "complete": now_ms - bar_close_ms > 3 * 86_400_000}

    max_ttl = max(ttls_min)
    horizon_end = place + max_ttl * MIN_MS
    m0 = place // MIN_MS * MIN_MS
    kl = market.klines(sym, "1m", m0, max(min(horizon_end + MIN_MS, now_ms), m0 + MIN_MS))

    agg0: Optional[list] = None
    try:
        agg0 = market.agg_trades(sym, [(place, m0 + MIN_MS)])[(place, m0 + MIN_MS)]
    except Unavailable:
        agg0 = None
    if agg0:
        p0, p0_basis = agg0[0][1], "aggtrades"
    elif kl:
        p0, p0_basis = (kl[0]["c"] if kl[0]["ts"] == m0 else kl[0]["o"]), "klines_1m"
    else:
        return {"status": "pending", "error": "no 1m data yet", "actual": {}, "results": [], "complete": False}

    fill = sig.get("fill_price")
    actual = {
        "bar_close_px": close, "atr": atr_v, "p0": p0, "p0_basis": p0_basis,
        "latency_s": sig["arrival_s"] - sig["bar_close_s"],
        "drift_bps": d * bps(p0 - close, close),
        "slippage_bps": d * bps(fill - close, close) if fill else None,
        "impact_bps": d * bps(fill - p0, p0) if fill else None,
        "exec_latency_s": sig["fill_s"] - sig["arrival_s"] if sig.get("fill_s") else None,
    }
    ref, ref_basis = (fill, "fill") if fill else (p0, "proxy")
    if atr_v is None:
        return {"status": "no_data", "error": "ATR not available", "actual": actual, "results": [],
                "complete": True}

    # first trade-through per k: placement-minute trades, then 1m bars, then refine the minute
    later = [b for b in kl if b["ts"] >= (m0 + MIN_MS if agg0 is not None else m0)]
    first: dict[float, Optional[int]] = {}
    basis: dict[float, str] = {}
    minutes: dict[float, int] = {}
    for k in ks:
        lim = limit_price(close, d, k, atr_v)
        if d * (lim - p0) > 0:
            first[k] = None
            basis[k] = "postonly"
            continue
        hit = next((t for t, px in (agg0 or []) if _through(d, px, lim)), None)
        if hit is not None:
            first[k], basis[k] = hit, "aggtrades"
            continue
        bar = next((b for b in later if _bar_through(d, b, lim)), None)
        if bar is None:
            first[k], basis[k] = None, ("aggtrades" if agg0 is not None else "klines_1m")
        else:
            minutes[k] = bar["ts"]
    if minutes:
        wins = sorted({(max(t, place), t + MIN_MS) for t in minutes.values()})
        try:
            trades = market.agg_trades(sym, wins)
        except Unavailable:
            trades = None
        for k, t in minutes.items():
            lim = limit_price(close, d, k, atr_v)
            w = (max(t, place), t + MIN_MS)
            hit = next((ts for ts, px in trades[w] if _through(d, px, lim)), None) if trades else None
            if hit is not None:
                first[k], basis[k] = hit, "aggtrades"
            else:                       # no trades (yet): the kline says it went through in this minute
                first[k], basis[k] = max(t, place), "klines_1m"

    results = []
    done_ttls = 0
    for ttl in ttls_min:
        end = place + ttl * MIN_MS
        if end + MIN_MS > now_ms:           # window not over yet (+1 min for the last bar to settle)
            continue
        done_ttls += 1
        window = [b for b in kl if b["ts"] < end]
        closed = [b for b in window if b["ts"] + MIN_MS <= end]
        end_px = closed[-1]["c"] if closed else p0
        ext = [b["h"] if d > 0 else b["l"] for b in window if b["ts"] >= m0] or [p0]
        run_max = max(d * bps(x - ref, ref) for x in ext + [p0])
        for k in ks:
            lim = limit_price(close, d, k, atr_v)
            ft = first.get(k)
            if basis[k] == "postonly":
                outcome, saving, ttf = "postonly", 0.0, None
            elif ft is not None and ft < end:
                outcome, ttf = "filled", (ft - place) / 1000.0
                saving = d * bps(ref - lim, ref) + fee_diff_bps
            else:
                outcome, ttf = "missed", None
                saving = -d * bps(end_px - ref, ref)
            results.append({
                "k": k, "ttl_min": ttl, "limit_px": lim, "outcome": outcome,
                "fill_ts": iso(ft / 1000) if outcome == "filled" else None, "time_to_fill_s": ttf,
                "price_diff_bps": d * bps(ref - lim, ref), "saving_bps": saving, "end_px": end_px,
                "runaway_end_bps": d * bps(end_px - ref, ref), "runaway_max_bps": run_max,
                "ref_px": ref, "ref_basis": ref_basis,
                "data_basis": p0_basis if basis[k] == "postonly" else basis[k],
            })
    complete = done_ttls == len(ttls_min)
    return {"status": "done" if complete else "partial", "error": None, "actual": actual, "results": results,
            "complete": complete}
