"""Screener signals for the ledger.

Live (source ``screener``): once per closed hour the ``ledger_cycle`` job runs the
screener's own pipeline (``DataProcessor.process_all`` + ``ResponseBuilder``) — the
same code and labels the /screener page shows — and stores one snapshot row per coin.

Events are ONSETS only: a (coin, signal type, direction) is recorded when it becomes
active compared with the previous hourly snapshot, with a 24 h cooldown per
(coin, type, direction) so a label flickering around its threshold is not counted
over and over. The first snapshot (and the first after a gap > 3 h) is a baseline:
we don't know when those states started, so they produce no events.

Reconstruction (source ``screener_rekon``): the generator is a pure function of
market inputs, so it can be re-run causally on past data — each hour T only sees
data up to T. Binance keeps the long/short and open-interest history for ~30 days,
so the backfill covers at most that. Inputs are close but not identical to live:
24 h change from 1h candles (live: ticker), funding = last SETTLED rate (live: the
current predicted rate), top-trader L/S at 1h resolution (live: 5m), OI from the
1h history (live: current OI). It is kept as a separate source for that reason.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from ..db import dumps, loads, utcnow
from .store import ensure_schema, insert_signal, iso, kv_set, norm_symbol, to_epoch

log = logging.getLogger("lab.ledger.screener")

COOLDOWN_S = 24 * 3600
MAX_GAP_S = 3 * 3600

_DIR = {"BULLISH": 1, "BEARISH": -1, "BUY": 1, "SELL": -1}


def _d(v) -> Optional[int]:
    return _DIR.get(v) if isinstance(v, str) else None


# signal_type -> (asset state -> direction or None)
TYPE_RULES: dict[str, Callable[[dict], Optional[int]]] = {
    "komposit": lambda a: _d(a.get("signal")),
    "komposit_high": lambda a: _d(a.get("signal")) if a.get("confidence_tier") == "HIGH" else None,
    "tier_a": lambda a: 1 if a.get("tier") == "A" else None,
    "tier_c": lambda a: -1 if a.get("tier") == "C" else None,
    "momentum": lambda a: _d(a.get("momentum_signal")),
    "funding": lambda a: _d(a.get("funding_rate_signal")),
    "oi": lambda a: _d(a.get("oi_signal")),
}

STATE_FIELDS = ("signal", "tier", "confidence_tier", "confidence_pct", "momentum_signal", "funding_rate_signal",
                "oi_signal", "price", "rank", "composite_score", "change_24h", "funding_rate", "long_short_ratio")


def active_types(state: dict) -> dict[str, int]:
    out = {}
    for t, fn in TYPE_RULES.items():
        d = fn(state)
        if d in (1, -1):
            out[t] = d
    return out


def record_snapshot(conn, *, kind: str, bar: str, ts: str, states: dict[str, dict]) -> dict:
    """Store a snapshot and emit onset events against the previous snapshot of the same kind."""
    ensure_schema(conn)
    source = "screener" if kind == "live" else "screener_rekon"
    prev = conn.execute("SELECT MAX(bar) FROM ledger_screener_snapshots WHERE kind=? AND bar < ?",
                        (kind, bar)).fetchone()[0]
    baseline = prev is None or to_epoch(bar) - to_epoch(prev) > MAX_GAP_S
    prev_states: dict[str, dict] = {}
    if not baseline:
        prev_states = {r[0]: loads(r[1], {}) for r in conn.execute(
            "SELECT symbol, data_json FROM ledger_screener_snapshots WHERE kind=? AND bar=?", (kind, prev))}
    t_now = to_epoch(ts)
    events = 0
    for sym, st in states.items():
        conn.execute("INSERT OR REPLACE INTO ledger_screener_snapshots (kind, bar, symbol, data_json, created_at) "
                     "VALUES (?, ?, ?, ?, ?)", (kind, bar, sym, dumps(st), utcnow()))
        if baseline or sym not in prev_states:
            continue
        before = active_types(prev_states[sym])
        for stype, d in active_types(st).items():
            if before.get(stype) == d:
                continue
            recent = conn.execute(
                "SELECT 1 FROM ledger_signals WHERE source=? AND signal_type=? AND symbol=? AND direction=? "
                "AND ts > ? AND ts <= ? LIMIT 1", (source, stype, sym, d, iso(t_now - COOLDOWN_S), ts)).fetchone()
            if recent:
                continue
            meta = {k: st.get(k) for k in ("signal", "tier", "confidence_tier", "confidence_pct", "rank",
                                            "composite_score") if st.get(k) is not None}
            meta["bar"] = bar
            ok = insert_signal(conn, source=source, signal_type=stype, symbol=sym, direction=d, ts=ts,
                               ref=f"screener:{kind}", price=st.get("price"), meta=meta,
                               dedupe_key=f"{source}|{stype}|{sym}|{bar}|{d}")
            events += int(ok)
    conn.commit()
    return {"bar": bar, "coins": len(states), "events": events, "baseline": baseline}


def states_from_frame(df) -> dict[str, dict]:
    """ProcessedResult.data -> {BTCUSDT: state} using the screener's own ResponseBuilder labels."""
    from src.services.response_builder import ResponseBuilder
    assets = ResponseBuilder()._build_assets_list(df)
    out = {}
    for a in assets:
        d = a.model_dump()
        out[norm_symbol(d["symbol"])] = {k: d.get(k) for k in STATE_FIELDS}
    return out


