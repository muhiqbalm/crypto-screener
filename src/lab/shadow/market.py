"""Public Binance USD-M market data for shadow execution (stdlib: urllib, zipfile, csv).

No API keys, no orders. Two sources for individual trades:

  * REST ``/fapi/v1/aggTrades``: Binance only serves ``startTime`` searches for the
    last ~2 days, so it is used for recent windows (the live cycle runs minutes
    after a signal).
  * data.binance.vision daily ``aggTrades`` zips for older windows (backfill). A day
    file appears the next day; until then the window is ``Unavailable`` and the
    caller falls back to 1m klines.

Klines (1m, 4h) always come from REST.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("lab.shadow.market")

BASE = "https://fapi.binance.com"
VISION = "https://data.binance.vision/data/futures/um/daily/aggTrades/{s}/{s}-aggTrades-{d}.zip"
TF_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
REST_AGG_HORIZON_MS = 46 * 3600 * 1000      # Binance: "Search window is restricted to recent 2 days only"
_TIMEOUT = 20
_UA = {"User-Agent": "bmtm-lab-shadow/1.0"}


class Unavailable(RuntimeError):
    """Trades for this window can't be obtained (yet)."""


def _get(path: str, params: dict):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        raise Unavailable(f"{path} HTTP {e.code}: {body}") from None


class PublicMarket:
    """Klines + aggTrades windows. ``cache_dir`` holds downloaded vision zips for one job run."""

    def __init__(self, cache_dir: Optional[str] = None, now_ms: Optional[int] = None, pause_s: float = 0.05):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.now_ms = now_ms
        self.pause_s = pause_s
        self.calls = {"klines": 0, "agg_rest": 0, "vision": 0}

    def _now(self) -> int:
        return self.now_ms or int(time.time() * 1000)

    # ── klines ─────────────────────────────────────────────────────────
    def klines(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> list[dict]:
        """Closed bars with open time in [start_ms, end_ms)."""
        step, now = TF_MS[tf], self._now()
        out, t = [], int(start_ms)
        while t < end_ms:
            rows = _get("/fapi/v1/klines", {"symbol": symbol, "interval": tf, "startTime": t,
                                            "endTime": int(end_ms) - 1, "limit": 1500})
            self.calls["klines"] += 1
            if not rows:
                break
            for r in rows:
                ts = int(r[0])
                if ts < end_ms and ts + step <= now:
                    out.append({"ts": ts, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])})
            nxt = int(rows[-1][0]) + step
            if nxt <= t or len(rows) < 1500:
                break
            t = nxt
            if self.pause_s:
                time.sleep(self.pause_s)
        return out

    # ── trades ─────────────────────────────────────────────────────────
    def agg_trades(self, symbol: str, windows: list[tuple[int, int]]) -> dict[tuple[int, int], list[tuple[int, float]]]:
        """{(start, end): [(ts_ms, price), ...]} for each [start, end) window, oldest first.
        Raises Unavailable when any window can't be served."""
        if not windows:
            return {}
        if min(w[0] for w in windows) >= self._now() - REST_AGG_HORIZON_MS:
            return {w: self._rest_window(symbol, *w) for w in windows}
        return self._vision_windows(symbol, windows)

    def _rest_window(self, symbol: str, start: int, end: int) -> list[tuple[int, float]]:
        out: list[tuple[int, float]] = []
        params = {"symbol": symbol, "startTime": int(start), "endTime": int(min(end, start + 3_600_000) - 1),
                  "limit": 1000}
        while True:
            rows = _get("/fapi/v1/aggTrades", params)
            self.calls["agg_rest"] += 1
            for r in rows:
                ts = int(r["T"])
                if start <= ts < end:
                    out.append((ts, float(r["p"])))
            if len(rows) < 1000 or int(rows[-1]["T"]) >= end - 1:
                break
            params = {"symbol": symbol, "fromId": int(rows[-1]["a"]) + 1, "limit": 1000}
            if self.pause_s:
                time.sleep(self.pause_s)
        return out

    def _day_file(self, symbol: str, day: str) -> bytes:
        if self.cache_dir:
            p = self.cache_dir / f"{symbol}-aggTrades-{day}.zip"
            if p.exists():
                return p.read_bytes()
        url = VISION.format(s=symbol, d=day)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=120) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise Unavailable(f"vision {symbol} {day}: HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise Unavailable(f"vision {symbol} {day}: {e.reason}") from None
        self.calls["vision"] += 1
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / f".{symbol}-{day}.part"
            tmp.write_bytes(data)
            os.replace(tmp, self.cache_dir / f"{symbol}-aggTrades-{day}.zip")
        return data

    def _vision_windows(self, symbol: str, windows: list[tuple[int, int]]) -> dict:
        out: dict = {w: [] for w in windows}
        days = sorted({datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                       for w in windows for t in (w[0], w[1] - 1)})
        lo, hi = min(w[0] for w in windows), max(w[1] for w in windows)
        for day in days:
            z = zipfile.ZipFile(io.BytesIO(self._day_file(symbol, day)))
            with z.open(z.namelist()[0]) as fh:
                for row in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                    # agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker
                    if not row or not row[0].isdigit():
                        continue                        # header line in newer files
                    ts = int(row[5])
                    if ts < lo or ts >= hi:
                        continue
                    px = float(row[1])
                    for w in windows:
                        if w[0] <= ts < w[1]:
                            out[w].append((ts, px))
        for w in out:
            out[w].sort()
        return out


def default_cache_dir() -> str:
    from ..settings import get_lab_settings
    return str(Path(get_lab_settings().data_dir) / "shadow_aggtrades")
