"""Parquet cache of Binance USD-M perpetual OHLCV + funding.

File layout matches bmtm-v2's scripts/fetch_perp_data.py so the existing VPS
files can be copied in as-is:
    {LAB_DATA_DIR}/{SYMBOL}_PERP_{tf}.parquet      timestamp(UTC), open, high, low, close, volume
    {LAB_DATA_DIR}/{SYMBOL}_PERP_funding.parquet   timestamp(UTC), funding_rate
    {LAB_DATA_DIR}/_index.json                     {key: {symbol, timeframe, first, last, rows}}

Sources (public only, never API keys):
  1. bulk monthly/daily zips from data.binance.vision
  2. ccxt binanceusdm public endpoints for the tail, throttled to <=300 weight/min

Runs in the engine child process (needs pandas + pyarrow; ccxt optional).
The API only reads _index.json.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .settings import get_lab_settings

TF_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
VISION = "https://data.binance.vision/data/futures/um"
DEFAULT_START = "2020-01-01"
# klines limit=1500 costs 10 weight; 300 weight/min -> one page per 2 s.
CCXT_PAGE_SLEEP_S = 2.0
_UA = {"User-Agent": "bmtm-lab/1.0"}


def data_dir() -> Path:
    p = Path(get_lab_settings().data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ohlcv_path(symbol: str, tf: str) -> Path:
    return data_dir() / f"{symbol.upper()}_PERP_{tf}.parquet"


def funding_path(symbol: str) -> Path:
    return data_dir() / f"{symbol.upper()}_PERP_funding.parquet"


def index_path() -> Path:
    return data_dir() / "_index.json"


def read_index(path: Optional[Path] = None) -> dict:
    """Stdlib-only reader (used by the API)."""
    p = path or Path(get_lab_settings().data_dir) / "_index.json"
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return {}


def _write_index_entry(symbol: str, tf: str, df) -> None:
    idx = read_index(index_path())
    key = f"{symbol.upper()}_{tf}"
    if df is None or len(df) == 0:
        idx.pop(key, None)
    else:
        idx[key] = {
            "symbol": symbol.upper(), "timeframe": tf,
            "first": df["timestamp"].iloc[0].isoformat(),
            "last": df["timestamp"].iloc[-1].isoformat(),
            "rows": int(len(df)),
        }
    tmp = index_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, indent=1, sort_keys=True))
    os.replace(tmp, index_path())


def rebuild_index() -> dict:
    import pandas as pd
    for p in data_dir().glob("*_PERP_*.parquet"):
        sym, _, tf = p.stem.partition("_PERP_")
        if tf in TF_SECONDS:
            _write_index_entry(sym, tf, _normalise(pd.read_parquet(p)))
    return read_index(index_path())


# ── loading ──────────────────────────────────────────────────────────────

def _normalise(df):
    import pandas as pd
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return df.reset_index(drop=True)


def load_ohlcv(symbol: str, tf: str):
    import pandas as pd
    p = ohlcv_path(symbol, tf)
    if not p.exists():
        return None
    df = _normalise(pd.read_parquet(p))
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def load_funding(symbol: str):
    import pandas as pd
    p = funding_path(symbol)
    if not p.exists():
        return None
    return _normalise(pd.read_parquet(p))[["timestamp", "funding_rate"]]


def _save(df, path: Path) -> None:
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ── data.binance.vision bulk ─────────────────────────────────────────────

def _http_get(url: str, timeout: float = 60.0) -> Optional[bytes]:
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _read_zip_csv(blob: bytes, kind: str):
    import pandas as pd
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = z.namelist()[0]
        raw = z.read(name)
    first = raw[:200].decode("utf-8", "ignore").lower()
    has_header = first.startswith("open_time") or first.startswith("calc_time")
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if kind == "klines":
        df = df.iloc[:, :6]
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
    else:  # fundingRate: calc_time, funding_interval_hours, last_funding_rate
        df = df.iloc[:, [0, 2]]
        df.columns = ["timestamp", "funding_rate"]
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
        df["funding_rate"] = df["funding_rate"].astype(float)
    return df


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch_vision_klines(symbol: str, tf: str, start: date, progress: Optional[Callable] = None):
    import pandas as pd
    today = datetime.now(timezone.utc).date()
    frames = []
    months = list(_months(start, today))
    for n, (y, m) in enumerate(months):
        url = f"{VISION}/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{y}-{m:02d}.zip"
        blob = _http_get(url)
        recent = (today.year * 12 + today.month) - (y * 12 + m) <= 1
        if blob is None and recent:
            # current / just-finished month: monthly zip may not exist yet -> daily zips
            d = date(y, m, 1)
            while d.month == m and d < today:
                b = _http_get(f"{VISION}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{d.isoformat()}.zip")
                if b:
                    frames.append(_read_zip_csv(b, "klines"))
                d += timedelta(days=1)
        elif blob:
            frames.append(_read_zip_csv(blob, "klines"))
        if progress:
            progress({"stage": f"download {symbol} {tf}", "done": n + 1, "total": len(months)})
    if not frames:
        return None
    return _normalise(pd.concat(frames, ignore_index=True))


def fetch_vision_funding(symbol: str, start: date):
    import pandas as pd
    today = datetime.now(timezone.utc).date()
    frames = []
    for y, m in _months(start, today):
        blob = _http_get(f"{VISION}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{y}-{m:02d}.zip")
        if blob:
            frames.append(_read_zip_csv(blob, "funding"))
    if not frames:
        return None
    return _normalise(pd.concat(frames, ignore_index=True))


# ── ccxt public tail ─────────────────────────────────────────────────────

def _ccxt():
    import ccxt  # type: ignore
    return ccxt.binanceusdm({"enableRateLimit": True})  # public endpoints only, no keys


def _market(symbol: str) -> str:
    return f"{symbol.upper()[:-4]}/USDT:USDT"


def fetch_ccxt_klines(symbol: str, tf: str, since_ms: int, ex=None):
    import pandas as pd
    ex = ex or _ccxt()
    tf_ms = TF_SECONDS[tf] * 1000
    now_ms = int(time.time() * 1000)
    rows, cursor = [], since_ms
    while cursor < now_ms:
        batch = ex.fetch_ohlcv(_market(symbol), tf, since=cursor, limit=1500)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + tf_ms
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 1500:
            break
        time.sleep(CCXT_PAGE_SLEEP_S)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return _normalise(df)


def fetch_ccxt_funding(symbol: str, since_ms: int, ex=None):
    import pandas as pd
    ex = ex or _ccxt()
    now_ms = int(time.time() * 1000)
    rows, cursor = [], since_ms
    while cursor < now_ms:
        batch = ex.fetch_funding_rate_history(_market(symbol), since=cursor, limit=1000)
        if not batch:
            break
        rows.extend({"timestamp": b["timestamp"], "funding_rate": b["fundingRate"]} for b in batch)
        nxt = batch[-1]["timestamp"] + 1
        if nxt <= cursor or len(batch) < 1000:
            break
        cursor = nxt
        time.sleep(CCXT_PAGE_SLEEP_S)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return _normalise(df)


def fetch_vision_daily_klines(symbol: str, tf: str, since: date):
    import pandas as pd
    today = datetime.now(timezone.utc).date()
    frames, d = [], since
    while d < today:
        b = _http_get(f"{VISION}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{d.isoformat()}.zip")
        if b:
            frames.append(_read_zip_csv(b, "klines"))
        d += timedelta(days=1)
    return _normalise(pd.concat(frames, ignore_index=True)) if frames else None


def fetch_tail(symbol: str, tf: str, since_ms: int):
    """Best effort: ccxt public first, then data.binance.vision daily zips."""
    try:
        return fetch_ccxt_klines(symbol, tf, since_ms)
    except Exception:  # noqa: BLE001 - network/geo errors
        pass
    try:
        since = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).date()
        return fetch_vision_daily_klines(symbol, tf, since)
    except Exception:  # noqa: BLE001
        return None


def _drop_forming(df, tf: str):
    import pandas as pd
    if df is None or len(df) == 0:
        return df
    now = pd.Timestamp.now(tz="UTC")
    return df[df["timestamp"] + pd.Timedelta(seconds=TF_SECONDS[tf]) <= now].reset_index(drop=True)


# ── public API ───────────────────────────────────────────────────────────

def ensure(symbol: str, tf: str, start: str = DEFAULT_START, funding: bool = True,
           max_stale_bars: int = 1, progress: Optional[Callable] = None, offline: bool = False):
    """Make sure OHLCV (and funding) are cached and reasonably fresh.

    Returns (ohlcv_df, funding_df_or_None). With offline=True nothing is fetched.
    """
    import pandas as pd
    symbol = symbol.upper()
    if tf not in TF_SECONDS:
        raise ValueError(f"unsupported timeframe {tf}")
    df = load_ohlcv(symbol, tf)
    if not offline:
        now = pd.Timestamp.now(tz="UTC")
        fresh_cut = now - pd.Timedelta(seconds=TF_SECONDS[tf] * (max_stale_bars + 1))
        if df is None or len(df) == 0:
            df = fetch_vision_klines(symbol, tf, pd.Timestamp(start).date(), progress)
            tail_since = (int(df["timestamp"].iloc[-1].value // 10**6) + TF_SECONDS[tf] * 1000
                          if df is not None and len(df) else
                          int(pd.Timestamp(start, tz="UTC").value // 10**6))
            tail = fetch_tail(symbol, tf, tail_since)
            if tail is not None:
                df = tail if df is None else _normalise(pd.concat([df, tail]))
        elif df["timestamp"].iloc[-1] < fresh_cut:
            since = int(df["timestamp"].iloc[-1].value // 10**6) + TF_SECONDS[tf] * 1000
            tail = fetch_tail(symbol, tf, since)
            if tail is not None:
                df = _normalise(pd.concat([df, tail]))
        if df is None or len(df) == 0:
            raise RuntimeError(f"no data available for {symbol} {tf}")
        df = _drop_forming(df, tf)
        _save(df, ohlcv_path(symbol, tf))
        _write_index_entry(symbol, tf, df)
    if df is None:
        raise RuntimeError(f"no cached data for {symbol} {tf}")

    fdf = None
    if funding:
        fdf = load_funding(symbol)
        if not offline:
            stale = fdf is None or len(fdf) == 0 or \
                fdf["timestamp"].iloc[-1] < pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=9)
            if stale:
                if fdf is None or len(fdf) == 0:
                    fdf = fetch_vision_funding(symbol, pd.Timestamp(start).date())
                since = (int(fdf["timestamp"].iloc[-1].value // 10**6) + 1 if fdf is not None and len(fdf)
                         else int(pd.Timestamp(start, tz="UTC").value // 10**6))
                try:
                    tail = fetch_ccxt_funding(symbol, since)
                except Exception:
                    tail = None
                if tail is not None:
                    fdf = tail if fdf is None else _normalise(pd.concat([fdf, tail]))
                if fdf is not None and len(fdf):
                    _save(fdf, funding_path(symbol))
    return df, fdf
