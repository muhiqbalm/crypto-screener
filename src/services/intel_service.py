"""Intelligence service for market sentiment, Binance derivatives flow and news.

Pulls live data from:
1. Binance Futures public API (fapi.binance.com): top-trader long/short
   position ratios and recent aggregated trades (large prints).
2. Alternative.me: Crypto Fear & Greed Index.
3. CoinTelegraph RSS: headlines with their real publication time.

Zero static mocking: nothing here is ever a hardcoded number. When a source
cannot be reached the corresponding fields are ``None`` and listed in
``unavailableFields``; ``status`` is ``"live"``, ``"partial"`` or
``"unavailable"``. Fully failed snapshots are not cached, so the next request
retries immediately.

FE conventions kept: ratio rows from the live API carry ``updated: "Live FAPI"``,
trade ids start with ``tx-fapi-``, news ids start with ``live-news-``.
"""

import asyncio
import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60

FAPI = "https://fapi.binance.com"
RATIO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
LARGE_TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
AGG_TRADES_LIMIT = 500
LARGE_TRADE_MIN_USD = 50_000
MAX_WHALE_TRANSACTIONS = 10

# Top-trader positioning thresholds (share of positions held long, %).
STANCE_LONG_THRESHOLD = 55.0
STANCE_SHORT_THRESHOLD = 45.0

# Headline keyword lists; matched on word boundaries (see _keyword_regex).
BULLISH_WORDS = [
    "surge", "surges", "surged", "surging", "rally", "rallies", "rallied",
    "inflow", "inflows", "record", "advance", "advances", "etf", "approval",
    "approved", "approves", "bull", "bulls", "bullish", "gain", "gains",
    "climb", "climbs", "climbed", "high", "highs", "soar", "soars", "soared",
    "jump", "jumps", "jumped", "breakout",
]
BEARISH_WORDS = [
    "hack", "hacked", "hacker", "hackers", "exploit", "exploited", "warn",
    "warns", "warning", "drop", "drops", "dropped", "plunge", "plunges",
    "plunged", "ban", "bans", "banned", "lawsuit", "sec", "fraud", "crash",
    "crashes", "crashed", "investigation", "bear", "bears", "bearish",
    "outflow", "outflows", "selloff", "sell-off", "liquidation", "liquidations",
    "slump", "slumps", "tumble", "tumbles",
]
REGULATORY_WORDS = ["sec", "rules", "rule", "regulator", "regulators", "regulation", "lawsuit", "court", "cftc"]

SYMBOL_ALIASES = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ether", "ethereum"],
    "SOL": ["sol", "solana"],
    "XRP": ["xrp", "ripple"],
    "USDT": ["usdt", "tether"],
    "DOGE": ["doge", "dogecoin"],
}


def _keyword_regex(words: List[str]) -> "re.Pattern[str]":
    alternation = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE)


_BULL_RE = _keyword_regex(BULLISH_WORDS)
_BEAR_RE = _keyword_regex(BEARISH_WORDS)
_REG_RE = _keyword_regex(REGULATORY_WORDS)
_SYMBOL_RES = {sym: _keyword_regex(aliases) for sym, aliases in SYMBOL_ALIASES.items()}


def count_keywords(text: str, pattern: "re.Pattern[str]") -> int:
    """Number of whole-word keyword hits in ``text``."""
    return len(pattern.findall(text or ""))


def classify_headline(title: str) -> Dict[str, Any]:
    """Keyword sentiment for a headline using word-boundary matching."""
    bull = count_keywords(title, _BULL_RE)
    bear = count_keywords(title, _BEAR_RE)
    if bull > bear:
        sentiment, impact = "BULLISH", 80 + min(bull * 5, 18)
    elif bear > bull:
        sentiment, impact = "BEARISH", 70 + min(bear * 6, 25)
    else:
        sentiment, impact = "NEUTRAL", 65
    symbols = [sym for sym, rx in _SYMBOL_RES.items() if rx.search(title or "")]
    if sentiment == "BULLISH":
        category = "Catalyst"
    elif _REG_RE.search(title or ""):
        category = "Regulatory"
    else:
        category = "Macro"
    return {
        "sentiment": sentiment,
        "impactScore": impact,
        "affectedSymbols": symbols or ["CRYPTO"],
        "category": category,
        "bullHits": bull,
        "bearHits": bear,
    }


