"""Response builder service for converting DataFrames to API response models.

Transforms processed pandas DataFrames into structured Pydantic response
objects suitable for JSON serialization. Handles NaN/None sanitization,
numeric precision formatting, and summary aggregation.
"""

import math
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.api.models import (
    AssetDetail,
    AssetDetailResponse,
    AssetSummary,
    MarketOverview,
    ResponseMetadata,
    ScreenerResponse,
    SummaryData,
)


class ResponseBuilder:
    """Builds structured API responses from processed DataFrames.

    Stateless service — all methods receive data as parameters.
    """

    def build_full_response(
        self,
        df: pd.DataFrame,
        cache_hit: bool,
        data_age_seconds: float,
        errors: Optional[list] = None,
    ) -> ScreenerResponse:
        """Build complete screener response with metadata, summary, and assets.

        Args:
            df: Processed DataFrame with ranked screener data.
            cache_hit: Whether the data was served from cache.
            data_age_seconds: Seconds since data was last fetched.
            errors: List of per-symbol error messages.

        Returns:
            ScreenerResponse with metadata, summary, and full assets array.
        """
        metadata = self._build_metadata(df, cache_hit, data_age_seconds, errors)
        summary = self._build_summary(df)
        assets = self._build_assets_list(df)

        return ScreenerResponse(
            metadata=metadata,
            summary=summary,
            assets=assets,
        )

    def build_summary_only(
        self,
        df: pd.DataFrame,
        cache_hit: bool,
        data_age_seconds: float,
        errors: Optional[list] = None,
    ) -> ScreenerResponse:
        """Build response with metadata and summary, omitting assets array.

        Args:
            df: Processed DataFrame with ranked screener data.
            cache_hit: Whether the data was served from cache.
            data_age_seconds: Seconds since data was last fetched.
            errors: List of per-symbol error messages.

        Returns:
            ScreenerResponse with metadata and summary, assets=None.
        """
        metadata = self._build_metadata(df, cache_hit, data_age_seconds, errors)
        summary = self._build_summary(df)

        return ScreenerResponse(
            metadata=metadata,
            summary=summary,
            assets=None,
        )

    def build_asset_detail(
        self,
        df: pd.DataFrame,
        symbol: str,
        cache_hit: bool,
        data_age_seconds: float,
    ) -> AssetDetailResponse:
        """Build single asset detail response.

        Args:
            df: Processed DataFrame with ranked screener data.
            symbol: The symbol to extract detail for.
            cache_hit: Whether the data was served from cache.
            data_age_seconds: Seconds since data was last fetched.

        Returns:
            AssetDetailResponse with metadata and single asset detail.

        Raises:
            ValueError: If symbol is not found in the DataFrame.
        """
        row = df[df["symbol"] == symbol]
        if row.empty:
            raise ValueError(f"Symbol {symbol} not found in data")

        metadata = self._build_metadata(df, cache_hit, data_age_seconds, errors=None)
        asset = self._build_asset(row.iloc[0])

        return AssetDetailResponse(
            metadata=metadata,
            asset=asset,
        )

    def _build_metadata(
        self,
        df: pd.DataFrame,
        cache_hit: bool,
        data_age_seconds: float,
        errors: Optional[list] = None,
    ) -> ResponseMetadata:
        """Build response metadata from DataFrame and cache info.

        Args:
            df: Processed DataFrame.
            cache_hit: Whether data was served from cache.
            data_age_seconds: Seconds since data was fetched.
            errors: List of per-symbol errors.

        Returns:
            ResponseMetadata with timestamp, counts, and staleness info.
        """
        errors_list = errors or []
        stale_warning = True if data_age_seconds > 300 else None

        return ResponseMetadata(
            timestamp=datetime.now(timezone.utc),
            data_age_seconds=round(data_age_seconds, 2),
            cache_hit=cache_hit,
            stale_data_warning=stale_warning,
            symbols_count=len(df),
            errors_count=len(errors_list),
        )

    def _build_summary(self, df: pd.DataFrame) -> SummaryData:
        """Build summary data with top 3 assets and market overview.

        Args:
            df: Processed DataFrame sorted by rank.

        Returns:
            SummaryData with top_3_assets and market_overview.
        """
        top_3 = self._build_top_3_assets(df)
        market_overview = self._build_market_overview(df)

        return SummaryData(
            top_3_assets=top_3,
            market_overview=market_overview,
        )

    def _build_top_3_assets(self, df: pd.DataFrame) -> list[AssetSummary]:
        """Extract top 3 assets from ranked DataFrame.

        Takes the first 3 rows (assumed sorted by rank) and builds
        AssetSummary objects.

        Args:
            df: DataFrame sorted by rank.

        Returns:
            List of up to 3 AssetSummary objects.
        """
        top_rows = df.head(3)
        summaries = []

        for _, row in top_rows.iterrows():
            summary = AssetSummary(
                symbol=row.get("symbol", ""),
                rank=self._sanitize_int(row.get("rank")),
                composite_score=self._sanitize_value(row.get("composite_score"), decimals=4),
                signal=row.get("signal") if pd.notna(row.get("signal")) else None,
            )
            summaries.append(summary)

        return summaries

    def _build_market_overview(self, df: pd.DataFrame) -> MarketOverview:
        """Build market overview aggregates from DataFrame.

        Computes averages, totals, and signal counts across all assets.

        Args:
            df: Full processed DataFrame.

        Returns:
            MarketOverview with aggregated statistics.
        """
        avg_change = None
        avg_funding = None
        total_vol = None

        if "change_24h" in df.columns:
            valid_changes = df["change_24h"].dropna()
            if len(valid_changes) > 0:
                avg_change = self._sanitize_value(valid_changes.mean(), decimals=4)

        if "funding_rate" in df.columns:
            valid_funding = df["funding_rate"].dropna()
            if len(valid_funding) > 0:
                avg_funding = self._sanitize_value(valid_funding.mean(), decimals=4)

        if "volume_24h" in df.columns:
            valid_volume = df["volume_24h"].dropna()
            if len(valid_volume) > 0:
                total_vol = self._sanitize_value(valid_volume.sum(), decimals=2)

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        if "signal" in df.columns:
            signal_counts = df["signal"].value_counts()
            bullish_count = int(signal_counts.get("BULLISH", 0))
            bearish_count = int(signal_counts.get("BEARISH", 0))
            neutral_count = int(signal_counts.get("NEUTRAL", 0))

        return MarketOverview(
            avg_change_24h=avg_change,
            avg_funding_rate=avg_funding,
            total_volume=total_vol,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            neutral_count=neutral_count,
        )

    def _build_assets_list(self, df: pd.DataFrame) -> list[AssetDetail]:
        """Build full assets list from DataFrame.

        Args:
            df: Processed DataFrame with all asset rows.

        Returns:
            List of AssetDetail objects for all rows.
        """
        assets = []
        for _, row in df.iterrows():
            assets.append(self._build_asset(row))
        return assets

    def _build_asset(self, row: pd.Series) -> AssetDetail:
        """Build a single AssetDetail from a DataFrame row.

        Args:
            row: A single row from the processed DataFrame.

        Returns:
            AssetDetail with all metric fields populated or None.
        """
        return AssetDetail(
            symbol=row.get("symbol", ""),
            rank=self._sanitize_int(row.get("rank")),
            composite_score=self._sanitize_value(row.get("composite_score"), decimals=4),
            signal=row.get("signal") if pd.notna(row.get("signal")) else None,
            price=self._sanitize_value(row.get("price"), decimals=2),
            change_24h=self._sanitize_value(row.get("change_24h"), decimals=4),
            volume_24h=self._sanitize_value(row.get("volume_24h"), decimals=2),
            funding_rate=self._sanitize_value(row.get("funding_rate"), decimals=4),
            open_interest=self._sanitize_value(row.get("open_interest"), decimals=2),
            long_short_ratio=self._sanitize_value(row.get("long_short_ratio"), decimals=4),
            rsi=self._sanitize_value(row.get("rsi"), decimals=2),
            macd_signal=row.get("macd_signal") if pd.notna(row.get("macd_signal")) else None,
            volatility=self._sanitize_value(row.get("volatility"), decimals=4),
            ic_weight=self._sanitize_value(row.get("ic_weight"), decimals=4),
        )

    def _sanitize_value(self, value, decimals: int = 2) -> Optional[float]:
        """Convert NaN/None to null, format numeric precision.

        Args:
            value: The value to sanitize (may be float, NaN, None, or other).
            decimals: Number of decimal places to round to (2-4).

        Returns:
            Rounded float or None if value is NaN/None/non-numeric.
        """
        if value is None:
            return None
        try:
            float_val = float(value)
            if math.isnan(float_val) or math.isinf(float_val):
                return None
            return round(float_val, decimals)
        except (TypeError, ValueError):
            return None

    def _sanitize_int(self, value) -> Optional[int]:
        """Convert value to int, returning None for NaN/None.

        Args:
            value: The value to convert.

        Returns:
            Integer value or None.
        """
        if value is None:
            return None
        try:
            float_val = float(value)
            if math.isnan(float_val) or math.isinf(float_val):
                return None
            return int(float_val)
        except (TypeError, ValueError):
            return None
