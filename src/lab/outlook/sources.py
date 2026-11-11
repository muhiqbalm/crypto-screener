"""External context for the Outlook job (stdlib urllib; public endpoints only, no keys).

  * headlines: the same CoinTelegraph RSS the /news page uses, matched to coins by name /
    ticker. Shown as CONTEXT only: no per-coin sentiment score is computed or claimed.
  * Fear & Greed: alternative.me, market-wide.
  * open interest: Binance /futures/data/openInterestHist (4h, last 7 points -> 24h change).

Every fetch fails soft: the caller gets None and the UI shows "tidak tersedia".
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Optional

RSS_URL = "https://cointelegraph.com/rss"
FNG_URL = "https://api.alternative.me/fng/?limit=1"
OI_URL = "https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}&period=4h&limit=7"
_UA = {"User-Agent": "bmtm-lab/1.0"}
_TIMEOUT = 15

# Names are matched case-insensitively; tickers only in UPPER case (avoids "near", "link", "dot").
COIN_NAMES: dict[str, list[str]] = {
    "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"], "XRP": ["xrp", "ripple"],
    "BNB": ["bnb", "binance coin"], "DOGE": ["dogecoin"], "ADA": ["cardano"], "AVAX": ["avalanche"],
    "LINK": ["chainlink"], "DOT": ["polkadot"], "LTC": ["litecoin"], "NEAR": ["near protocol"],
    "UNI": ["uniswap"], "AAVE": ["aave"], "APT": ["aptos"], "ARB": ["arbitrum"], "OP": ["optimism"],
    "SUI": ["sui"], "SEI": ["sei network"], "TIA": ["celestia"], "INJ": ["injective"], "FET": ["fetch.ai", "artificial superintelligence alliance"],
    "RENDER": ["render network"], "GALA": ["gala games"], "WIF": ["dogwifhat"], "HYPE": ["hyperliquid"],
    "ZEC": ["zcash"], "1000PEPE": ["pepe"], "1000SHIB": ["shiba inu", "shib"],
}
_MIN_TICKER = 3


def coin_of(symbol: str) -> str:
    s = symbol.upper()
    return s[:-4] if s.endswith("USDT") else s


def _patterns(coin: str) -> list[re.Pattern]:
    pats = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", re.I) for n in COIN_NAMES.get(coin, [])]
    tick = coin.replace("1000", "")
    if len(tick) >= _MIN_TICKER:
        pats.append(re.compile(r"(?<![A-Za-z0-9$])\$?" + re.escape(tick) + r"(?![A-Za-z0-9])"))
    return pats


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 (fixed public https URLs)
        return r.read()


def parse_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        link = link if link.startswith("https://") or link.startswith("http://") else None
        pub = item.findtext("pubDate")
        try:
            ts = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if pub else None
        except (TypeError, ValueError):
            ts = None
        out.append({"title": title[:300], "url": link, "published_at": ts, "source": "CoinTelegraph"})
    return out


def headlines_for(items: list[dict], symbol: str, limit: int = 5) -> list[dict]:
    pats = _patterns(coin_of(symbol))
    if not pats:
        return []
    hits = [i for i in items if any(p.search(i["title"]) for p in pats)]
    hits.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    return hits[:limit]


def fetch_headlines() -> Optional[list[dict]]:
    try:
        return parse_rss(_get(RSS_URL))
    except Exception:  # noqa: BLE001
        return None


def fetch_fear_greed() -> Optional[dict]:
    try:
        data = json.loads(_get(FNG_URL)).get("data") or []
        if not data or data[0].get("value") is None:
            return None
        d = data[0]
        ts = d.get("timestamp")
        return {"value": int(d["value"]), "classification": d.get("value_classification"),
                "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts))) if ts else None,
                "source": "alternative.me"}
    except Exception:  # noqa: BLE001
        return None


def oi_change(symbol: str) -> Optional[dict]:
    """24h open-interest change from 4h points (oldest of the last 7 vs newest)."""
    try:
        rows = json.loads(_get(OI_URL.format(sym=symbol)))
        pts = [(int(r["timestamp"]), float(r["sumOpenInterest"])) for r in rows if r.get("sumOpenInterest")]
        pts.sort()
        if len(pts) < 2 or pts[0][1] <= 0:
            return None
        return {"change_24h_pct": (pts[-1][1] / pts[0][1] - 1.0) * 100.0, "oi": pts[-1][1],
                "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(pts[-1][0] / 1000)), "source": "Binance"}
    except Exception:  # noqa: BLE001
        return None
