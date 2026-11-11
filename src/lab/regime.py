"""Market regime: a causal label (naik / turun / datar) for BTC and ETH.

Rule (daily closed bars only, documented in RULE and returned by the API):

  EMA50 / EMA200 of the daily close, slope = EMA50 change over SLOPE_DAYS days.
    naik   close > EMA200  and  EMA50 > EMA200  and  slope > 0
    turun  close < EMA200  and  EMA50 < EMA200  and  slope < 0
    datar  anything else (mixed signals, a transition or a sideways market)

The label of day D uses data up to D's close only, and is "valid" from D's close
onward: a trade that entered at time T is classified with the label of the last
daily bar that had CLOSED by T (``label_at``). No look-ahead.

Used by the Outlook job (per-preset performance by regime) and served by
``GET /api/v1/lab/regime`` from the cached JSON in lab_kv (key ``regime``).
The compute functions need pandas (engine / job side); ``load`` is stdlib only.
"""
from __future__ import annotations

import bisect
from typing import Any, Iterable, Optional

EMA_FAST = 50
EMA_SLOW = 200
SLOPE_DAYS = 10
LABELS = ("naik", "turun", "datar")
LABEL_TEXT = {"naik": "Pasar naik", "turun": "Pasar turun", "datar": "Pasar datar / transisi"}
RULE = (f"Harian, hanya candle yang sudah close. naik = close > EMA{EMA_SLOW}, EMA{EMA_FAST} > EMA{EMA_SLOW} "
        f"dan EMA{EMA_FAST} naik dalam {SLOPE_DAYS} hari; turun = kebalikannya; datar = selain itu. "
        "Label hari D baru berlaku setelah candle D close (tanpa melihat masa depan).")
KV_KEY = "regime"
MIN_TRADES = 5  # fewer trades in a regime bucket -> flagged as too small to read


def _iso(ts) -> str:
    import pandas as pd
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(close: float, ema_fast: float, ema_slow: float, slope: float) -> str:
    if any(v is None or v != v for v in (close, ema_fast, ema_slow, slope)):
        return "datar"
    if close > ema_slow and ema_fast > ema_slow and slope > 0:
        return "naik"
    if close < ema_slow and ema_fast < ema_slow and slope < 0:
        return "turun"
    return "datar"


def label_series(daily) -> list[dict]:
    """Per CLOSED daily bar: {t (bar open), valid_from (bar close), close, ema50, ema200, slope_pct, label}.

    ``daily``: DataFrame with timestamp (UTC bar open) and close, closed bars only.
    Bars before EMA_SLOW days of history are labelled ``datar`` with ``warmup=True``.
    """
    import pandas as pd
    df = daily[["timestamp", "close"]].dropna().reset_index(drop=True)
    c = df["close"].astype(float)
    ef = c.ewm(span=EMA_FAST, adjust=False).mean()
    es = c.ewm(span=EMA_SLOW, adjust=False).mean()
    slope = (ef / ef.shift(SLOPE_DAYS) - 1.0) * 100.0
    out = []
    for i in range(len(df)):
        warm = i < EMA_SLOW
        lab = "datar" if warm else classify(float(c[i]), float(ef[i]), float(es[i]), float(slope[i]))
        t = pd.Timestamp(df["timestamp"][i])
        out.append({"t": _iso(t), "valid_from": _iso(t + pd.Timedelta(days=1)), "close": float(c[i]),
                    "ema_fast": float(ef[i]), "ema_slow": float(es[i]),
                    "slope_pct": None if slope[i] != slope[i] else float(slope[i]), "label": lab, "warmup": warm})
    return out


class RegimeIndex:
    """Fast causal lookup: label in force at an ISO time (or None before the first label)."""

    def __init__(self, series: list[dict]):
        rows = [r for r in series if not r.get("warmup")]
        self._keys = [r["valid_from"] for r in rows]
        self._labels = [r["label"] for r in rows]

    def label_at(self, iso_ts: Optional[str]) -> Optional[str]:
        if not iso_ts or not self._keys:
            return None
        k = bisect.bisect_right(self._keys, iso_ts[:19] + "Z") - 1
        return self._labels[k] if k >= 0 else None


def current(series: list[dict], symbol: str) -> dict:
    if not series:
        return {"symbol": symbol, "label": None, "label_text": "tidak tersedia", "available": False}
    r = series[-1]
    dist = (r["close"] / r["ema_slow"] - 1.0) * 100.0 if r["ema_slow"] else None
    # how long the current label has been in force (consecutive daily bars)
    days = 0
    for x in reversed(series):
        if x["label"] != r["label"] or x.get("warmup"):
            break
        days += 1
    return {
        "symbol": symbol, "available": not r.get("warmup"), "label": r["label"], "label_text": LABEL_TEXT[r["label"]],
        "as_of": r["valid_from"], "close": r["close"], "ema_fast": r["ema_fast"], "ema_slow": r["ema_slow"],
        "slope_pct": r["slope_pct"], "dist_ema_slow_pct": dist, "days_in_label": days,
        "inputs": {
            "close_above_ema_slow": r["close"] > r["ema_slow"],
            "ema_fast_above_slow": r["ema_fast"] > r["ema_slow"],
            "ema_fast_rising": (r["slope_pct"] or 0) > 0,
        },
        "history": [{"t": x["t"], "label": x["label"]} for x in series[-90:] if not x.get("warmup")],
    }


def perf_by_regime(trades: Iterable[dict], idx: RegimeIndex) -> dict:
    """{side: {label: {n, win_rate_pct, mean_pct, sum_pct}}} on net pnl % of notional per trade.

    A trade is classified by the regime in force at its ENTRY time (causal)."""
    acc: dict[str, dict[str, list[float]]] = {}
    for t in trades:
        lab = idx.label_at(t.get("entry_time"))
        p = t.get("pnl_pct")
        if lab is None or p is None:
            continue
        acc.setdefault(t["side"], {}).setdefault(lab, []).append(float(p))
    out: dict[str, Any] = {}
    for side in ("long", "short"):
        out[side] = {}
        for lab in LABELS:
            xs = acc.get(side, {}).get(lab, [])
            out[side][lab] = {
                "n": len(xs),
                "win_rate_pct": (sum(1 for x in xs if x > 0) / len(xs) * 100.0) if xs else None,
                "mean_pct": (sum(xs) / len(xs)) if xs else None,
                "sum_pct": sum(xs) if xs else None,
                "enough": len(xs) >= MIN_TRADES,
            }
    return out


def load(conn) -> Optional[dict]:
    """Cached regime payload (stdlib; API side)."""
    from .db import loads
    try:
        row = conn.execute("SELECT value FROM lab_kv WHERE key=?", (KV_KEY,)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return loads(row["value"]) if row else None


def save(conn, payload: dict) -> None:
    from .db import dumps
    conn.execute("INSERT INTO lab_kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (KV_KEY, dumps(payload)))
    conn.commit()