def relative_time(event_epoch: float, now: float) -> str:
    """Human-friendly age of a real event timestamp."""
    delta = max(0, int(now - event_epoch))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        mins = delta // 60
        return f"{mins} min{'s' if mins != 1 else ''} ago"
    if delta < 86400:
        hours = delta // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = delta // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def parse_pub_date(value: Optional[str]) -> Optional[datetime]:
    """Parse an RSS ``pubDate`` (RFC 822); None if missing or malformed."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_stance(ratios: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Top-trader positioning bias from long-position shares.

    The old logic labelled everything at or below 60% long as short-biased
    and "DEFENSIVE" (e.g. 55% long -> "45.0% Short"). Now: the bias names the
    side that actually holds the majority, and the stance is bullish/bearish
    only outside a neutral band around 50%.
    """
    if not ratios:
        return {"topTraderBias": None, "smartMoneyStance": None, "smartMoneyStanceCode": None}
    avg_long = sum(r["longPct"] for r in ratios) / len(ratios)
    avg_short = 100.0 - avg_long
    if avg_long >= avg_short:
        bias = f"{avg_long:.1f}% Long"
    else:
        bias = f"{avg_short:.1f}% Short"
    if avg_long > STANCE_LONG_THRESHOLD:
        stance, code = "NET LONG (bullish positioning)", "bullish"
    elif avg_long < STANCE_SHORT_THRESHOLD:
        stance, code = "NET SHORT (bearish positioning)", "bearish"
    else:
        stance, code = "BALANCED", "neutral"
    return {"topTraderBias": bias, "smartMoneyStance": stance, "smartMoneyStanceCode": code}


def extract_large_trades(
    symbol: str, trades: List[Dict[str, Any]], now: float, min_usd: float = LARGE_TRADE_MIN_USD
) -> List[Dict[str, Any]]:
    """Turn Binance aggTrades into whale-transaction rows (taker side is real)."""
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    out = []
    for t in trades:
        try:
            price = float(t.get("p", 0))
            qty = float(t.get("q", 0))
        except (TypeError, ValueError):
            continue
        usd_val = price * qty
        if usd_val < min_usd:
            continue
        # m = buyer is the maker -> the aggressive (taker) side sold.
        is_taker_sell = bool(t.get("m", False))
        trade_ms = t.get("T")
        trade_epoch = trade_ms / 1000.0 if isinstance(trade_ms, (int, float)) else None
        out.append({
            "id": f"tx-fapi-{base}-{t.get('a')}",
            "timestamp": relative_time(trade_epoch, now) if trade_epoch else None,
            "tradeTime": trade_ms if trade_epoch else None,
            "symbol": base,
            "amount": f"{qty:,.4f} {base}",
            "usdValue": f"${usd_val:,.0f}",
            "usdValueRaw": round(usd_val, 2),
            "side": "SELL" if is_taker_sell else "BUY",
            "from": "Aggressive seller (taker)" if is_taker_sell else "Aggressive buyer (taker)",
            "to": f"Binance USDT-M {base}USDT perpetual",
            # FE convention: "outflow" = taker buy, "inflow" = taker sell.
            "type": "inflow" if is_taker_sell else "outflow",
            # The trade is an exchange print, not an inference.
            "confidence": 100,
            "catalyst": f"Taker {'sell' if is_taker_sell else 'buy'} >= ${min_usd:,.0f} on Binance Futures",
        })
    return out


