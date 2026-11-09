"""Regression tests for the screener data-honesty fixes (B2-B16, Nov 2026)."""

import asyncio
import re
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.data.fetcher import MarketDataFetcher
from src.services.cache_manager import CacheManager
from src.services.intel_service import (
    IntelService,
    classify_headline,
    compute_stance,
    extract_large_trades,
    parse_pub_date,
)
from src.services.models import ProcessedResult
from src.services.response_builder import ResponseBuilder
from src.signals.generator import SignalGenerator
from src.signals.ic_weights import ICWeightCalculator
from src.signals.scorer import MultiFactorScorer


def _row(**kw):
    base = {"symbol": "X/USDT:USDT", "rank": 1, "risk_adjusted_score": 0.01}
    base.update(kw)
    return pd.Series(base)


# ---------------------------------------------------------------- B2 price
class TestPricePrecision:
    @pytest.mark.parametrize("price", [0.00001234, 0.000000987654, 0.01523, 0.0042])
    def test_sub_cent_prices_are_not_zeroed(self, price):
        asset = ResponseBuilder()._build_asset(_row(price=price))
        assert asset.price is not None and asset.price > 0
        assert asset.price == pytest.approx(price, rel=1e-7)

    def test_large_price_keeps_cents(self):
        asset = ResponseBuilder()._build_asset(_row(price=97123.456789))
        assert asset.price == pytest.approx(97123.457, abs=1e-3)

    def test_small_funding_rate_preserved(self):
        asset = ResponseBuilder()._build_asset(_row(funding_rate=0.000123456))
        assert asset.funding_rate == pytest.approx(0.000123456, rel=1e-7)

    def test_sig_rounding_handles_none_nan_zero(self):
        rb = ResponseBuilder()
        assert rb._sanitize_sig(None) is None
        assert rb._sanitize_sig(float("nan")) is None
        assert rb._sanitize_sig(0) == 0.0


# ------------------------------------------------------------ B5 open interest
class TestOpenInterestUsd:
    def test_open_interest_is_usd_notional(self):
        # ~74k BTC of OI at $97k -> ~$7.2B, not "$74K".
        asset = ResponseBuilder()._build_asset(_row(price=97_000.0, open_interest=74_000.0))
        assert asset.open_interest == pytest.approx(74_000.0 * 97_000.0)
        assert asset.open_interest_coins == pytest.approx(74_000.0)

    def test_missing_price_gives_null_usd(self):
        asset = ResponseBuilder()._build_asset(_row(price=np.nan, open_interest=10.0))
        assert asset.open_interest is None
        assert asset.open_interest_coins == pytest.approx(10.0)

    def test_explicit_usd_column_wins(self):
        asset = ResponseBuilder()._build_asset(
            _row(price=2.0, open_interest=10.0, open_interest_usd=123.0)
        )
        assert asset.open_interest == 123.0


# ---------------------------------------------- B6 tier/rank + B8 confidence
def _scored_frame(n=30, seed=7):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "symbol": [f"S{i}" for i in range(n)],
        "change_24h": rng.normal(0, 4, n),
        "momentum_30d": rng.normal(0, 20, n),
        "funding_rate": rng.normal(0, 0.01, n),
        "long_short_ratio": rng.uniform(0.6, 2.5, n),
        "oi_delta_percent": rng.normal(0, 5, n),
        # Wide ATR spread so ranking by raw vs risk-adjusted score differs.
        "atr_percent": rng.uniform(1.0, 15.0, n),
    })
    gen = SignalGenerator()
    for col, fn in [
        ("reversal_signal", gen.calculate_reversal_signal),
        ("momentum_signal", gen.calculate_momentum_signal),
        ("funding_rate_signal", gen.calculate_funding_rate_signal),
        ("sentiment_signal", gen.calculate_sentiment_signal),
        ("oi_momentum_signal", gen.calculate_oi_momentum_signal),
    ]:
        df[col] = gen.normalize_signal(fn(df))
    return df


class TestTierRankConsistency:
    def test_mock_pipeline_tiers_follow_rank(self):
        from src.services.data_processor import DataProcessor

        settings = MagicMock()
        settings.symbols_list = [f"S{i}/USDT:USDT" for i in range(12)]
        settings.mock_mode = True
        df = DataProcessor(settings)._generate_mock_data().data
        order = {"A": 0, "B": 1, "C": 2}
        tiers = [order[t] for t in df.sort_values("rank")["tier"]]
        assert tiers == sorted(tiers), "a better-ranked asset must never have a worse tier"
        assert df.sort_values("rank").iloc[0]["tier"] == "A"


