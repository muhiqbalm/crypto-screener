"""Pydantic response models for the crypto screener API.

Defines all request/response schemas used by the API endpoints.
All numeric metric fields use Optional[float] with None default to handle
missing data gracefully (serialized as JSON null).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ResponseMetadata(BaseModel):
    """Metadata included in every API response."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    data_age_seconds: Optional[float] = None
    cache_hit: bool = False
    stale_data_warning: Optional[bool] = None
    symbols_count: int = 0
    errors_count: int = 0


class MarketOverview(BaseModel):
    """Aggregated market statistics across all tracked assets."""

    model_config = ConfigDict(from_attributes=True)

    avg_change_24h: Optional[float] = None
    avg_funding_rate: Optional[float] = None
    total_volume: Optional[float] = None
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0


class AssetSummary(BaseModel):
    """Brief summary of an asset for top-N display."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    rank: Optional[int] = None
    composite_score: Optional[float] = None
    signal: Optional[str] = None


class AssetDetail(BaseModel):
    """Full detail for a single asset with all metric fields."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    rank: Optional[int] = None
    composite_score: Optional[float] = None
    signal: Optional[str] = None
    price: Optional[float] = None
    change_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    long_short_ratio: Optional[float] = None
    rsi: Optional[float] = None
    macd_signal: Optional[str] = None
    volatility: Optional[float] = None
    ic_weight: Optional[float] = None


class SummaryData(BaseModel):
    """Summary section containing top assets and market overview."""

    model_config = ConfigDict(from_attributes=True)

    top_3_assets: list[AssetSummary] = []
    market_overview: MarketOverview = MarketOverview()


class ScreenerResponse(BaseModel):
    """Response for GET /api/v1/screener/summary endpoint."""

    model_config = ConfigDict(from_attributes=True)

    metadata: ResponseMetadata
    summary: SummaryData
    assets: Optional[list[AssetDetail]] = None


class AssetDetailResponse(BaseModel):
    """Response for GET /api/v1/screener/assets/{symbol} endpoint."""

    model_config = ConfigDict(from_attributes=True)

    metadata: ResponseMetadata
    asset: AssetDetail


class CacheStatus(BaseModel):
    """Cache status information for health check."""

    model_config = ConfigDict(from_attributes=True)

    data_age_seconds: Optional[float] = None
    is_stale: bool = False
    next_refresh_in: Optional[float] = None


class HealthResponse(BaseModel):
    """Response for GET /api/v1/health endpoint."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    uptime_seconds: float
    cache_status: CacheStatus = CacheStatus()
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    """Standard error response body."""

    model_config = ConfigDict(from_attributes=True)

    error: str
    message: str
    available_symbols: Optional[list[str]] = None
    timestamp: datetime
