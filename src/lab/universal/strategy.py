"""Universal v0 signals: panel of 4H closes -> features -> target weights.

Everything is causal: the value at bar t uses closes up to and including bar t
only. A decision taken at the close of bar t earns bar t+1's return.
Works with pandas 2.x (screener venv) and 3.x (engine venv).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

BAR_S = 4 * 3600
BARS_PER_DAY = 6
BARS_PER_YEAR = BARS_PER_DAY * 365


@dataclass
class Panel:
    ts: "object"              # pandas DatetimeIndex (UTC), regular 4H grid
    symbols: list[str]
    close: np.ndarray         # T x N, forward-filled after listing, NaN before
    present: np.ndarray       # T x N bool, a real bar exists at t (not forward-filled)
    funding: np.ndarray       # T x N, sum of funding rates settled in (open_t, close_t]
    first_idx: np.ndarray     # N, first bar index with data (T if none)
    quote_volume: Optional[np.ndarray] = None  # T x N quote (USDT) volume per bar, NaN where no real bar
    funding_n: Optional[np.ndarray] = None     # T x N number of settlements binned into each bar

    @property
    def n(self) -> int:
        return len(self.symbols)

    def index_of(self, symbol: str) -> Optional[int]:
        try:
            return self.symbols.index(symbol)
        except ValueError:
            return None


def build_panel(ohlcv: dict, funding: Optional[dict] = None, end=None) -> Panel:
    """ohlcv: {symbol: DataFrame[timestamp, close, ...]}; funding: {symbol: DataFrame[timestamp, funding_rate]}."""
    import pandas as pd
    syms = sorted(s for s, df in ohlcv.items() if df is not None and len(df))
    if not syms:
        raise ValueError("no price data for the universe")
    series, qvol = {}, {}
    for s in syms:
        df = ohlcv[s]
        ts = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
        px = df["close"].astype(float).to_numpy()
        series[s] = pd.Series(px, index=ts).groupby(level=0).last()
        if "quote_volume" in df.columns:
            qv = df["quote_volume"].astype(float).to_numpy()
        elif "volume" in df.columns:  # base volume x close is a close enough proxy for ranking
            qv = df["volume"].astype(float).to_numpy() * px
        else:
            qv = None
        if qv is not None:
            qvol[s] = pd.Series(qv, index=ts).groupby(level=0).last()
    lo = min(x.index[0] for x in series.values())
    hi = max(x.index[-1] for x in series.values())
    if end is not None:
        hi = min(hi, pd.Timestamp(end).tz_convert("UTC") if pd.Timestamp(end).tzinfo else
                 pd.Timestamp(end).tz_localize("UTC"))
    grid = pd.date_range(lo.floor("4h"), hi, freq="4h", tz="UTC")
    T, N = len(grid), len(syms)
    raw = np.full((T, N), np.nan)
    qv = np.full((T, N), np.nan) if qvol else None
    for j, s in enumerate(syms):
        raw[:, j] = series[s].reindex(grid).to_numpy(dtype=float)
        if qv is not None and s in qvol:
            qv[:, j] = qvol[s].reindex(grid).to_numpy(dtype=float)
    present = np.isfinite(raw)
    close = pd.DataFrame(raw).ffill().to_numpy()
    first_idx = np.array([int(np.argmax(present[:, j])) if present[:, j].any() else T for j in range(N)])
    fund = np.zeros((T, N))
    fund_n = np.zeros((T, N), dtype=np.int32)
    if funding:
        for j, s in enumerate(syms):
            f = funding.get(s)
            if f is None or not len(f):
                continue
            t = pd.to_datetime(f["timestamp"], utc=True)
            rel = (t - grid[0]).dt.total_seconds().to_numpy(dtype=float) / BAR_S
            # settlement at time x belongs to the bar with open < x <= open + 4h
            idx = np.ceil(rel).astype("int64") - 1
            rates = f["funding_rate"].astype(float).to_numpy()
            ok = (idx >= 0) & (idx < T) & np.isfinite(rates)
            np.add.at(fund[:, j], idx[ok], rates[ok])
            np.add.at(fund_n[:, j], idx[ok], 1)
    return Panel(ts=grid, symbols=syms, close=close, present=present, funding=fund, first_idx=first_idx,
                 quote_volume=qv, funding_n=fund_n)


def slice_panel(p: Panel, end_excl: int) -> Panel:
    """Bars [0, end_excl) only — used to make the development segment physically holdout-free."""
    return Panel(ts=p.ts[:end_excl], symbols=list(p.symbols), close=p.close[:end_excl],
                 present=p.present[:end_excl], funding=p.funding[:end_excl],
                 first_idx=np.minimum(p.first_idx, end_excl),
                 quote_volume=None if p.quote_volume is None else p.quote_volume[:end_excl],
                 funding_n=None if p.funding_n is None else p.funding_n[:end_excl])


def subset_panel(p: Panel, idx) -> Panel:
    """Columns `idx` only (same bars)."""
    idx = list(idx)
    return Panel(ts=p.ts, symbols=[p.symbols[i] for i in idx], close=p.close[:, idx], present=p.present[:, idx],
                 funding=p.funding[:, idx], first_idx=p.first_idx[idx],
                 quote_volume=None if p.quote_volume is None else p.quote_volume[:, idx],
                 funding_n=None if p.funding_n is None else p.funding_n[:, idx])


@dataclass
class Features:
    score: np.ndarray       # composite vol-adjusted momentum
    mom: dict               # {days: T x N log return}
    vol_ann: np.ndarray     # annualised realised vol (fraction)
    ema: np.ndarray
    up: np.ndarray
    down: np.ndarray
    eligible: np.ndarray
    logret: np.ndarray      # bar log returns (NaN where undefined)
    ret: np.ndarray         # bar simple returns (0 where undefined)
    in_universe: Optional[np.ndarray] = None  # universe_mode=liquidity: T x N top-K by trailing quote volume


def liquidity_universe(panel: Panel, base_ok: np.ndarray, days: int, k: int) -> np.ndarray:
    """T x N bool: at each bar, the k coins with the largest trailing `days` quote volume among the
    coins in `base_ok` (history/data requirements already met). Causal: uses bars <= t only.
    A coin needs >= 80% of the window with real bars to be ranked at all."""
    import pandas as pd
    T, N = base_ok.shape
    if panel.quote_volume is None:
        raise ValueError("universe_mode=liquidity needs volume data in the panel")
    w = int(days) * BARS_PER_DAY
    qv = pd.DataFrame(np.where(panel.present, np.nan_to_num(panel.quote_volume, nan=0.0), np.nan))
    liq = qv.rolling(w, min_periods=max(1, int(w * 0.8))).sum().to_numpy()
    traded_now = np.nan_to_num(panel.quote_volume, nan=0.0) > 0  # zero-volume (halted/settled) bars don't count
    ok = base_ok & traded_now & np.isfinite(liq) & (liq > 0)
    key = np.where(ok, liq, -np.inf)
    order = np.argsort(-key, axis=1, kind="stable")
    rank = np.empty_like(order)
    rank[np.arange(T)[:, None], order] = np.arange(N)[None, :]
    return ok & (rank < int(k))


def compute_features(panel: Panel, p: dict) -> Features:
    import pandas as pd
    close = panel.close
    with np.errstate(divide="ignore", invalid="ignore"):
        logp = np.log(close)
    lp = pd.DataFrame(logp)
    lr = lp.diff()
    vw = int(p["vol_days"]) * BARS_PER_DAY
    sigma = lr.rolling(vw, min_periods=max(2, int(vw * 0.8))).std().to_numpy()
    moms, scores = {}, []
    for key in ("mom_short_days", "mom_mid_days", "mom_long_days"):
        d = int(p[key])
        h = d * BARS_PER_DAY
        m = (lp - lp.shift(h)).to_numpy()
        moms[d] = m
        with np.errstate(divide="ignore", invalid="ignore"):
            scores.append(m / (sigma * np.sqrt(h)))
    score = np.mean(np.stack(scores), axis=0)
    span = int(p["trend_ema_days"]) * BARS_PER_DAY
    ema = pd.DataFrame(close).ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()
    with np.errstate(invalid="ignore"):
        up = (close > ema) & np.isfinite(ema)
        down = (close < ema) & np.isfinite(ema)
    vol_ann = sigma * np.sqrt(BARS_PER_YEAR)
    T = close.shape[0]
    age = np.arange(T)[:, None] - panel.first_idx[None, :]
    eligible = ((age >= int(p["min_history_days"]) * BARS_PER_DAY) & np.isfinite(score) & np.isfinite(vol_ann)
                & (vol_ann > 0) & panel.present)
    in_univ = None
    if p.get("universe_mode", "static") == "liquidity":
        in_univ = liquidity_universe(panel, eligible, int(p.get("liquidity_days", 30)),
                                     int(p.get("universe_size", 30)))
        eligible = eligible & in_univ
    lrn = lr.to_numpy()
    ret = np.nan_to_num(np.expm1(lrn), nan=0.0, posinf=0.0, neginf=0.0)
    return Features(score=score, mom=moms, vol_ann=vol_ann, ema=ema, up=up, down=down, eligible=eligible,
                    logret=lrn, ret=ret, in_universe=in_univ)


def rebalance_mask(panel: Panel, rebalance: str):
    """True on bars whose CLOSE is a rebalance time ('4h': every bar; '1d': close at 00:00 UTC)."""
    if rebalance == "4h":
        return np.ones(len(panel.ts), dtype=bool)
    hours = np.asarray(panel.ts.hour)
    return hours == 20  # bar opening 20:00 closes at 00:00 UTC


def select(feat: Features, panel: Panel, t: int, p: dict) -> tuple[list[int], list[int]]:
    """Indices chosen for long / short at bar t (before sizing)."""
    elig = feat.eligible[t]
    s = feat.score[t]
    long_ok = short_ok = True
    if p.get("regime_filter"):
        b = panel.index_of("BTCUSDT")
        if b is not None:
            long_ok, short_ok = bool(feat.up[t, b]), bool(feat.down[t, b])
        # no BTC in the universe -> filter has nothing to look at (documented)
    longs: list[int] = []
    shorts: list[int] = []
    if long_ok:
        cand = elig & (s > 0)
        if p.get("require_trend", True):
            cand &= feat.up[t]
        idx = np.flatnonzero(cand)
        longs = [int(i) for i in idx[np.argsort(-s[idx], kind="stable")][: int(p["top_n"])]]
    if p.get("allow_short") and short_ok:
        cand = elig & (s < 0)
        if p.get("require_trend", True):
            cand &= feat.down[t]
        idx = [i for i in np.flatnonzero(cand) if i not in longs]
        idx = np.array(idx, dtype=int)
        shorts = [int(i) for i in idx[np.argsort(s[idx], kind="stable")][: int(p["bottom_n"])]]
    return longs, shorts


def size(feat: Features, t: int, longs: list[int], shorts: list[int], p: dict, n: int) -> np.ndarray:
    """Inverse-vol weights scaled to the portfolio vol target, then capped."""
    w = np.zeros(n)
    for side, sel, slots in ((1.0, longs, int(p["top_n"])), (-1.0, shorts, int(p["bottom_n"]))):
        if not sel:
            continue
        inv = 1.0 / feat.vol_ann[t, sel]
        w[sel] = side * inv / inv.sum() * (len(sel) / max(1, slots))
    sel = np.flatnonzero(w)
    if not len(sel):
        return w
    cw = int(p["cov_days"]) * BARS_PER_DAY
    win = np.nan_to_num(feat.logret[max(0, t - cw + 1): t + 1][:, sel], nan=0.0)
    if len(win) >= 10:
        cov = np.atleast_2d(np.cov(win, rowvar=False)) * BARS_PER_YEAR
        pv = float(np.sqrt(max(w[sel] @ cov @ w[sel], 0.0)))
    else:
        pv = float(np.sqrt(np.sum((w[sel] * feat.vol_ann[t, sel]) ** 2)))
    if pv > 0:
        w *= (float(p["target_vol_pct"]) / 100.0) / pv
    cap = float(p["max_weight_pct"]) / 100.0
    w = np.clip(w, -cap, cap)
    gross = float(np.abs(w).sum())
    mg = float(p["max_gross"])
    if gross > mg:
        w *= mg / gross
    return w


def target_weights(feat: Features, panel: Panel, t: int, p: dict) -> np.ndarray:
    longs, shorts = select(feat, panel, t, p)
    return size(feat, t, longs, shorts, p, panel.n)


def last_complete_index(panel: Panel, frac: float = 0.8, lookback: int = 60) -> int:
    """Last bar where at least `frac` of the coins that recently had data have a real bar.
    Guards against a partially refreshed cache (one coin a bar ahead of the rest)."""
    cnt = panel.present.sum(axis=1)
    T = len(cnt)
    ref = int(cnt[max(0, T - lookback):].max()) if T else 0
    ok = np.flatnonzero(cnt >= max(1, int(np.ceil(frac * ref))))
    return int(ok[-1]) if len(ok) else T - 1


def first_tradable_index(feat: Features, p: dict) -> int:
    """First bar with at least min_universe eligible coins."""
    cnt = feat.eligible.sum(axis=1)
    ok = np.flatnonzero(cnt >= int(p["min_universe"]))
    if not len(ok):
        raise ValueError(f"never {p['min_universe']} eligible coins at once — universe too small or too young")
    return int(ok[0])
