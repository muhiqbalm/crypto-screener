"""Pydantic request/response models for the Trading User Management API.

All request bodies are validated against these models; malformed inputs
result in 422 responses that include the field name and rejection reason
(Requirements 20.1, 20.2).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Request body for POST /trading/auth/register."""

    email: EmailStr
    name: str = Field(min_length=1)
    password: str = Field(min_length=8)
    telegram_chat_id: str | None = None


class UserProfileResponse(BaseModel):
    """Response body returned by registration, profile GET/PATCH, and login flows."""

    id: str
    email: str
    name: str
    telegram_chat_id: str | None
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Request body for POST /trading/auth/login."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Full token response returned on successful login.

    Contains both an access token (JWT) and a one-time plaintext refresh token.
    """

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 1800  # seconds


class AccessTokenResponse(BaseModel):
    """Short token response returned on token refresh (no new refresh token)."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 1800  # seconds


class RefreshRequest(BaseModel):
    """Request body for POST /trading/auth/refresh."""

    refresh_token: str


# ---------------------------------------------------------------------------
# Profile update
# ---------------------------------------------------------------------------


class ProfileUpdateRequest(BaseModel):
    """Request body for PATCH /trading/users/me.

    At least one of the three updatable fields must be provided.
    Requirement 7.4: empty body is rejected with 422.
    """

    name: str | None = Field(default=None, min_length=1)
    telegram_chat_id: str | None = None
    password: str | None = Field(default=None, min_length=8)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ProfileUpdateRequest":
        """Require at least one updatable field to be non-None."""
        if self.name is None and self.telegram_chat_id is None and self.password is None:
            raise ValueError("At least one updatable field must be provided")
        return self


# ---------------------------------------------------------------------------
# Webhook config
# ---------------------------------------------------------------------------


class WebhookConfigCreateRequest(BaseModel):
    """Request body for POST /trading/users/me/webhook-config."""

    passphrase: str = Field(min_length=8)


class WebhookConfigUpdateRequest(BaseModel):
    """Request body for PATCH /trading/users/me/webhook-config."""

    passphrase: str = Field(min_length=8)


class WebhookConfigResponse(BaseModel):
    """Response body for all webhook-config endpoints.

    The passphrase is returned in full (stored as plaintext in DB).
    """

    id: str
    passphrase: str
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Exchange credentials
# ---------------------------------------------------------------------------


class CredentialUpsertRequest(BaseModel):
    """Request body for POST /trading/users/me/credentials.

    Only "binance" and "okx" are supported exchanges (Requirement 13.2).
    """

    exchange: Literal["binance", "okx"]
    api_key: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    api_passphrase: str | None = None


class CredentialSummaryResponse(BaseModel):
    """Response body for credential list and upsert endpoints.

    API keys, secrets, and passphrases are never included in responses
    (Requirements 12.2, 13.4).
    """

    exchange: str
    is_configured: bool = True
    created_at: datetime


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


class ExchangeBalanceResponse(BaseModel):
    """Balance for one currency on one exchange."""

    exchange: str
    currency: str
    free: float
    used: float
    total: float


class BalanceResponse(BaseModel):
    """Response for GET /trading/users/me/balance."""

    balances: list[ExchangeBalanceResponse]


# ---------------------------------------------------------------------------
# Open positions
# ---------------------------------------------------------------------------


class OpenPositionResponse(BaseModel):
    """One open (active) position record returned by GET /trading/users/me/positions.

    Data is sourced directly from the exchange (source of truth).
    Real-time fields (mark_price, unrealized_pnl, unrealized_pnl_pct,
    liquidation_price) are None when the exchange does not provide them.
    """

    symbol: str
    side: str
    entry_price: float
    quantity: float
    exchange: str
    # Real-time data from exchange
    mark_price: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    liquidation_price: float | None = None
    leverage: float | None = None


# ---------------------------------------------------------------------------
# Closed positions / history
# ---------------------------------------------------------------------------


class ClosedPositionResponse(BaseModel):
    """One closed position record returned by GET /trading/users/me/positions/history.

    Records are ordered by closed_at descending (Requirement 16.3).
    """

    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    opened_at: datetime
    closed_at: datetime
    exchange: str


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------


class TradeLogResponse(BaseModel):
    """One trade log entry returned by GET /trading/users/me/trades.

    Records are ordered by created_at descending (Requirement 17.3).
    Optional fields are None when the trade did not reach order submission
    (e.g., it failed during validation or position sizing).
    """

    id: str
    symbol: str
    action: str
    side: str
    exchange: str
    size_value: float
    status: str
    order_id: str | None
    fill_price: float | None
    filled_quantity: float | None
    error_details: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


class APIErrorResponse(BaseModel):
    """Consistent error response shape used by all error handlers.

    The ``detail`` field carries optional field-level information; for 422
    responses FastAPI's native validation error list is serialised here.
    """

    status: Literal["error"] = "error"
    error: str
    detail: str | None = None
