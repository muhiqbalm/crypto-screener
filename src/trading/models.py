"""Pydantic models for TradingView webhook payload and response types."""

import re
from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator


# CCXT unified symbol format: BASE/QUOTE:SETTLE (e.g., BTC/USDT:USDT)
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$")


class WebhookPayload(BaseModel):
    """
    Pydantic model for TradingView webhook alert payload.

    Validates all fields per Requirements 1.1–1.10 and 11.1, 11.2, 11.4.
    """

    action: Literal["open", "close"]
    symbol: str  # CCXT unified format: BASE/QUOTE:SETTLE
    side: Literal["long", "short"]
    size_type: Literal["percent", "fixed"]
    size_value: float
    leverage: Optional[int] = None
    exchange: Literal["binance", "okx"]
    passphrase: str

    @field_validator("symbol")
    @classmethod
    def validate_symbol_format(cls, v: str) -> str:
        """Validate CCXT unified symbol format (e.g., BTC/USDT:USDT).

        Requirement 1.6: symbol must match ^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$
        """
        if not _SYMBOL_PATTERN.match(v):
            raise ValueError(
                "Symbol must be in CCXT unified format (e.g., BTC/USDT:USDT). "
                "Expected pattern: BASE/QUOTE:SETTLE using uppercase alphanumeric characters."
            )
        return v

    @field_validator("size_value")
    @classmethod
    def validate_size_value_positive(cls, v: float) -> float:
        """Validate size_value is greater than zero.

        Requirement 1.7: size_value must be > 0
        """
        if v <= 0:
            raise ValueError("size_value must be greater than zero")
        return v

    @field_validator("leverage")
    @classmethod
    def validate_leverage_range(cls, v: Optional[int]) -> Optional[int]:
        """Validate leverage is between 1 and 125 inclusive, or None.

        Requirement 1.10: leverage must be 1–125 or omitted
        """
        if v is not None and (v < 1 or v > 125):
            raise ValueError("leverage must be between 1 and 125 inclusive")
        return v

    @model_validator(mode="after")
    def validate_size_value_bounds(self) -> "WebhookPayload":
        """Cross-field validation for size_value upper bounds based on size_type.

        Requirement 1.8: percent size_value must be ≤ 100
        Requirement 1.9: fixed size_value must be ≤ 10,000,000
        """
        if self.size_type == "percent" and self.size_value > 100:
            raise ValueError(
                "size_value must be ≤ 100 when size_type is 'percent'"
            )
        if self.size_type == "fixed" and self.size_value > 10_000_000:
            raise ValueError(
                "size_value must be ≤ 10,000,000 when size_type is 'fixed'"
            )
        return self


class BalanceInfo(BaseModel):
    """Balance snapshot included in webhook trade responses."""

    free: float
    currency: str
    min_order_amount: float
    min_order_notional: Optional[float] = None
    current_price: float
    order_quantity: Optional[float] = None
    order_notional: Optional[float] = None
    margin_required: Optional[float] = None


class TradeSuccessResponse(BaseModel):
    """Response model for a successfully executed trade."""

    status: Literal["success"] = "success"
    order_id: str
    symbol: str
    action: str
    side: str
    fill_price: float
    filled_quantity: float
    balance_info: Optional[BalanceInfo] = None


class TradeErrorResponse(BaseModel):
    """Response model for a failed or rejected trade."""

    status: Literal["error"] = "error"
    error: str
    detail: Optional[str] = None
    balance_info: Optional[BalanceInfo] = None
