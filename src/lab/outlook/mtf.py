"""Multi-timeframe context for the Outlook (stdlib only).

The SAME functions run in the live outlook job and in the historical replay
(replay.py), so a factor state shown on the page is computed exactly like the
states the calibration measured. Closed bars only: the caller passes the index
of the last bar that had CLOSED at the call time (``last_closed``).

  * tren_1d      daily close vs EMA50 and the EMA50 slope over 10 days
                 +1: close > EMA50 and EMA50 rising, -1: close < EMA50 and falling, 0: mixed
  * momentum_1h  1H close vs EMA20 vs EMA50
                 +1: close > EMA20 > EMA50, -1: close < EMA20 < EMA50, 0: mixed
  * regime_btc   BTC market regime (regime.py label in force at the call time)

Direction +1 = mendukung long, -1 = mendukung short, 0 = netral / campuran.
The rules and thresholds were fixed BEFORE the calibration was run (no tuning).
"""
from __future__ import annotations

import bisect
from typing import Optional, Sequence

TREND_EMA = 50
TREND_SLOPE_BARS = 10
TREND_MIN_BARS = 60
MOM_FAST = 20
MOM_SLOW = 50
MOM_MIN_BARS = 100
REGIME_DIR = {"naik": 1, "turun": -1, "datar": 0}
ALIGN_FACTORS = ("tren_1d", "momentum_1h", "regime_btc")
ALIGN_TEXT = {"searah": "searah", "campuran": "campuran", "berlawanan": "berlawanan"}


def ema_series(xs: Sequence[float], n: int) -> list[float]:
    """EMA with alpha = 2/(n+1), seeded with the first value (= pandas ewm(adjust=False))."""
    a = 2.0 / (n + 1.0)
    out: list[float] = []
    y: Optional[float] = None
    for x in xs:
        y = float(x) if y is None else y + a * (float(x) - y)
        out.append(y)
    return out


def last_closed(opens_s: Sequence[float], tf_s: int, t_s: float) -> int:
    """Index of the last bar (by open time, epoch seconds, ascending) that had closed at t_s; -1 if none."""
    return bisect.bisect_right(opens_s, t_s - tf_s) - 1


def trend_at(closes: Sequence[float], ema: Sequence[float], i: int) -> Optional[dict]:
    if i < max(TREND_MIN_BARS - 1, TREND_SLOPE_BARS) or i >= len(closes):
        return None
    c, e, e0 = float(closes[i]), float(ema[i]), float(ema[i - TREND_SLOPE_BARS])
    if e <= 0 or e0 <= 0:
        return None
    slope = (e / e0 - 1.0) * 100.0
    d = 1 if c > e and slope > 0 else -1 if c < e and slope < 0 else 0
    return {"direction": d, "close": c, "ema": e, "dist_pct": (c / e - 1.0) * 100.0, "slope_pct": slope}


def momentum_at(closes: Sequence[float], ema_fast: Sequence[float], ema_slow: Sequence[float],
                i: int) -> Optional[dict]:
    if i < MOM_MIN_BARS - 1 or i >= len(closes):
        return None
    c, f, s = float(closes[i]), float(ema_fast[i]), float(ema_slow[i])
    d = 1 if c > f > s else -1 if c < f < s else 0
    ret24 = (c / float(closes[i - 24]) - 1.0) * 100.0 if i >= 24 and closes[i - 24] else None
    return {"direction": d, "close": c, "ema_fast": f, "ema_slow": s, "ret_24h_pct": ret24}


def trend_now(closes: Sequence[float]) -> Optional[dict]:
    """Live helper: trend on the last element of a closed-bar series."""
    if not closes:
        return None
    return trend_at(closes, ema_series(closes, TREND_EMA), len(closes) - 1)


def momentum_now(closes: Sequence[float]) -> Optional[dict]:
    if not closes:
        return None
    return momentum_at(closes, ema_series(closes, MOM_FAST), ema_series(closes, MOM_SLOW), len(closes) - 1)


def regime_dir(label: Optional[str]) -> Optional[int]:
    return None if label is None else REGIME_DIR.get(label, 0)


def align_score(side_sign: int, dirs: dict) -> tuple[int, int]:
    """(score, n_available): sum of direction x side over the available ALIGN_FACTORS (each -1..+1)."""
    score, n = 0, 0
    for k in ALIGN_FACTORS:
        d = dirs.get(k)
        if d is None:
            continue
        score += int(d) * side_sign
        n += 1
    return score, n


def align_group(score: int) -> str:
    """searah: >= 2 of 3 factors net with the call; berlawanan: <= -2; else campuran."""
    return "searah" if score >= 2 else "berlawanan" if score <= -2 else "campuran"
