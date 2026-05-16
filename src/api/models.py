"""Pydantic response models for the crypto screener API.

Defines all request/response schemas used by the API endpoints.
All numeric metric fields use Optional[float] with None default to handle
missing data gracefully (serialized as JSON null).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ResponseMetadata(BaseModel):
    """Metadata included in every API response."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime = Field(description="UTC timestamp of the response")
    data_age_seconds: Optional[float] = Field(
        default=None,
        description="Seconds since the underlying data was last fetched from the exchange",
    )
    cache_hit: bool = Field(
        default=False,
        description="Whether the response was served from cache",
    )
    stale_data_warning: Optional[bool] = Field(
        default=None,
        description="True if data age exceeds 300 seconds (5 minutes)",
    )
    symbols_count: int = Field(
        default=0,
        description="Number of symbols in the dataset",
    )
    errors_count: int = Field(
        default=0,
        description="Number of per-symbol errors encountered during data fetch",
    )


class MarketOverview(BaseModel):
    """Aggregated market statistics across all tracked assets."""

    model_config = ConfigDict(from_attributes=True)

    avg_change_24h: Optional[float] = Field(
        default=None,
        description="Average 24-hour price change percentage across all assets",
    )
    avg_funding_rate: Optional[float] = Field(
        default=None,
        description="Average perpetual swap funding rate across all assets",
    )
    total_volume: Optional[float] = Field(
        default=None,
        description="Sum of 24-hour trading volume (USD) across all assets",
    )
    bullish_count: int = Field(
        default=0,
        description="Number of assets with BULLISH signal (risk_adjusted_score > 0.5)",
    )
    bearish_count: int = Field(
        default=0,
        description="Number of assets with BEARISH signal (risk_adjusted_score < -0.5)",
    )
    neutral_count: int = Field(
        default=0,
        description="Number of assets with NEUTRAL signal (-0.5 ≤ risk_adjusted_score ≤ 0.5)",
    )
    avg_risk_adjusted_score: Optional[float] = Field(
        default=None,
        description="Average risk-adjusted score across all assets (multi_factor_score / ATR penalty)",
    )
    tier_a_count: int = Field(
        default=0,
        description="Number of assets in Tier A (top 33% — strong buy candidates)",
    )
    tier_b_count: int = Field(
        default=0,
        description="Number of assets in Tier B (middle 34% — moderate/hold)",
    )
    tier_c_count: int = Field(
        default=0,
        description="Number of assets in Tier C (bottom 33% — avoid/short candidates)",
    )


