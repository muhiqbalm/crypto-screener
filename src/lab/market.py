"""Light, cached public market data for the Lab (klines, last price, funding).

Public Binance USD-M endpoints only (no keys). Used by the API (klines, paper
fill price) and by the worker scheduler (paper SL/TP checks, funding). Never
touches src.trading. The API can hand in the screener's shared exchange via
set_shared_exchange(); otherwise one lazily-created public instance is used.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

_lock = threading.Lock()
_cache: dict[tuple, tuple[float, Any]] = {}
_shared: Any = None
_own: Any = None


def set_shared_exchange(ex: Any) -> None:
    global _shared
    _shared = ex


def _exchange():
    global _own
    if _shared is not None:
        return _shared
    with _lock:
        if _own is None:
            import ccxt  # type: ignore
            _own = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 10000})
        return _own


def market_id(symbol: str) -> str:
    s = symbol.upper()
    return f"{s[:-4]}/USDT:USDT"


def _cached(key: tuple, ttl: float, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (now, val)
        if len(_cache) > 500:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                _cache.pop(k, None)
    return val


def _iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def fetch_klines(symbol: str, tf: str, limit: int = 500, since_ms: Optional[int] = None) -> list[dict]:
    rows = _exchange().fetch_ohlcv(market_id(symbol), tf, since=since_ms, limit=min(int(limit), 1500))
    return [{"t": _iso(r[0]), "ts": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
             "c": float(r[4]), "v": float(r[5])} for r in rows]


def klines(symbol: str, tf: str, limit: int = 500, ttl: float = 30.0) -> list[dict]:
    """Recent candles incl. the still-forming one, cached >= 30 s."""
    if tf not in TF_SECONDS:
        raise ValueError(f"unsupported timeframe {tf}")
    data = _cached(("k", symbol, tf, int(limit)), max(30.0, ttl), lambda: fetch_klines(symbol, tf, limit))
    return [{k: v for k, v in r.items() if k != "ts"} for r in data]


def closed_klines(symbol: str, tf: str, since_ms: int, limit: int = 1500) -> list[dict]:
    """Closed candles opening at/after since_ms (uncached; used by the worker)."""
    now_ms = int(time.time() * 1000)
    rows = fetch_klines(symbol, tf, limit=limit, since_ms=since_ms)
    return [r for r in rows if r["ts"] + TF_SECONDS[tf] * 1000 <= now_ms]


def last_price(symbol: str, ttl: float = 5.0) -> float:
    def fetch():
        t = _exchange().fetch_ticker(market_id(symbol))
        px = t.get("last") or t.get("close")
        if not px:
            raise RuntimeError(f"no price for {symbol}")
        return float(px)
    return _cached(("p", symbol), ttl, fetch)


def funding_history(symbol: str, since_ms: int) -> list[dict]:
    rows = _exchange().fetch_funding_rate_history(market_id(symbol), since=since_ms, limit=100)
    out = []
    for r in rows:
        info = r.get("info") or {}
        mark = info.get("markPrice")
        out.append({"ts": int(r["timestamp"]), "rate": float(r["fundingRate"]),
                    "mark": float(mark) if mark not in (None, "") else None})
    return out