class TestConfidence:
    def _confidence(self, df):
        scorer = MultiFactorScorer(ICWeightCalculator())
        df["multi_factor_score"] = scorer.calculate_score(df)
        df = scorer.calculate_risk_adjusted_score(df)
        return scorer.calculate_confidence_rate(df)

    def test_all_tiers_reachable_on_realistic_data(self):
        tiers = set()
        for seed in range(5):
            tiers |= set(self._confidence(_scored_frame(40, seed))["confidence_tier"])
        assert {"HIGH", "MEDIUM", "LOW"} <= tiers

    def test_strong_outlier_with_full_confluence_is_high(self):
        n = 10
        df = pd.DataFrame({
            "risk_adjusted_score": [0.05] + [0.001 * i for i in range(n - 1)],
            **{c: [1.0] + [0.0] * (n - 1) for c in [
                "reversal_signal", "momentum_signal", "funding_rate_signal",
                "sentiment_signal", "oi_momentum_signal"]},
        })
        out = MultiFactorScorer(ICWeightCalculator()).calculate_confidence_rate(df)
        assert out.loc[0, "confidence_tier"] == "HIGH"
        assert 0 <= out["confidence_pct"].min() and out["confidence_pct"].max() <= 100

    def test_single_asset_does_not_crash(self):
        df = pd.DataFrame({"risk_adjusted_score": [0.02], "momentum_signal": [0.3]})
        out = MultiFactorScorer(ICWeightCalculator()).calculate_confidence_rate(df)
        assert out.loc[0, "confidence_tier"] in {"LOW", "MEDIUM", "HIGH"}


# ----------------------------------------------------------- B14 momentum label
class TestMomentumLabel:
    def test_momentum_signal_field_and_deprecated_alias(self):
        asset = ResponseBuilder()._build_asset(_row(momentum_signal=1.2))
        assert asset.momentum_signal == "BUY"
        assert asset.macd_signal == asset.momentum_signal

    def test_weights_are_labelled_static(self):
        assert ICWeightCalculator.WEIGHTS_SOURCE == "static_heuristic"


# -------------------------------------------------------------- B13 caching
class TestEmptyResultsNotCached:
    def test_empty_result_is_rejected_and_previous_kept(self):
        cm = CacheManager(ttl=60)
        good = ProcessedResult(data=pd.DataFrame({"symbol": ["BTC"]}), errors=[])
        assert cm.set(good) is True
        assert cm.set(ProcessedResult(data=pd.DataFrame(), errors=[{"symbol": "x"}])) is False
        assert cm.get().result is good

    def test_empty_result_on_cold_cache_stays_empty(self):
        cm = CacheManager(ttl=60)
        assert cm.set(ProcessedResult(data=pd.DataFrame(), errors=[])) is False
        assert cm.get() is None and cm.get_last_good() is None

    def test_route_serves_stale_data_when_fetch_is_empty(self):
        from src.api.routes import _fetch_fresh_or_stale

        cm = CacheManager(ttl=0)
        good = ProcessedResult(data=pd.DataFrame({"symbol": ["BTC"]}), errors=[])
        cm.set(good)
        processor = MagicMock()

        async def _empty():
            return ProcessedResult(data=pd.DataFrame(), errors=[{"symbol": "pipeline", "error": "down"}])

        processor.process_all = _empty
        result, cache_hit, _age = asyncio.run(_fetch_fresh_or_stale(processor, cm))
        assert cache_hit is True
        assert list(result.data["symbol"]) == ["BTC"]
        assert result.errors == [{"symbol": "pipeline", "error": "down"}]


# ------------------------------------------------- B16 exchange reuse + dedupe
def _candles(n):
    return [[i, 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i, 10.0] for i in range(n)]


