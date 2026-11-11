"""Point-in-time (survivorship-free) perp data for Universal research.

Downloads 4H klines (with quote volume) + funding for EVERY Binance USD-M USDT
perpetual that data.binance.vision has ever published, including delisted ones
(LUNA, FTT, SRM, ...). Files use the same layout as ``data_cache`` plus a
``quote_volume`` column, but MUST live in their own directory (default
``{LAB_DATA_DIR}/../perp_pit``): the default Universal universe is "every 4H file
in the main cache", so dropping 400+ symbols there would silently change the
live paper watches.

    {dir}/{SYMBOL}_PERP_4h.parquet        timestamp, open, high, low, close, volume, quote_volume
    {dir}/{SYMBOL}_PERP_funding.parquet   timestamp, funding_rate
    {dir}/_manifest.json                  {symbol: {first, last, rows, funding_rows}}

Public data only (no API keys). Symbols are discovered from the public S3 bucket
listing behind data.binance.vision.

CLI (engine venv, needs pandas + pyarrow):
    python -m src.lab.universal.pit_data --out /path/perp_pit --until 2026-11-10 --workers 6
"""
from __future__ import annotations

import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import quote

from ..data_cache import VISION, _http_get

S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
UM_PREFIX = "data/futures/um"

# Not "coins" for a momentum universe: stablecoins / fiat pairs and composite index perps.
STABLE_BASES = {"USDC", "BUSD", "TUSD", "USDP", "FDUSD", "DAI", "EUR", "GBP", "AUD", "USDE", "PAX",
                "UST", "USTC", "SUSD", "PYUSD", "RLUSD", "USD1", "XUSD", "BFUSD", "AEUR", "EURI", "U"}
INDEX_BASES = {"BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD", "ALLSTAR"}
_SYM_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")


def base_of(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def is_excluded(symbol: str) -> bool:
    """True for anything that is not a plain USDT-margined coin perpetual."""
    s = symbol.upper()
    if not _SYM_RE.match(s):  # dated futures (BTCUSDT_230331), non-USDT quotes, odd names
        return True
    b = base_of(s)
    return b in STABLE_BASES or b in INDEX_BASES


# ── S3 listing ───────────────────────────────────────────────────────────

def _list(prefix: str, delimiter: Optional[str] = "/", get: Callable = _http_get) -> tuple[list[str], list[str]]:
    """All (common prefixes, keys) under prefix, following pagination."""
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    prefixes, keys, marker = [], [], ""
    while True:
        url = f"{S3_LIST}?prefix={quote(prefix)}" + (f"&delimiter={quote(delimiter)}" if delimiter else "")
        if marker:
            url += f"&marker={quote(marker)}"
        blob = get(url)
        if not blob:
            break
        root = ET.fromstring(blob)
        prefixes += [e.text for e in root.findall("s:CommonPrefixes/s:Prefix", ns) if e.text]
        keys += [e.text for e in root.findall("s:Contents/s:Key", ns) if e.text]
        if (root.findtext("s:IsTruncated", default="false", namespaces=ns) or "").lower() != "true":
            break
        marker = root.findtext("s:NextMarker", default="", namespaces=ns) or (keys[-1] if keys else
                                                                              prefixes[-1] if prefixes else "")
        if not marker:
            break
    return prefixes, keys


def list_um_symbols(get: Callable = _http_get) -> list[str]:
    """Every USD-M symbol with monthly klines on data.binance.vision (live + delisted), filtered."""
    prefixes, _ = _list(f"{UM_PREFIX}/monthly/klines/", get=get)
    syms = {p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes}
    return sorted(s for s in syms if not is_excluded(s))


def _zip_keys(prefix: str, get: Callable = _http_get) -> list[str]:
    _, keys = _list(prefix, delimiter=None, get=get)
    return sorted(k for k in keys if k.endswith(".zip"))


# ── parsing ──────────────────────────────────────────────────────────────

KLINE_COLS = ["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]


def parse_klines_zip(blob: bytes):
    import pandas as pd
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    has_header = raw[:20].decode("utf-8", "ignore").lower().startswith("open_time")
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None).iloc[:, :8]
    df.columns = KLINE_COLS
    df = df.drop(columns=["close_time"])
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[c] = df[c].astype(float)
    return df


def parse_funding_zip(blob: bytes):
    import pandas as pd
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    has_header = raw[:20].decode("utf-8", "ignore").lower().startswith("calc_time")
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    df = df.iloc[:, [0, df.shape[1] - 1]]
    df.columns = ["timestamp", "funding_rate"]
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df["funding_rate"] = df["funding_rate"].astype(float)
    return df


def _clean(df):
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return df.reset_index(drop=True)


# ── per-symbol download ──────────────────────────────────────────────────

def fetch_symbol(symbol: str, tf: str = "4h", until: Optional[date] = None, get: Callable = _http_get):
    """(klines DataFrame | None, funding DataFrame | None) for one symbol, bars opening < until."""
    import pandas as pd
    until = until or datetime.now(timezone.utc).date()
    mkeys = _zip_keys(f"{UM_PREFIX}/monthly/klines/{symbol}/{tf}/", get=get)
    frames = []
    last_month = None
    for k in mkeys:
        m = re.search(r"-(\d{4})-(\d{2})\.zip$", k)
        if not m or date(int(m.group(1)), int(m.group(2)), 1) >= until:
            continue
        blob = get(f"https://data.binance.vision/{k}")
        if blob:
            frames.append(parse_klines_zip(blob))
            last_month = date(int(m.group(1)), int(m.group(2)), 1)
    # daily files for the months after the last monthly file (only if the symbol is still trading)
    if last_month is not None and (until.year * 12 + until.month) - (last_month.year * 12 + last_month.month) <= 2:
        d = date(last_month.year + (last_month.month == 12), last_month.month % 12 + 1, 1)
        while d < until:
            blob = get(f"{VISION}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{d.isoformat()}.zip")
            if blob:
                frames.append(parse_klines_zip(blob))
            d += timedelta(days=1)
    kl = None
    if frames:
        kl = _clean(pd.concat(frames, ignore_index=True))
        kl = kl[kl["timestamp"] < pd.Timestamp(until, tz="UTC")].reset_index(drop=True)
    fr = []
    for k in _zip_keys(f"{UM_PREFIX}/monthly/fundingRate/{symbol}/", get=get):
        blob = get(f"https://data.binance.vision/{k}")
        if blob:
            fr.append(parse_funding_zip(blob))
    fu = _clean(pd.concat(fr, ignore_index=True)) if fr else None
    return kl, fu


def _save(df, path: Path) -> None:
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def download(out_dir: str, symbols: Optional[Iterable[str]] = None, tf: str = "4h", until: Optional[date] = None,
             workers: int = 6, skip_existing: bool = True, log: Callable = print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    syms = list(symbols) if symbols else list_um_symbols()
    man_path = out / "_manifest.json"
    try:
        manifest = json.loads(man_path.read_text())
    except (OSError, ValueError):
        manifest = {}
    todo = [s for s in syms if not (skip_existing and s in manifest and (out / f"{s}_PERP_{tf}.parquet").exists())]
    log(f"{len(syms)} symbols, {len(todo)} to download -> {out}")
    errors = {}

    def one(s):
        kl, fu = fetch_symbol(s, tf, until)
        if kl is not None and len(kl):
            _save(kl, out / f"{s}_PERP_{tf}.parquet")
        if fu is not None and len(fu):
            _save(fu, out / f"{s}_PERP_funding.parquet")
        return s, kl, fu

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(one, s): s for s in todo}
        for n, f in enumerate(as_completed(futs), 1):
            s = futs[f]
            try:
                _, kl, fu = f.result()
                manifest[s] = {"first": kl["timestamp"].iloc[0].isoformat() if kl is not None and len(kl) else None,
                               "last": kl["timestamp"].iloc[-1].isoformat() if kl is not None and len(kl) else None,
                               "rows": int(len(kl)) if kl is not None else 0,
                               "funding_rows": int(len(fu)) if fu is not None else 0}
            except Exception as e:  # noqa: BLE001 - keep going, report at the end
                errors[s] = str(e)[:200]
            if n % 25 == 0 or n == len(todo):
                log(f"  {n}/{len(todo)} done, {len(errors)} errors")
                tmp = man_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True))
                os.replace(tmp, man_path)
    return {"symbols": len(syms), "downloaded": len(todo) - len(errors), "errors": errors}