# ── live ─────────────────────────────────────────────────────────────────

def live_snapshot(conn, bar: str, ts: Optional[str] = None, processor=None) -> dict:
    """Run the screener pipeline once and record it. ``processor`` is injectable for tests."""
    import asyncio
    ts = ts or iso(time.time())
    close = None
    if processor is None:
        from src.config.settings import Settings
        from src.services.data_processor import DataProcessor
        settings = Settings()
        if settings.mock_mode:
            return {"skipped": "SCREENER_MOCK_MODE is on — synthetic data is not recorded"}
        processor = DataProcessor(settings)
        close = processor.close
    try:
        res = asyncio.run(processor.process_all())
    finally:
        if close:
            close()
    if res.data is None or len(res.data) == 0:
        return {"error": f"screener returned no data ({len(res.errors)} errors)"}
    out = record_snapshot(conn, kind="live", bar=bar, ts=ts, states=states_from_frame(res.data))
    if conn.execute("SELECT value FROM lab_kv WHERE key='ledger_live_since'").fetchone() is None:
        kv_set(conn, "ledger_live_since", ts)
        conn.commit()
    out["fetch_errors"] = len(res.errors)
    return out


# ── reconstruction ───────────────────────────────────────────────────────

def run_pipeline(df):
    """Stages 3–5 of DataProcessor.process_all (signals → scores → ranking), synchronously,
    calling the same modules in the same order."""
    from src.ranking.engine import RankingEngine
    from src.signals.generator import SignalGenerator
    from src.signals.ic_weights import ICWeightCalculator
    from src.signals.scorer import MultiFactorScorer
    g = SignalGenerator()
    df["reversal_signal"] = g.calculate_reversal_signal(df)
    df["momentum_signal"] = g.calculate_momentum_signal(df)
    df["funding_rate_signal"] = g.calculate_funding_rate_signal(df)
    df["sentiment_signal"] = g.calculate_sentiment_signal(df)
    df["oi_momentum_signal"] = g.calculate_oi_momentum_signal(df)
    for c in ("reversal_signal", "momentum_signal", "funding_rate_signal", "sentiment_signal", "oi_momentum_signal"):
        df[c] = g.normalize_signal(df[c])
    scorer = MultiFactorScorer(ICWeightCalculator())
    df["multi_factor_score"] = scorer.calculate_score(df)
    df = scorer.calculate_risk_adjusted_score(df)
    df["tier"] = scorer.classify_tiers(df["risk_adjusted_score"] if "risk_adjusted_score" in df.columns
                                       else df["multi_factor_score"])
    df = scorer.calculate_position_sizing(df)
    df = scorer.calculate_confidence_rate(df)
    return RankingEngine().rank_assets(df, "risk_adjusted_score")


def _last_le(series: list[dict], t_ms: int) -> Optional[dict]:
    """Latest point with ts <= t_ms (series sorted ascending)."""
    import bisect
    keys = [p["ts"] for p in series]
    i = bisect.bisect_right(keys, t_ms) - 1
    return series[i] if i >= 0 else None


_FETCHER_CLS = None


def _hist_fetcher(daily: list[list]):
    """MarketDataFetcher whose daily OHLCV is the reconstruction as of time T, so momentum,
    ATR and MA50 are computed by the screener's own methods."""
    global _FETCHER_CLS
    if _FETCHER_CLS is None:
        from src.data.fetcher import MarketDataFetcher

        class _F(MarketDataFetcher):
            def fetch_ohlcv(self, symbol, timeframe="1d", limit=30):
                return self._daily[-limit:] if limit else list(self._daily)

        _FETCHER_CLS = _F
    f = _FETCHER_CLS(None, [], memoize=False)
    f._daily = daily
    return f