class TestFetchDedup:
    def test_daily_ohlcv_fetched_once_per_symbol(self):
        ex = MagicMock()
        ex.fetch_ohlcv.side_effect = lambda s, tf, limit: _candles(limit)
        f = MarketDataFetcher(ex, ["BTC/USDT:USDT"], memoize=True)
        f.calculate_momentum_30d("BTC/USDT:USDT")
        f.calculate_atr("BTC/USDT:USDT")
        f.calculate_distance_to_ma50("BTC/USDT:USDT")
        daily = [c for c in ex.fetch_ohlcv.call_args_list if c.args[1] == "1d"]
        assert len(daily) == 1
        # Slices match what an unmemoized fetch would return.
        assert f.fetch_ohlcv("BTC/USDT:USDT", "1d", limit=31) == _candles(50)[-31:]

    def test_ticker_and_current_oi_reused(self):
        ex = MagicMock()
        ex.fetch_ticker.return_value = {"last": 2.0, "percentage": 1.0, "quoteVolume": 5.0}
        ex.fetch_open_interest.return_value = {"openInterestAmount": 100.0}
        f = MarketDataFetcher(ex, ["X/USDT:USDT"], memoize=True)
        f.fetch_ticker_data("X/USDT:USDT")
        f.fetch_ticker_data("X/USDT:USDT")
        assert f.fetch_open_interest("X/USDT:USDT") == 100.0
        with patch("requests.get") as rget:
            assert f._fetch_current_oi("X/USDT:USDT") == 100.0
            rget.assert_not_called()
        assert ex.fetch_ticker.call_count == 1

    def test_unmemoized_behaviour_unchanged(self):
        ex = MagicMock()
        ex.fetch_ohlcv.side_effect = lambda s, tf, limit: _candles(limit)
        f = MarketDataFetcher(ex, ["BTC/USDT:USDT"])
        f.fetch_ohlcv("BTC/USDT:USDT", "1d", limit=31)
        f.fetch_ohlcv("BTC/USDT:USDT", "1d", limit=31)
        assert ex.fetch_ohlcv.call_count == 2

    def test_data_processor_reuses_exchange_and_never_calls_close(self):
        from src.services.data_processor import DataProcessor

        settings = MagicMock()
        settings.symbols_list = ["BTC/USDT:USDT"]
        settings.mock_mode = False
        dp = DataProcessor(settings)
        with patch("src.exchange.connector.ExchangeConnector") as MockConn:
            inst = MockConn.return_value
            inst.exchange = MagicMock(spec=["load_markets", "session"])
            inst.get_exchange.return_value = inst.exchange
            asyncio.run(dp._get_exchange())
            asyncio.run(dp._get_exchange())
            assert MockConn.call_count == 1
            assert inst.connect.call_count == 1
            dp.close()
            inst.exchange.session.close.assert_called_once()


# ---------------------------------------------------- B9 / B15 whale radar
def _agg(a, price, qty, maker, t):
    return {"a": a, "p": str(price), "q": str(qty), "m": maker, "T": t}


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class TestWhaleRadar:
    def test_stance_majority_side_and_neutral_band(self):
        mk = lambda p: [{"longPct": p, "shortPct": 100 - p}]
        assert compute_stance(mk(55.0))["topTraderBias"] == "55.0% Long"
        assert compute_stance(mk(52.0))["smartMoneyStanceCode"] == "neutral"
        assert compute_stance(mk(58.0))["smartMoneyStanceCode"] == "bullish"
        bear = compute_stance(mk(40.0))
        assert bear["smartMoneyStanceCode"] == "bearish" and bear["topTraderBias"] == "60.0% Short"
        assert compute_stance([])["smartMoneyStance"] is None

    def test_large_trades_use_real_side_and_time(self):
        now_ms = 1_800_000_000_000
        rows = extract_large_trades("ETHUSDT", [
            _agg(1, 3000, 100, True, now_ms - 120_000),   # $300k taker sell
            _agg(2, 3000, 1, False, now_ms),              # $3k: ignored
            _agg(3, 3000, 20, False, now_ms - 5_000),     # $60k taker buy
        ], now=now_ms / 1000)
        assert [r["id"] for r in rows] == ["tx-fapi-ETH-1", "tx-fapi-ETH-3"]
        assert rows[0]["side"] == "SELL" and rows[0]["type"] == "inflow"
        assert rows[1]["side"] == "BUY" and rows[1]["type"] == "outflow"
        assert rows[0]["timestamp"] == "2 mins ago"
        assert rows[0]["tradeTime"] == now_ms - 120_000

    def test_all_sources_down_returns_unavailable_without_fake_numbers(self):
        svc = IntelService()

        async def fail(*a, **k):
            raise RuntimeError("network down")

        svc._client.get = fail
        out = asyncio.run(svc.get_whales_data())
        assert out["status"] == "unavailable"
        assert out["topTraderRatios"] == [] and out["whaleTransactions"] == []
        for key in ("whaleVolume24h", "whaleVolumeChange", "exchangeNetFlow", "topTraderBias"):
            assert out[key] is None
        assert svc._whales_cache is None  # failed snapshot not cached

    def test_live_snapshot(self):
        svc = IntelService()
        import time as _t
        now_ms = int(_t.time() * 1000)

        async def fake_get(url, params=None):
            if "topLongShortPositionRatio" in url:
                return _Resp(200, [{"longAccount": "0.62", "shortAccount": "0.38", "longShortRatio": "1.63", "timestamp": now_ms}])
            if "aggTrades" in url:
                return _Resp(200, [_agg(9, 100_000, 2, False, now_ms - 1000)])
            raise AssertionError(url)

        svc._client.get = fake_get
        out = asyncio.run(svc.get_whales_data())
        assert out["status"] == "live"
        assert all(r["updated"] == "Live FAPI" for r in out["topTraderRatios"])
        assert out["smartMoneyStanceCode"] == "bullish"
        assert out["largeTradeNetUsd"] == pytest.approx(3 * 200_000.0)
        assert all(t["id"].startswith("tx-fapi-") for t in out["whaleTransactions"])
        assert "whaleVolume24h" in out["unavailableFields"]

    def test_no_hardcoded_placeholder_values_in_source(self):
        import inspect
        import src.services.intel_service as mod

        src = inspect.getsource(mod)
        for fake in ("1,482,850,000", "342.5M", "Coinbase Prime", "fallback-01", "mins ago\"", "Cached"):
            assert fake not in src