class AssetSummary(BaseModel):
    """Brief summary of an asset for top-N display."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(description="Trading pair symbol (e.g. BTC/USDT:USDT)")
    rank: Optional[int] = Field(
        default=None,
        description="Overall rank by risk-adjusted score (1 = highest)",
    )
    composite_score: Optional[float] = Field(
        default=None,
        description="Risk-adjusted composite score combining all 5 signal factors",
    )
    signal: Optional[str] = Field(
        default=None,
        description="Trading signal direction: BULLISH, BEARISH, or NEUTRAL",
    )


class AssetDetail(BaseModel):
    """Full detail for a single asset with all metric fields.

    The composite score is a risk-adjusted, 5-factor weighted score derived from:
    momentum (30d), reversal (1d), funding rate (contrarian), sentiment (L/S ratio),
    and OI-price momentum signals. Assets are classified into tiers A/B/C by percentile.
    """

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(description="Trading pair symbol (e.g. BTC/USDT:USDT)")
    rank: Optional[int] = Field(
        default=None,
        description="Overall rank by risk-adjusted score (1 = highest)",
    )
    composite_score: Optional[float] = Field(
        default=None,
        description="Risk-adjusted composite score (multi_factor_score / ATR volatility penalty)",
    )
    signal: Optional[str] = Field(
        default=None,
        description="Aggregate trading signal: BULLISH (score > 0.5), BEARISH (< -0.5), or NEUTRAL",
    )
    price: Optional[float] = Field(
        default=None,
        description="Current price in USD",
    )
    change_24h: Optional[float] = Field(
        default=None,
        description="24-hour price change percentage",
    )
    volume_24h: Optional[float] = Field(
        default=None,
        description="24-hour trading volume in USD",
    )
    funding_rate: Optional[float] = Field(
        default=None,
        description="Current perpetual swap funding rate (e.g. 0.01 = 1%)",
    )
    open_interest: Optional[float] = Field(
        default=None,
        description="Total open interest in USD",
    )
    long_short_ratio: Optional[float] = Field(
        default=None,
        description="Long/short account ratio (> 1 = more longs, < 1 = more shorts)",
    )
    reversal_score: Optional[float] = Field(
        default=None,
        description="Reversal score (0-100 scale). Derived from normalized reversal z-score: 50 = neutral, < 30 = strong reversal potential upward, > 70 = strong reversal potential downward. NOT a standard RSI calculation.",
    )
    macd_signal: Optional[str] = Field(
        default=None,
        description="MACD-derived signal: BUY (momentum z > 0.5), SELL (< -0.5), or HOLD",
    )
    volatility: Optional[float] = Field(
        default=None,
        description="ATR percentage — average true range as percentage of price",
    )
    ic_weight: Optional[float] = Field(
        default=None,
        description="Suggested portfolio weight (0-1 range), derived from inverse-volatility position sizing",
    )
    risk_adjusted_score: Optional[float] = Field(
        default=None,
        description="Risk-adjusted score = multi_factor_score / max(atr_percent, 1.0). Penalizes volatile assets",
    )
    suggested_position_pct: Optional[float] = Field(
        default=None,
        description="Suggested position size as percentage of portfolio (sums to 100% across all assets), based on inverse volatility weighting",
    )
    tier: Optional[str] = Field(
        default=None,
        description="Classification tier: A (top 33% — buy), B (middle 34% — hold), C (bottom 33% — avoid)",
    )
    funding_rate_signal: Optional[str] = Field(
        default=None,
        description="Funding rate sub-signal direction: BULLISH (negative funding), BEARISH (positive funding), or NEUTRAL",
    )
    oi_signal: Optional[str] = Field(
        default=None,
        description="Open Interest momentum sub-signal: BULLISH (OI↑+Price↑ or short squeeze), BEARISH (OI↑+Price↓ or long liquidation), or NEUTRAL",
    )


class SummaryData(BaseModel):
    """Summary section containing top assets and market overview."""

    model_config = ConfigDict(from_attributes=True)

    top_3_assets: list[AssetSummary] = Field(
        default=[],
        description="Top 3 ranked assets by risk-adjusted score",
    )
    market_overview: MarketOverview = Field(
        default=MarketOverview(),
        description="Aggregated market statistics and tier distribution",
    )


class ScreenerResponse(BaseModel):
    """Response for GET /api/v1/screener/summary endpoint."""

    model_config = ConfigDict(from_attributes=True)

    metadata: ResponseMetadata = Field(description="Response metadata including cache info and data age")
    summary: SummaryData = Field(description="Market overview and top 3 assets summary")
    assets: Optional[list[AssetDetail]] = Field(
        default=None,
        description="Full list of all ranked assets with detailed metrics. Omitted when summary_only=true",
    )


class AssetDetailResponse(BaseModel):
    """Response for GET /api/v1/screener/assets/{symbol} endpoint."""

    model_config = ConfigDict(from_attributes=True)

    metadata: ResponseMetadata = Field(description="Response metadata including cache info and data age")
    asset: AssetDetail = Field(description="Complete asset detail with all scoring and market metrics")


class CacheStatus(BaseModel):
    """Cache status information for health check."""

    model_config = ConfigDict(from_attributes=True)

    data_age_seconds: Optional[float] = Field(
        default=None,
        description="Seconds since cached data was last refreshed",
    )
    is_stale: bool = Field(
        default=False,
        description="Whether cached data has exceeded TTL and needs refresh",
    )
    next_refresh_in: Optional[float] = Field(
        default=None,
        description="Seconds until next automatic cache refresh",
    )


class HealthResponse(BaseModel):
    """Response for GET /api/v1/health endpoint."""

    model_config = ConfigDict(from_attributes=True)

    status: str = Field(description="Health status: 'healthy' or 'degraded' (stale cache)")
    uptime_seconds: float = Field(description="Server uptime in seconds since startup")
    cache_status: CacheStatus = Field(
        default=CacheStatus(),
        description="Current cache state and refresh timing",
    )
    version: str = Field(default="1.0.0", description="API version string")


class ErrorResponse(BaseModel):
    """Standard error response body."""

    model_config = ConfigDict(from_attributes=True)

    error: str = Field(description="Error category (e.g. 'Not Found', 'Internal Server Error')")
    message: str = Field(description="Human-readable error description")
    available_symbols: Optional[list[str]] = Field(
        default=None,
        description="List of valid symbols (included on 404 errors)",
    )
    timestamp: datetime = Field(description="UTC timestamp when error occurred")
