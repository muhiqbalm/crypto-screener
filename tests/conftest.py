"""Shared pytest fixtures for the crypto screener API test suite.

Provides:
- mock_settings: Settings instance with mock_mode=True and test symbols
- sample_df: DataFrame with realistic crypto data for 5 symbols
- mock_data_processor: AsyncMock returning a ProcessedResult with sample_df
- mock_cache_manager: CacheManager pre-loaded with sample data
- test_app: FastAPI app created with create_app() using mock settings
- async_client: httpx AsyncClient using ASGITransport with the test_app

Requirements: 11.4
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config.settings import Settings
from src.services.cache_manager import CacheManager
from src.services.models import ProcessedResult


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings() -> Settings:
    """Settings instance configured for testing with mock_mode=True.

    Uses a small set of test symbols and short cache TTL.
    """
    return Settings(
        api_host="127.0.0.1",
        api_port=8000,
        cache_ttl=60,
        log_level="DEBUG",
        symbols="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,AAVE/USDT:USDT,LINK/USDT:USDT",
        mock_mode=True,
        cors_origins="*",
        shutdown_timeout=5,
    )


# ---------------------------------------------------------------------------
# Sample DataFrame fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_df() -> pd.DataFrame:
    """DataFrame with realistic crypto screener data for 5 symbols.

    Contains all columns expected by the ResponseBuilder and API routes:
    symbol, price, change_24h, funding_rate, long_short_ratio, momentum_30d,
    reversal_signal, momentum_signal, multi_factor_score, tier, rank,
    atr_percent, distance_to_ma50, oi_delta_percent, composite_score,
    signal, volume_24h, open_interest, reversal_score, macd_signal, volatility, ic_weight.
    """
    data = {
        "symbol": [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
            "AAVE/USDT:USDT",
            "LINK/USDT:USDT",
        ],
        "price": [67500.0, 3450.0, 145.0, 92.0, 14.5],
        "change_24h": [2.35, -1.20, 5.80, -0.45, 3.10],
        "volume_24h": [28000000000.0, 15000000000.0, 3500000000.0, 450000000.0, 800000000.0],
        "funding_rate": [0.0100, -0.0050, 0.0200, 0.0010, -0.0030],
        "open_interest": [18000000000.0, 8000000000.0, 2000000000.0, 300000000.0, 500000000.0],
        "long_short_ratio": [1.25, 0.85, 1.80, 1.10, 0.95],
        "momentum_30d": [12.5, -5.3, 25.0, 3.2, 8.7],
        "reversal_signal": [0.65, 0.30, 0.80, 0.45, 0.55],
        "momentum_signal": [0.70, 0.25, 0.90, 0.50, 0.60],
        "multi_factor_score": [0.85, 0.45, 0.92, 0.55, 0.70],
        "composite_score": [0.85, 0.45, 0.92, 0.55, 0.70],
        "tier": ["Tier 1", "Tier 3", "Tier 1", "Tier 2", "Tier 2"],
        "rank": [2, 5, 1, 4, 3],
        "signal": ["BULLISH", "BEARISH", "BULLISH", "NEUTRAL", "BULLISH"],
        "atr_percent": [3.5, 4.2, 6.8, 5.1, 4.0],
        "distance_to_ma50": [5.2, -3.1, 12.0, 1.5, 4.8],
        "oi_delta_percent": [2.5, -1.8, 5.0, 0.3, 1.2],
        "reversal_score": [62.0, 38.0, 72.0, 50.0, 58.0],
        "macd_signal": ["BULLISH", "BEARISH", "BULLISH", "NEUTRAL", "BULLISH"],
        "volatility": [0.035, 0.042, 0.068, 0.051, 0.040],
        "ic_weight": [0.25, 0.15, 0.30, 0.12, 0.18],
    }
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# ProcessedResult fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_processed_result(sample_df) -> ProcessedResult:
    """ProcessedResult wrapping the sample_df with no errors."""
    return ProcessedResult(
        data=sample_df,
        errors=[],
        processed_at=datetime(2025, 1, 15, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# Mock DataProcessor fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_data_processor(sample_processed_result) -> AsyncMock:
    """AsyncMock DataProcessor whose process_all() returns sample data.

    Usage in tests:
        app.state.data_processor = mock_data_processor
    """
    processor = AsyncMock()
    processor.process_all.return_value = sample_processed_result
    processor.settings = Settings(
        mock_mode=True,
        symbols="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,AAVE/USDT:USDT,LINK/USDT:USDT",
    )
    return processor


# ---------------------------------------------------------------------------
# Mock CacheManager fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cache_manager(sample_processed_result) -> CacheManager:
    """CacheManager pre-loaded with sample data (cache is warm).

    The cache entry is fresh (just stored), so get() will return data.
    """
    cache = CacheManager(ttl=60)
    cache.set(sample_processed_result)
    return cache


# ---------------------------------------------------------------------------
# Mock ResponseBuilder fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_response_builder():
    """ResponseBuilder instance for testing.

    ResponseBuilder is stateless, so we can use a real instance.
    """
    from src.services.response_builder import ResponseBuilder
    return ResponseBuilder()


# ---------------------------------------------------------------------------
# FastAPI test app fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def test_app(mock_settings, mock_data_processor, mock_cache_manager, mock_response_builder):
    """FastAPI app configured for testing with mock dependencies.

    Patches Settings so create_app() uses mock_settings, then overrides
    app.state with mock services.
    """
    import time
    
    with patch("src.api.app.Settings", return_value=mock_settings):
        from src.api.app import create_app

        app = create_app()

    # Override state with test fixtures
    app.state.settings = mock_settings
    app.state.data_processor = mock_data_processor
    app.state.cache_manager = mock_cache_manager
    app.state.response_builder = mock_response_builder
    app.state.start_time = time.time()  # Add start_time for health endpoint

    return app


# ---------------------------------------------------------------------------
# Async HTTP client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_client(test_app):
    """httpx AsyncClient wired to the test FastAPI app via ASGITransport.

    Provides a fully functional HTTP client for testing API endpoints
    without starting a real server.
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