# ── loading ──────────────────────────────────────────────────────────────

def default_dir() -> str:
    """LAB_PIT_DATA_DIR, else a `perp_pit` directory next to the main Lab cache."""
    env = os.environ.get("LAB_PIT_DATA_DIR")
    if env:
        return env
    from ..settings import get_lab_settings
    return str(Path(get_lab_settings().data_dir).parent / "perp_pit")


def pit_symbols(data_dir: str, tf: str = "4h") -> list[str]:
    d = Path(data_dir)
    return sorted(p.name.split("_PERP_")[0] for p in d.glob(f"*_PERP_{tf}.parquet")
                  if not is_excluded(p.name.split("_PERP_")[0]))


def load(data_dir: str, symbols: Optional[Iterable[str]] = None, tf: str = "4h", funding: bool = True):
    """({symbol: klines df}, {symbol: funding df}) from a PIT directory."""
    import pandas as pd
    d = Path(data_dir)
    syms = list(symbols) if symbols else pit_symbols(data_dir, tf)
    ohlcv, fund = {}, {}
    for s in syms:
        p = d / f"{s}_PERP_{tf}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        ohlcv[s] = _clean(df)
        fp = d / f"{s}_PERP_funding.parquet"
        if funding and fp.exists():
            f = pd.read_parquet(fp)
            f["timestamp"] = pd.to_datetime(f["timestamp"], utc=True)
            fund[s] = _clean(f)
    return ohlcv, fund


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--until", default=None, help="YYYY-MM-DD, exclusive (default: today UTC)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--symbols", default="", help="comma list (default: every USDT perp ever listed)")
    ap.add_argument("--refresh", action="store_true", help="re-download symbols already in the manifest")
    a = ap.parse_args(argv)
    until = date.fromisoformat(a.until) if a.until else None
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or None
    res = download(a.out, syms, until=until, workers=a.workers, skip_existing=not a.refresh)
    print(json.dumps({k: v for k, v in res.items() if k != "errors"}), "errors:", len(res["errors"]))
    for s, e in sorted(res["errors"].items()):
        print("  ", s, e)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
