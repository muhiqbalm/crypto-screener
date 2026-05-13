"""Data Processor service - orchestrates existing modules for the API pipeline.

Wraps the existing synchronous modules (ExchangeConnector, MarketDataFetcher,
SignalGenerator, ICWeightCalculator, MultiFactorScorer, RankingEngine) in an
async interface suitable for the FastAPI backend.
"""

import asyncio
import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.config.settings import Settings
from src.services.models import ProcessedResult

logger = logging.getLogger(__name__)


class DataProcessor:
    """Orchestrates existing crypto screener modules into an async pipeline.

    The processor executes the full pipeline: connect → fetch → signal → score → rank.
    Synchronous module calls are wrapped in asyncio.to_thread() for non-blocking execution.
    Per-symbol errors are collected without halting the pipeline.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize DataProcessor with application settings.

        Args:
            settings: Application settings containing symbols, exchange config, etc.
        """
        self.settings = settings
        self._symbols = settings.symbols_list
        logger.info(
            f"DataProcessor initialized with {len(self._symbols)} symbols"
        )

    async def process_all(self) -> ProcessedResult:
        """Execute the full processing pipeline.

        Pipeline stages:
        1. If mock_mode is enabled, return synthetic data immediately.
        2. Connect to exchange via ExchangeConnector.
        3. Create MarketDataFetcher with the exchange connection.
        4. Fetch data for each symbol with per-symbol error isolation.
        5. Combine results into a single DataFrame.
        6. Generate signals (reversal + momentum).
        7. Calculate IC weights and multi-factor scores.
        8. Rank assets by score.
        9. Return ProcessedResult with ranked data and any errors.

        Returns:
            ProcessedResult containing the ranked DataFrame and error list.
        """
        if self.settings.mock_mode:
            logger.info("Mock mode enabled - returning synthetic data")
            return self._generate_mock_data()

        from src.exchange.connector import ExchangeConnector

        connector = ExchangeConnector(exchange_id="binanceusdm")
        errors: list[dict] = []

        try:
            # Stage 1: Connect to exchange
            logger.info("Connecting to exchange...")
            await asyncio.to_thread(connector.connect)
            exchange = connector.get_exchange()
            logger.info("Exchange connection established")

            # Stage 2: Fetch data with per-symbol error isolation
            logger.info(f"Fetching data for {len(self._symbols)} symbols...")
            from src.data.fetcher import MarketDataFetcher

            fetcher = MarketDataFetcher(exchange, self._symbols)

            records: list[dict] = []
            for symbol in self._symbols:
                data_dict, error_info = await self._fetch_with_error_isolation(
                    fetcher, symbol
                )
                if data_dict is not None:
                    records.append(data_dict)
                if error_info is not None:
                    errors.append(error_info)

            if not records:
                logger.error("All symbol fetches failed")
                return ProcessedResult(data=pd.DataFrame(), errors=errors)

            market_data = pd.DataFrame(records)
            logger.info(
                f"Fetched data for {len(market_data)} symbols successfully"
            )

            # Stage 3: Generate signals
            logger.info("Generating trading signals...")
            from src.signals.generator import SignalGenerator

            signal_gen = SignalGenerator()

            market_data["reversal_signal"] = await asyncio.to_thread(
                signal_gen.calculate_reversal_signal, market_data
            )
            market_data["momentum_signal"] = await asyncio.to_thread(
                signal_gen.calculate_momentum_signal, market_data
            )

            # Normalize signals
            market_data["reversal_signal"] = await asyncio.to_thread(
                signal_gen.normalize_signal, market_data["reversal_signal"]
            )
            market_data["momentum_signal"] = await asyncio.to_thread(
                signal_gen.normalize_signal, market_data["momentum_signal"]
            )
            logger.info("Signals generated and normalized")

            # Stage 4: Calculate multi-factor scores
            logger.info("Calculating multi-factor scores...")
            from src.signals.ic_weights import ICWeightCalculator
            from src.signals.scorer import MultiFactorScorer

            ic_calc = ICWeightCalculator()
            scorer = MultiFactorScorer(ic_calc)

            market_data["multi_factor_score"] = await asyncio.to_thread(
                scorer.calculate_score, market_data
            )
            market_data["tier"] = await asyncio.to_thread(
                scorer.classify_tiers, market_data["multi_factor_score"]
            )
            logger.info("Multi-factor scores calculated")

            # Stage 5: Rank assets
            logger.info("Ranking assets...")
            from src.ranking.engine import RankingEngine

            ranker = RankingEngine()
            ranked_data = await asyncio.to_thread(ranker.rank_assets, market_data)
            logger.info(f"Ranking complete - {len(ranked_data)} assets ranked")

            return ProcessedResult(data=ranked_data, errors=errors)

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            errors.append({"symbol": "pipeline", "error": str(e)})
            return ProcessedResult(data=pd.DataFrame(), errors=errors)

        finally:
            # Always close the exchange connector
            try:
                if connector.exchange is not None:
                    logger.info("Closing exchange connection...")
                    await asyncio.to_thread(connector.exchange.close)
                    logger.info("Exchange connection closed")
            except Exception as e:
                logger.warning(f"Error closing exchange connection: {e}")

    async def _fetch_with_error_isolation(
        self, fetcher, symbol: str
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Fetch data for a single symbol with error isolation.

        Wraps the per-symbol fetch in a try/except so that failures for one
        symbol do not halt the entire pipeline.

        Args:
            fetcher: MarketDataFetcher instance with an active exchange connection.
            symbol: The trading pair symbol to fetch data for.

        Returns:
            A tuple of (data_dict, error_info):
            - On success: (dict with symbol data, None)
            - On failure: (None, dict with symbol and error message)
        """
        try:
            record = await asyncio.to_thread(self._fetch_symbol_data, fetcher, symbol)
            return (record, None)
        except Exception as e:
            logger.warning(f"Error fetching data for {symbol}: {e}")
            return (None, {"symbol": symbol, "error": str(e)})

    def _fetch_symbol_data(self, fetcher, symbol: str) -> dict:
        """Synchronously fetch all data fields for a single symbol.

        This method is designed to be called via asyncio.to_thread().

        Args:
            fetcher: MarketDataFetcher instance.
            symbol: The trading pair symbol.

        Returns:
            Dictionary with all data fields for the symbol.
        """
        record: dict = {
            "symbol": symbol,
            "price": np.nan,
            "change_24h": np.nan,
            "funding_rate": np.nan,
            "long_short_ratio": np.nan,
            "momentum_30d": np.nan,
            "atr_percent": np.nan,
            "distance_to_ma50": np.nan,
            "sparkline_data": None,
            "sparkline_trend": "neutral",
            "oi_delta_percent": np.nan,
            "oi_interpretation": "neutral",
        }

        # Fetch ticker data
        try:
            ticker_data = fetcher.fetch_ticker_data(symbol)
            record["price"] = ticker_data.get("price", np.nan)
            record["change_24h"] = ticker_data.get("change_24h", np.nan)
        except Exception as e:
            logger.warning(f"Failed to fetch ticker data for {symbol}: {e}")

        # Fetch funding rate
        try:
            funding_rate = fetcher.fetch_funding_rate(symbol)
            record["funding_rate"] = funding_rate if funding_rate is not None else np.nan
        except Exception as e:
            logger.warning(f"Failed to fetch funding rate for {symbol}: {e}")

        # Fetch long/short ratio
        try:
            ls_ratio = fetcher.fetch_long_short_ratio(symbol)
            record["long_short_ratio"] = ls_ratio if ls_ratio is not None else np.nan
        except Exception as e:
            logger.warning(f"Failed to fetch long/short ratio for {symbol}: {e}")

        # Calculate 30-day momentum
        try:
            momentum = fetcher.calculate_momentum_30d(symbol)
            record["momentum_30d"] = momentum if momentum is not None else np.nan
        except Exception as e:
            logger.warning(f"Failed to calculate momentum for {symbol}: {e}")

        # Calculate ATR
        try:
            atr_data = fetcher.calculate_atr(symbol)
            record["atr_percent"] = (
                atr_data["atr_percent"]
                if atr_data["atr_percent"] is not None
                else np.nan
            )
        except Exception as e:
            logger.warning(f"Failed to calculate ATR for {symbol}: {e}")

        # Calculate distance to MA50
        try:
            ma50_data = fetcher.calculate_distance_to_ma50(symbol)
            record["distance_to_ma50"] = (
                ma50_data["distance_percent"]
                if ma50_data["distance_percent"] is not None
                else np.nan
            )
        except Exception as e:
            logger.warning(f"Failed to calculate MA50 distance for {symbol}: {e}")

        # Fetch sparkline data
        try:
            sparkline_data = fetcher.fetch_sparkline_data(symbol)
            record["sparkline_data"] = (
                sparkline_data["prices"]
                if sparkline_data["prices"] is not None
                else None
            )
            record["sparkline_trend"] = (
                sparkline_data["trend"]
                if sparkline_data["trend"] is not None
                else "neutral"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch sparkline data for {symbol}: {e}")

        # Calculate OI delta
        try:
            oi_data = fetcher.calculate_oi_delta(symbol)
            record["oi_delta_percent"] = (
                oi_data["oi_delta_percent"]
                if oi_data["oi_delta_percent"] is not None
                else np.nan
            )
            record["oi_interpretation"] = (
                oi_data["interpretation"]
                if oi_data["interpretation"] is not None
                else "neutral"
            )
        except Exception as e:
            logger.warning(f"Failed to calculate OI delta for {symbol}: {e}")

        return record

    def _generate_mock_data(self) -> ProcessedResult:
        """Generate synthetic data for testing without exchange connectivity.

        Creates a DataFrame with all expected columns populated with random
        but realistic values for the configured symbols.

        Returns:
            ProcessedResult with synthetic data and no errors.
        """
        rng = np.random.default_rng(seed=42)
        symbols = self._symbols
        n = len(symbols)

        records = []
        for i, symbol in enumerate(symbols):
            records.append(
                {
                    "symbol": symbol,
                    "price": rng.uniform(0.5, 70000.0),
                    "change_24h": rng.uniform(-15.0, 15.0),
                    "funding_rate": rng.uniform(-0.1, 0.1),
                    "long_short_ratio": rng.uniform(0.5, 3.0),
                    "momentum_30d": rng.uniform(-30.0, 30.0),
                    "atr_percent": rng.uniform(1.0, 10.0),
                    "distance_to_ma50": rng.uniform(-20.0, 20.0),
                    "sparkline_data": [
                        float(rng.uniform(100, 200)) for _ in range(7)
                    ],
                    "sparkline_trend": rng.choice(
                        ["bullish", "bearish", "neutral"]
                    ),
                    "oi_delta_percent": rng.uniform(-10.0, 10.0),
                    "oi_interpretation": rng.choice(
                        ["bullish", "bearish", "neutral"]
                    ),
                }
            )

        df = pd.DataFrame(records)

        # Generate signals
        from src.signals.generator import SignalGenerator
        from src.signals.ic_weights import ICWeightCalculator
        from src.signals.scorer import MultiFactorScorer
        from src.ranking.engine import RankingEngine

        signal_gen = SignalGenerator()
        df["reversal_signal"] = signal_gen.calculate_reversal_signal(df)
        df["momentum_signal"] = signal_gen.calculate_momentum_signal(df)
        df["reversal_signal"] = signal_gen.normalize_signal(df["reversal_signal"])
        df["momentum_signal"] = signal_gen.normalize_signal(df["momentum_signal"])

        ic_calc = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calc)
        df["multi_factor_score"] = scorer.calculate_score(df)
        df["tier"] = scorer.classify_tiers(df["multi_factor_score"])

        ranker = RankingEngine()
        ranked_df = ranker.rank_assets(df)

        logger.info(f"Generated mock data for {n} symbols")
        return ProcessedResult(data=ranked_df, errors=[])