# ----------------------------------------------------------------- B11 news
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Bitcoin rallies to record high as ETF inflows surge</title>
<link>https://example.com/a</link><description>&lt;p&gt;Body&lt;/p&gt;</description>
<pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Ethereum developers discuss roadmap whether or not secondary markets react</title>
<link>https://example.com/b</link><pubDate>Mon, 09 Nov 2026 09:00:00 +0000</pubDate></item>
<item><title>SEC sues exchange over fraud</title><link>https://example.com/c</link></item>
</channel></rss>"""


class TestNews:
    def test_word_boundary_matching(self):
        # "bull" inside "bulletin", "sec" inside "second", "eth" inside "whether"
        out = classify_headline("Weekly bulletin: second whether")
        assert out["sentiment"] == "NEUTRAL"
        assert out["affectedSymbols"] == ["CRYPTO"]
        assert classify_headline("SEC opens investigation")["sentiment"] == "BEARISH"
        assert classify_headline("SEC opens investigation")["category"] == "Regulatory"
        assert classify_headline("Bitcoin bulls return")["affectedSymbols"] == ["BTC"]

    def test_real_publish_timestamps(self):
        from datetime import datetime, timezone

        now = datetime(2026, 11, 9, 10, 30, tzinfo=timezone.utc).timestamp()
        items = IntelService.parse_rss(RSS, now)
        assert items[0]["publishedAt"] == "2026-11-09T10:00:00+00:00"
        assert items[0]["timestamp"] == "30 mins ago"
        assert items[1]["timestamp"] == "1 hour ago"
        assert items[2]["timestamp"] is None and items[2]["publishedAt"] is None
        assert items[0]["sentiment"] == "BULLISH"
        assert items[1]["sentiment"] == "NEUTRAL"
        assert items[1]["affectedSymbols"] == ["ETH"]
        assert items[0]["summary"] == "Body"
        assert all(i["id"].startswith("live-news-") for i in items)
        assert parse_pub_date("garbage") is None

    def test_failures_return_nulls_not_placeholders(self):
        svc = IntelService()

        async def fail(*a, **k):
            return _Resp(503)

        svc._client.get = fail
        out = asyncio.run(svc.get_news_data())
        assert out["status"] == "unavailable"
        assert out["fearAndGreed"] is None
        assert out["news"] == []
        assert out["catalystBias"] is None
        assert svc._news_cache is None

    def test_catalyst_bias_from_headlines(self):
        news = [{"sentiment": "BULLISH"}, {"sentiment": "BULLISH"}, {"sentiment": "BEARISH"}, {"sentiment": "NEUTRAL"}]
        assert IntelService.headline_bias(news) == "+25%"
        assert IntelService.headline_bias([]) is None