class IntelService:
    def __init__(self) -> None:
        self._whales_cache: Optional[Dict[str, Any]] = None
        self._whales_cache_time: float = 0.0

        self._news_cache: Optional[Dict[str, Any]] = None
        self._news_cache_time: float = 0.0

        self._client = httpx.AsyncClient(
            headers={"User-Agent": "BMTM-MoonTrade/1.0"},
            timeout=8.0,
            verify=True,
        )

    # ------------------------------------------------------------------ whales
    async def _fetch_ratio(self, sym: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._client.get(
                f"{FAPI}/futures/data/topLongShortPositionRatio",
                params={"symbol": sym, "period": "5m", "limit": 1},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data:
                return None
            item = data[0]
            long_share = item.get("longAccount")
            short_share = item.get("shortAccount")
            if long_share is None or short_share is None:
                return None
            ratio = item.get("longShortRatio")
            return {
                "symbol": sym,
                "longPct": round(float(long_share) * 100, 1),
                "shortPct": round(float(short_share) * 100, 1),
                "lsRatio": round(float(ratio), 2) if ratio is not None else None,
                "updated": "Live FAPI",
                "timestamp": item.get("timestamp"),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch L/S ratio for {sym}: {e}")
            return None

    async def _fetch_agg_trades(self, sym: str) -> Optional[List[Dict[str, Any]]]:
        try:
            resp = await self._client.get(
                f"{FAPI}/fapi/v1/aggTrades", params={"symbol": sym, "limit": AGG_TRADES_LIMIT}
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch aggTrades for {sym}: {e}")
            return None

    async def get_whales_data(self) -> Dict[str, Any]:
        """Top-trader positioning and recent large Binance Futures prints."""
        now = time.time()
        if self._whales_cache and (now - self._whales_cache_time) < CACHE_TTL_SECONDS:
            return self._whales_cache

        ratio_results, trade_results = await asyncio.gather(
            asyncio.gather(*[self._fetch_ratio(s) for s in RATIO_SYMBOLS]),
            asyncio.gather(*[self._fetch_agg_trades(s) for s in LARGE_TRADE_SYMBOLS]),
        )
        now = time.time()
        ratios = [r for r in ratio_results if r]

        large_trades: List[Dict[str, Any]] = []
        trade_sources_ok = 0
        window_start: Optional[float] = None
        for sym, raw in zip(LARGE_TRADE_SYMBOLS, trade_results):
            if raw is None:
                continue
            trade_sources_ok += 1
            times = [t.get("T") for t in raw if isinstance(t.get("T"), (int, float))]
            if times:
                oldest = min(times) / 1000.0
                window_start = oldest if window_start is None else max(window_start, oldest)
            large_trades.extend(extract_large_trades(sym, raw, now))

        large_trades.sort(key=lambda r: r.get("tradeTime") or 0, reverse=True)

        flow: Dict[str, Optional[float]] = {
            "largeTradeBuyUsd": None,
            "largeTradeSellUsd": None,
            "largeTradeNetUsd": None,
            "largeTradeWindowSeconds": None,
        }
        if trade_sources_ok:
            cutoff_ms = window_start * 1000 if window_start else 0
            in_window = [t for t in large_trades if (t.get("tradeTime") or 0) >= cutoff_ms]
            buy = sum(t["usdValueRaw"] for t in in_window if t["side"] == "BUY")
            sell = sum(t["usdValueRaw"] for t in in_window if t["side"] == "SELL")
            flow = {
                "largeTradeBuyUsd": round(buy, 2),
                "largeTradeSellUsd": round(sell, 2),
                "largeTradeNetUsd": round(buy - sell, 2),
                # Window covered by the sampled trades (the shortest of the
                # per-symbol windows, so every symbol is fully covered).
                "largeTradeWindowSeconds": round(now - window_start, 1) if window_start else None,
            }

        unavailable = [
            # No free, reliable source for these yet; never fabricated.
            "whaleVolume24h",
            "whaleVolumeChange",
            "exchangeNetFlow",
        ]
        if not ratios:
            unavailable += ["topTraderRatios", "topTraderBias", "smartMoneyStance"]
        if not trade_sources_ok:
            unavailable += ["whaleTransactions", "largeTradeNetUsd"]

        if ratios and trade_sources_ok:
            status = "live"
        elif ratios or trade_sources_ok:
            status = "partial"
        else:
            status = "unavailable"

        result = {
            "status": status,
            "unavailableFields": unavailable,
            "whaleVolume24h": None,
            "whaleVolumeChange": None,
            "exchangeNetFlow": None,
            **compute_stance(ratios),
            "topTraderRatios": ratios,
            "whaleTransactions": large_trades[:MAX_WHALE_TRANSACTIONS],
            **flow,
            "largeTradeMinUsd": LARGE_TRADE_MIN_USD,
            "source": "Binance Futures FAPI (topLongShortPositionRatio, aggTrades)",
            "cachedAt": now,
        }

        if status != "unavailable":
            self._whales_cache = result
            self._whales_cache_time = now
        return result

    # -------------------------------------------------------------------- news
    async def _fetch_fear_greed(self) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._client.get("https://api.alternative.me/fng/?limit=1")
            if resp.status_code != 200:
                return None
            data = resp.json().get("data", [])
            if not data or data[0].get("value") is None:
                return None
            return {
                "value": int(data[0]["value"]),
                "classification": data[0].get("value_classification"),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch Fear & Greed index: {e}")
            return None

    async def _fetch_rss(self) -> Optional[str]:
        try:
            resp = await self._client.get("https://cointelegraph.com/rss")
            if resp.status_code != 200:
                return None
            return resp.text
        except Exception as e:
            logger.warning(f"Failed to fetch live RSS news: {e}")
            return None

    @staticmethod
    def parse_rss(xml_text: str, now: float, limit: int = 8) -> List[Dict[str, Any]]:
        """Parse RSS items into news rows; timestamps come from ``pubDate``."""
        root = ET.fromstring(xml_text)
        items: List[Dict[str, Any]] = []
        for item in root.findall(".//item")[:limit]:
            title_el = item.find("title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue
            link_el = item.find("link")
            link = (link_el.text or "").strip() if link_el is not None and link_el.text else None
            desc_el = item.find("description")
            summary = desc_el.text if desc_el is not None and desc_el.text else title
            if "<" in summary and ">" in summary:
                summary = re.sub(r"<[^>]+>", " ", summary)
                summary = re.sub(r"\s+", " ", summary).strip() or title

            published = parse_pub_date(item.findtext("pubDate"))
            classified = classify_headline(title)
            ident = hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:12]
            items.append({
                "id": f"live-news-{ident}",
                "title": title,
                "summary": summary[:220] + ("..." if len(summary) > 220 else ""),
                "source": "CoinTelegraph",
                "sourceType": "tier1",
                "timestamp": relative_time(published.timestamp(), now) if published else None,
                "publishedAt": published.isoformat() if published else None,
                "category": classified["category"],
                "sentiment": classified["sentiment"],
                # Heuristic: keyword-hit count mapped to a score, not a model output.
                "impactScore": classified["impactScore"],
                "affectedSymbols": classified["affectedSymbols"],
                # Article length is not in the feed, so no read time is claimed.
                "readTime": None,
                "linkUrl": link,
            })
        return items

    @staticmethod
    def headline_bias(news: List[Dict[str, Any]]) -> Optional[str]:
        """Net share of bullish minus bearish headlines, e.g. "+25%"."""
        if not news:
            return None
        bull = sum(1 for n in news if n["sentiment"] == "BULLISH")
        bear = sum(1 for n in news if n["sentiment"] == "BEARISH")
        return f"{round((bull - bear) / len(news) * 100):+d}%"

    async def get_news_data(self) -> Dict[str, Any]:
        """Fear & Greed index and recent headlines with real publish times."""
        now = time.time()
        if self._news_cache and (now - self._news_cache_time) < CACHE_TTL_SECONDS:
            return self._news_cache

        fng, rss_text = await asyncio.gather(self._fetch_fear_greed(), self._fetch_rss())
        now = time.time()

        news_items: List[Dict[str, Any]] = []
        if rss_text:
            try:
                news_items = self.parse_rss(rss_text, now)
            except ET.ParseError as e:
                logger.warning(f"Failed to parse RSS news: {e}")

        unavailable = []
        if fng is None:
            unavailable.append("fearAndGreed")
        if not news_items:
            unavailable += ["news", "catalystBias"]

        if fng is not None and news_items:
            status = "live"
        elif fng is not None or news_items:
            status = "partial"
        else:
            status = "unavailable"

        result = {
            "status": status,
            "unavailableFields": unavailable,
            "fearAndGreed": fng,
            # Previously Fear&Greed + 8 (meaningless). Now the net share of
            # bullish vs bearish headlines in this feed snapshot.
            "catalystBias": self.headline_bias(news_items),
            "catalystBiasBasis": "net bullish-minus-bearish headline share (keyword heuristic)",
            "news": news_items,
            "source": "Alternative.me & CoinTelegraph RSS",
            "cachedAt": now,
        }

        if status != "unavailable":
            self._news_cache = result
            self._news_cache_time = now
        return result


# Global singleton instance
intel_service = IntelService()
