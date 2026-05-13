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
            # Derive signal from multi_factor_score
            signal = self._derive_signal(row.get("multi_factor_score"))
            
            summary = AssetSummary(
                symbol=row.get("symbol", ""),
                rank=self._sanitize_int(row.get("rank")),
                composite_score=self._sanitize_value(row.get("multi_factor_score"), decimals=4),
                signal=signal,
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

        # Calculate total_volume according to requirement 2.3:
        # - If assets array is empty: return 0.0
        # - If all volume_24h values are null: return null
        # - If at least one non-null volume_24h: return sum rounded to 2 decimals
        if len(df) == 0:
            # Empty assets array
            total_vol = 0.0
        elif "volume_24h" in df.columns:
            valid_volume = df["volume_24h"].dropna()
            if len(valid_volume) > 0:
                total_vol = self._sanitize_value(valid_volume.sum(), decimals=2)
            # else: total_vol remains None (all values are null)

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        # Derive signal counts from multi_factor_score
        if "multi_factor_score" in df.columns:
            for _, row in df.iterrows():
                signal = self._derive_signal(row.get("multi_factor_score"))
                if signal == "BULLISH":
                    bullish_count += 1
                elif signal == "BEARISH":
                    bearish_count += 1
                elif signal == "NEUTRAL":
                    neutral_count += 1

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
        # Derive signal from multi_factor_score
        signal = self._derive_signal(row.get("multi_factor_score"))
        
        # Calculate RSI from reversal_signal (normalized z-score)
        # RSI approximation: map z-score to 0-100 range
        rsi = self._calculate_rsi_from_signal(row.get("reversal_signal"))
        
        # Derive MACD signal from momentum_signal
        macd_signal = self._derive_macd_signal(row.get("momentum_signal"))
        
        # Map atr_percent to volatility
        volatility = self._sanitize_value(row.get("atr_percent"), decimals=4)
        
        # Calculate weighted IC weight for this asset (average of signal weights)
        ic_weight = self._calculate_asset_ic_weight(row)
        
        return AssetDetail(
            symbol=row.get("symbol", ""),
            rank=self._sanitize_int(row.get("rank")),
            composite_score=self._sanitize_value(row.get("multi_factor_score"), decimals=4),
            signal=signal,
            price=self._sanitize_value(row.get("price"), decimals=2),
            change_24h=self._sanitize_value(row.get("change_24h"), decimals=4),
            volume_24h=self._sanitize_value(row.get("volume_24h"), decimals=2),
            funding_rate=self._sanitize_value(row.get("funding_rate"), decimals=4),
            open_interest=self._sanitize_value(row.get("open_interest"), decimals=2),
            long_short_ratio=self._sanitize_value(row.get("long_short_ratio"), decimals=4),
            rsi=rsi,
            macd_signal=macd_signal,
            volatility=volatility,
            ic_weight=ic_weight,
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

    def _derive_signal(self, multi_factor_score) -> Optional[str]:
        """Derive trading signal from multi-factor score.

        Args:
            multi_factor_score: The composite score value.

        Returns:
            "BULLISH", "BEARISH", or "NEUTRAL" based on score thresholds, or None if score is invalid.
        """
        if multi_factor_score is None:
            return None
        
        try:
            score = float(multi_factor_score)
            if math.isnan(score) or math.isinf(score):
                return None
            
            # Thresholds based on normalized z-scores
            # Score > 0.5: Strong bullish
            # Score < -0.5: Strong bearish
            # Otherwise: Neutral
            if score > 0.5:
                return "BULLISH"
            elif score < -0.5:
                return "BEARISH"
            else:
                return "NEUTRAL"
        except (TypeError, ValueError):
            return None

    def _calculate_rsi_from_signal(self, reversal_signal) -> Optional[float]:
        """Calculate RSI approximation from reversal signal (normalized z-score).

        Maps z-score to 0-100 RSI range:
        - z-score of -2 → RSI ~30 (oversold)
        - z-score of 0 → RSI ~50 (neutral)
        - z-score of +2 → RSI ~70 (overbought)

        Args:
            reversal_signal: Normalized reversal signal (z-score).

        Returns:
            RSI value between 0-100, or None if signal is invalid.
        """
        if reversal_signal is None:
            return None
        
        try:
            signal = float(reversal_signal)
            if math.isnan(signal) or math.isinf(signal):
                return None
            
            # Map z-score to RSI: RSI = 50 + (signal * 10)
            # Clamp to 0-100 range
            rsi = 50 + (signal * 10)
            rsi = max(0, min(100, rsi))
            
            return round(rsi, 2)
        except (TypeError, ValueError):
            return None

    def _derive_macd_signal(self, momentum_signal) -> Optional[str]:
        """Derive MACD signal from momentum signal (normalized z-score).

        Args:
            momentum_signal: Normalized momentum signal (z-score).

        Returns:
            "BUY", "SELL", or "HOLD" based on momentum thresholds, or None if signal is invalid.
        """
        if momentum_signal is None:
            return None
        
        try:
            signal = float(momentum_signal)
            if math.isnan(signal) or math.isinf(signal):
                return None
            
            # Thresholds based on normalized z-scores
            if signal > 0.5:
                return "BUY"
            elif signal < -0.5:
                return "SELL"
            else:
                return "HOLD"
        except (TypeError, ValueError):
            return None

    def _calculate_asset_ic_weight(self, row: pd.Series) -> Optional[float]:
        """Calculate effective IC weight for an asset.

        The IC weight represents the confidence in the composite score.
        For now, we use a fixed average of the signal weights (0.3 + 0.7) / 2 = 0.5.

        In a production system, this would be calculated based on:
        - Historical accuracy of signals for this specific asset
        - Data quality/completeness for this asset
        - Market regime indicators

        Args:
            row: DataFrame row with asset data.

        Returns:
            IC weight value between 0-1, or None if cannot be calculated.
        """
        # Fixed average IC weight for MVP
        # In production, this would be asset-specific
        return 0.5
