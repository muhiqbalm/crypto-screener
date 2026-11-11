"""Public Binance USD-M REST helpers for the ledger (no API keys, no orders).

klines (15m path for scoring, 1h/1d for the reconstruction), funding history,
top-trader long/short ratio and open-interest history (Binance keeps ~30 days
of the last two). Every function returns plain dicts; tests inject fakes instead.
"""
from __future__ import annotations

import time
from typing import Optional

BASE = "https://fapi.binance.com"
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_TIMEOUT = 15


class UnknownSymbol(RuntimeError):
    unknown_symbol = True


def _get(path: str, params: dict):
    import requests
    r = requests.get(BASE + path, params=params, timeout=_TIMEOUT)
    if r.status_code == 400 and "symbol" in r.text.lower():
        raise UnknownSymbol(f"{params.get('symbol')}: {r.text[:120]}")
    r.raise_for_status()
    return r.json()


def klines(symbol: str, tf: str, start_ms: int, end_ms: int, pause_s: float = 0.05) -> list[dict]:
    """Closed bars with open time in [start_ms, end_ms], paginated (1500 per request)."""
    step = TF_MS[tf]
    now_ms = int(time.time() * 1000)
    out: list[dict] = []
    t = int(start_ms)
    while t <= end_ms:
        rows = _get("/fapi/v1/klines", {"symbol": symbol, "interval": tf, "startTime": t, "endTime": int(end_ms),
                                        "limit": 1500})
        if not rows:
            break
        for r in rows:
            ts = int(r[0])
            if ts + step <= now_ms:
                out.append({"ts": ts, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]),
                            "v": float(r[5])})
        nxt = int(rows[-1][0]) + step
        if nxt <= t or len(rows) < 1500:
            break
        t = nxt
        if pause_s:
            time.sleep(pause_s)
    return out


def klines_15m(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    return klines(symbol, "15m", start_ms, end_ms)


def funding(symbol: str, start_ms: int, end_ms: Optional[int] = None) -> list[dict]:
    """Settled funding rates [{ts, rate}] (rate as a fraction)."""
    out, t = [], int(start_ms)
    end_ms = end_ms or int(time.time() * 1000)
    while t < end_ms:
        rows = _get("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": t, "endTime": end_ms, "limit": 1000})
        if not rows:
            break
        out += [{"ts": int(r["fundingTime"]), "rate": float(r["fundingRate"])} for r in rows]
        if len(rows) < 1000:
            break
        t = int(rows[-1]["fundingTime"]) + 1
    return out


def _futures_data(path: str, key: str, symbol: str, start_ms: int, end_ms: int, pause_s: float) -> list[dict]:
    """1h series from /futures/data/* in 500-point windows (startTime+endTime both required for history)."""
    out, t, win = [], int(start_ms), 500 * TF_MS["1h"]
    while t < end_ms:
        e = min(end_ms, t + win - 1)
        rows = _get(path, {"symbol": symbol, "period": "1h", "startTime": t, "endTime": e, "limit": 500})
        out += [{"ts": int(r["timestamp"]), "v": float(r[key])} for r in rows or [] if r.get(key) not in (None, "")]
        t = e + 1
        if pause_s:
            time.sleep(pause_s)
    dedup = {r["ts"]: r for r in out}
    return [dedup[k] for k in sorted(dedup)]


def long_short_hist(symbol: str, start_ms: int, end_ms: int, pause_s: float = 0.1) -> list[dict]:
    return _futures_data("/futures/data/topLongShortAccountRatio", "longShortRatio", symbol, start_ms, end_ms,
                         pause_s)


def open_interest_hist(symbol: str, start_ms: int, end_ms: int, pause_s: float = 0.1) -> list[dict]:
    return _futures_data("/futures/data/openInterestHist", "sumOpenInterest", symbol, start_ms, end_ms, pause_s)