def build_record(sym: str, T: int, data: dict) -> Optional[dict]:
    """Screener input record for ``sym`` as of hour close T (epoch s), using only data <= T."""
    import math
    nan = math.nan
    h1 = data["1h"]                       # closed 1h bars, sorted
    T_ms = T * 1000
    bars = [b for b in h1 if b["ts"] + 3_600_000 <= T_ms]
    if len(bars) < 25 or bars[-1]["ts"] != T_ms - 3_600_000:
        return None
    price = bars[-1]["c"]
    ago = next((b for b in reversed(bars) if b["ts"] + 3_600_000 <= T_ms - 86_400_000), None)
    change = (price / ago["c"] - 1.0) * 100.0 if ago and ago["c"] else nan
    vol = sum(b["v"] * b["c"] for b in bars if b["ts"] >= T_ms - 86_400_000)
    day0 = T_ms - T_ms % 86_400_000
    daily = [[b["ts"], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in data["1d"] if b["ts"] + 86_400_000 <= day0]
    today = [b for b in bars if b["ts"] >= day0]
    if today:
        daily.append([day0, today[0]["o"], max(b["h"] for b in today), min(b["l"] for b in today), price,
                      sum(b["v"] for b in today)])
    else:   # T is exactly 00:00 UTC: the new daily candle has just opened
        daily.append([day0, price, price, price, price, 0.0])
    f = _hist_fetcher(daily)
    mom = f.calculate_momentum_30d(sym)
    atr = f.calculate_atr(sym).get("atr_percent")
    ma = f.calculate_distance_to_ma50(sym).get("distance_percent")
    fr = _last_le(data["funding"], T_ms)
    ls = _last_le(data["ls"], T_ms)
    oi_now = _last_le(data["oi"], T_ms)
    oi_ago = _last_le(data["oi"], T_ms - 86_400_000)
    oi_delta = nan
    if oi_now and oi_ago and oi_ago["v"] and T_ms - oi_now["ts"] <= 7_200_000 and \
            T_ms - 86_400_000 - oi_ago["ts"] <= 7_200_000:
        oi_delta = (oi_now["v"] / oi_ago["v"] - 1.0) * 100.0
    return {
        "symbol": sym, "price": price, "change_24h": change, "volume_24h": vol, "open_interest": nan,
        "funding_rate": fr["rate"] * 100.0 if fr else nan,
        "long_short_ratio": ls["v"] if ls and T_ms - ls["ts"] <= 7_200_000 else nan,
        "momentum_30d": mom if mom is not None else nan,
        "atr_percent": atr if atr is not None else nan,
        "distance_to_ma50": ma if ma is not None else nan,
        "sparkline_data": None, "sparkline_trend": "neutral",
        "oi_delta_percent": oi_delta, "oi_interpretation": "neutral",
    }


def fetch_history(symbols: list[str], start_s: int, end_s: int, api=None, progress=None) -> dict[str, dict]:
    """All reconstruction inputs per coin (public endpoints). ``api`` = module like ledger.binance."""
    if api is None:
        from . import binance as api
    out = {}
    for k, sym in enumerate(symbols):
        try:
            a, b = start_s * 1000, end_s * 1000
            out[sym] = {
                "1h": api.klines(sym, "1h", a - 26 * 3_600_000, b),
                "1d": api.klines(sym, "1d", a - 70 * 86_400_000, b),
                "funding": api.funding(sym, a - 3 * 86_400_000, b),
                "ls": api.long_short_hist(sym, a - 3 * 3_600_000, b),
                "oi": api.open_interest_hist(sym, a - 27 * 3_600_000, b),
            }
        except Exception as e:  # noqa: BLE001
            log.warning("rekon: history for %s failed: %s", sym, e)
        if progress:
            progress("data", k + 1, len(symbols))
    return out


def reconstruct(conn, symbols: list[str], start_s: int, end_s: int, history: dict[str, dict],
                progress=None) -> dict:
    """Replay hourly snapshots T = start..end (hour closes) through the screener pipeline."""
    import pandas as pd
    for name in ("src.signals", "src.ranking", "src.data.fetcher", "src.signals.scorer", "src.signals.generator",
                 "src.signals.ic_weights", "src.ranking.engine"):
        logging.getLogger(name).setLevel(logging.ERROR)
    hours = list(range(start_s - start_s % 3600, end_s + 1, 3600))
    events = snaps = 0
    for k, T in enumerate(hours):
        recs = [r for sym in symbols if sym in history for r in [build_record(sym, T, history[sym])] if r]
        if len(recs) < 5:
            continue
        df = run_pipeline(pd.DataFrame(recs))
        res = record_snapshot(conn, kind="rekon", bar=iso(T), ts=iso(T), states=states_from_frame(df))
        events += res["events"]
        snaps += 1
        if progress and k % 24 == 0:
            progress("replay", k + 1, len(hours))
    return {"hours": snaps, "events": events, "from": iso(hours[0]) if hours else None,
            "to": iso(hours[-1]) if hours else None}
