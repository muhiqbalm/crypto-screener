"""Users router for the Trading User Management API.

Provides user profile, webhook config, credential, and monitoring endpoints
under the ``/trading/users/me`` prefix.  All routes are protected by
:func:`~..active_user_guard.active_user_guard`.

Endpoints:
- GET  /trading/users/me                        → 200 UserProfileResponse
- PATCH /trading/users/me                       → 200 UserProfileResponse
- GET  /trading/users/me/webhook-config         → 200 WebhookConfigResponse
- POST /trading/users/me/webhook-config         → 201 WebhookConfigResponse
- PATCH /trading/users/me/webhook-config        → 200 WebhookConfigResponse
- DELETE /trading/users/me/webhook-config       → 200 WebhookConfigResponse
- GET  /trading/users/me/credentials            → 200 list[CredentialSummaryResponse]
- POST /trading/users/me/credentials            → 200 CredentialSummaryResponse
- DELETE /trading/users/me/credentials/{exchange} → 200 {"message": "Credentials removed"}
- GET  /trading/users/me/positions              → 200 list[OpenPositionResponse]
- GET  /trading/users/me/positions/history      → 200 list[ClosedPositionResponse]
- GET  /trading/users/me/trades                 → 200 list[TradeLogResponse]

Requirements: 6.1, 6.2, 7.1, 7.3, 7.4, 8.1, 8.2, 9.1, 10.1, 11.1,
              12.1, 13.1, 14.1, 15.1, 16.1, 17.1
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from ..active_user_guard import active_user_guard
from ..credentials import CredentialStore
from ..router import get_settings, get_supabase_client
from ..services.credential_service import CredentialService
from ..services.monitoring_service import MonitoringService
from ..services.profile_service import ProfileService
from ..services.webhook_config_service import WebhookConfigService
from ..user_models import (
    BalanceResponse,
    ClosedPositionResponse,
    CredentialSummaryResponse,
    CredentialUpsertRequest,
    ExchangeBalanceResponse,
    OpenPositionResponse,
    ProfileUpdateRequest,
    TradeLogResponse,
    UserProfileResponse,
    WebhookConfigCreateRequest,
    WebhookConfigResponse,
    WebhookConfigUpdateRequest,
)

router = APIRouter(prefix="/trading/users/me", tags=["Users"])


# ---------------------------------------------------------------------------
# Dependency: ProfileService
# ---------------------------------------------------------------------------


def get_profile_service(
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> ProfileService:
    """FastAPI dependency that constructs and returns a :class:`ProfileService`."""
    return ProfileService(supabase=supabase)


# ---------------------------------------------------------------------------
# Dependency: WebhookConfigService
# ---------------------------------------------------------------------------


def get_webhook_config_service(
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> WebhookConfigService:
    """FastAPI dependency that constructs and returns a :class:`WebhookConfigService`."""
    return WebhookConfigService(supabase=supabase)


# ---------------------------------------------------------------------------
# Dependency: CredentialService
# ---------------------------------------------------------------------------


def get_credential_store(
    settings: Annotated[Any, Depends(get_settings)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> CredentialStore:
    """FastAPI dependency that constructs a :class:`CredentialStore`."""
    return CredentialStore(encryption_key=settings.encryption_key, supabase=supabase)


def get_credential_service(
    supabase: Annotated[Any, Depends(get_supabase_client)],
    credential_store: Annotated[CredentialStore, Depends(get_credential_store)],
) -> CredentialService:
    """FastAPI dependency that constructs and returns a :class:`CredentialService`."""
    return CredentialService(supabase=supabase, credential_store=credential_store)


# ---------------------------------------------------------------------------
# Dependency: MonitoringService
# ---------------------------------------------------------------------------


def get_monitoring_service(
    settings: Annotated[Any, Depends(get_settings)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
    credential_store: Annotated[CredentialStore, Depends(get_credential_store)],
) -> MonitoringService:
    """FastAPI dependency that constructs and returns a :class:`MonitoringService`."""
    from ..connector import TradingConnector
    return MonitoringService(
        supabase=supabase,
        credential_store=credential_store,
        trading_connector=TradingConnector(testnet_enabled=settings.testnet_enabled),
    )


# ===========================================================================
# Profile routes (tasks 6.2)
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /trading/users/me
# ---------------------------------------------------------------------------


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=UserProfileResponse,
    summary="Retrieve the authenticated user's profile",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
        503: {"description": "Service unavailable"},
    },
)
async def get_my_profile(
    payload: Annotated[dict, Depends(active_user_guard)],
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
) -> UserProfileResponse:
    """Return the authenticated user's profile.

    Requires a valid ``Authorization: Bearer <token>`` header (enforced by
    :func:`~..active_user_guard.active_user_guard`).

    The response includes ``id``, ``email``, ``name``, ``telegram_chat_id``,
    ``is_active``, and ``created_at``.  The ``password_hash`` field is never
    included in the response (Requirement 6.2).

    Requirements: 6.1, 6.2
    """
    user_id: str = payload["sub"]
    return await profile_service.get_profile(user_id=user_id)


# ---------------------------------------------------------------------------
# PATCH /trading/users/me
# ---------------------------------------------------------------------------


@router.patch(
    "",
    status_code=status.HTTP_200_OK,
    response_model=UserProfileResponse,
    summary="Update the authenticated user's profile",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
        422: {"description": "Validation error — no updatable field provided or invalid value"},
        503: {"description": "Service unavailable"},
    },
)
async def update_my_profile(
    body: ProfileUpdateRequest,
    payload: Annotated[dict, Depends(active_user_guard)],
    profile_service: Annotated[ProfileService, Depends(get_profile_service)],
) -> UserProfileResponse:
    """Partially update the authenticated user's profile.

    Requires a valid ``Authorization: Bearer <token>`` header (enforced by
    :func:`~..active_user_guard.active_user_guard`).

    Only the fields supplied in the request body are updated; fields that are
    absent remain unchanged (Requirement 7.1).  If ``password`` is supplied it
    is hashed with bcrypt before storage (Requirement 7.2).

    A request body with no recognised updatable fields is rejected with 422
    (Requirement 7.4).  An empty ``name`` field is also rejected with 422
    (Requirement 7.3).

    Requirements: 7.1, 7.3, 7.4
    """
    user_id: str = payload["sub"]
    return await profile_service.update_profile(user_id=user_id, update=body)


# ===========================================================================
# Webhook config routes (task 8.2)
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /trading/users/me/webhook-config
# ---------------------------------------------------------------------------


@router.get(
    "/webhook-config",
    status_code=status.HTTP_200_OK,
    response_model=WebhookConfigResponse,
    summary="Retrieve the authenticated user's active webhook configuration",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "No active webhook configuration found"},
        503: {"description": "Service unavailable"},
    },
)
async def get_webhook_config(
    payload: Annotated[dict, Depends(active_user_guard)],
    webhook_config_service: Annotated[WebhookConfigService, Depends(get_webhook_config_service)],
) -> WebhookConfigResponse:
    """Return the authenticated user's active webhook configuration.

    Returns the ``id``, ``passphrase`` (plaintext), ``is_active``, and
    ``created_at`` of the user's active webhook config.  Returns 404 when no
    active config exists (Requirement 8.2).

    Requirements: 8.1, 8.2
    """
    user_id: str = payload["sub"]
    return await webhook_config_service.get_active(user_id=user_id)


# ---------------------------------------------------------------------------
# POST /trading/users/me/webhook-config
# ---------------------------------------------------------------------------


@router.post(
    "/webhook-config",
    status_code=status.HTTP_201_CREATED,
    response_model=WebhookConfigResponse,
    summary="Create a new webhook configuration for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        409: {"description": "Active config already exists or passphrase already in use"},
        422: {"description": "Validation error — passphrase too short"},
        503: {"description": "Service unavailable"},
    },
)
async def create_webhook_config(
    body: WebhookConfigCreateRequest,
    payload: Annotated[dict, Depends(active_user_guard)],
    webhook_config_service: Annotated[WebhookConfigService, Depends(get_webhook_config_service)],
) -> WebhookConfigResponse:
    """Create a new active webhook configuration for the authenticated user.

    The request body must contain a ``passphrase`` of at least 8 characters.
    Returns 409 if the user already has an active config or if the passphrase
    is already in use by another user (Requirements 9.3, 9.4).

    Requirements: 9.1, 9.2, 9.3, 9.4
    """
    user_id: str = payload["sub"]
    return await webhook_config_service.create(user_id=user_id, passphrase=body.passphrase)


# ---------------------------------------------------------------------------
# PATCH /trading/users/me/webhook-config
# ---------------------------------------------------------------------------


@router.patch(
    "/webhook-config",
    status_code=status.HTTP_200_OK,
    response_model=WebhookConfigResponse,
    summary="Update the passphrase on the authenticated user's webhook configuration",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "No active webhook configuration found"},
        409: {"description": "Passphrase already in use"},
        422: {"description": "Validation error — passphrase too short"},
        503: {"description": "Service unavailable"},
    },
)
async def update_webhook_config(
    body: WebhookConfigUpdateRequest,
    payload: Annotated[dict, Depends(active_user_guard)],
    webhook_config_service: Annotated[WebhookConfigService, Depends(get_webhook_config_service)],
) -> WebhookConfigResponse:
    """Update the passphrase on the authenticated user's active webhook configuration.

    Returns 404 if no active config exists (Requirement 10.3).  Returns 409
    if the new passphrase is already in use by any user (Requirement 10.2).

    Requirements: 10.1, 10.2, 10.3
    """
    user_id: str = payload["sub"]
    return await webhook_config_service.update(user_id=user_id, passphrase=body.passphrase)


# ---------------------------------------------------------------------------
# DELETE /trading/users/me/webhook-config
# ---------------------------------------------------------------------------


@router.delete(
    "/webhook-config",
    status_code=status.HTTP_200_OK,
    response_model=WebhookConfigResponse,
    summary="Deactivate the authenticated user's webhook configuration",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "No active webhook configuration found"},
        503: {"description": "Service unavailable"},
    },
)
async def delete_webhook_config(
    payload: Annotated[dict, Depends(active_user_guard)],
    webhook_config_service: Annotated[WebhookConfigService, Depends(get_webhook_config_service)],
) -> WebhookConfigResponse:
    """Deactivate the authenticated user's active webhook configuration.

    Sets ``is_active = false`` on the active record and returns the updated
    record.  Returns 404 if no active config exists (Requirement 11.2).

    Requirements: 11.1, 11.2
    """
    user_id: str = payload["sub"]
    return await webhook_config_service.deactivate(user_id=user_id)


# ===========================================================================
# Credential routes (task 9.2)
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /trading/users/me/credentials
# ---------------------------------------------------------------------------


@router.get(
    "/credentials",
    status_code=status.HTTP_200_OK,
    response_model=list[CredentialSummaryResponse],
    summary="List all configured exchange credentials for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def list_credentials(
    payload: Annotated[dict, Depends(active_user_guard)],
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
) -> list[CredentialSummaryResponse]:
    """Return a list of exchange credential summaries for the authenticated user.

    Each record contains ``exchange``, ``is_configured`` (always ``true``),
    and ``created_at``.  API keys and secrets are never included
    (Requirements 12.2, 13.4).  Returns an empty list when no credentials
    are configured (Requirement 12.3).

    Requirements: 12.1, 12.2, 12.3
    """
    user_id: str = payload["sub"]
    return await credential_service.list_credentials(user_id=user_id)


# ---------------------------------------------------------------------------
# POST /trading/users/me/credentials
# ---------------------------------------------------------------------------


@router.post(
    "/credentials",
    status_code=status.HTTP_200_OK,
    response_model=CredentialSummaryResponse,
    summary="Add or update exchange credentials for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        422: {"description": "Validation error — unsupported exchange or missing field"},
        503: {"description": "Service unavailable"},
    },
)
async def upsert_credentials(
    body: CredentialUpsertRequest,
    payload: Annotated[dict, Depends(active_user_guard)],
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
) -> CredentialSummaryResponse:
    """Encrypt and store (or replace) exchange API credentials.

    The request body must contain ``exchange`` (``"binance"`` or ``"okx"``),
    ``api_key``, and ``secret``.  An optional ``api_passphrase`` may also be
    provided (required for OKX).  Credentials are encrypted using Fernet
    before storage (Requirement 13.1).  The response contains only
    ``exchange``, ``is_configured``, and ``created_at`` — no secrets
    (Requirement 13.4).

    Requirements: 13.1, 13.2, 13.3, 13.4
    """
    user_id: str = payload["sub"]
    return await credential_service.upsert_credentials(user_id=user_id, req=body)


# ---------------------------------------------------------------------------
# DELETE /trading/users/me/credentials/{exchange}
# ---------------------------------------------------------------------------


@router.delete(
    "/credentials/{exchange}",
    status_code=status.HTTP_200_OK,
    summary="Remove exchange credentials for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "No credentials found for the specified exchange"},
        422: {"description": "Validation error — unsupported exchange"},
        503: {"description": "Service unavailable"},
    },
)
async def delete_credentials(
    exchange: str,
    payload: Annotated[dict, Depends(active_user_guard)],
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
) -> dict:
    """Delete the API credentials for the specified exchange.

    Returns 422 if *exchange* is not ``"binance"`` or ``"okx"``
    (Requirement 14.2).  Returns 404 if no credentials exist for the pair
    (Requirement 14.3).

    Requirements: 14.1, 14.2, 14.3
    """
    user_id: str = payload["sub"]
    return await credential_service.delete_credentials(user_id=user_id, exchange=exchange)


# ===========================================================================
# Balance routes
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /trading/users/me/balance
# ---------------------------------------------------------------------------


@router.get(
    "/balance",
    status_code=status.HTTP_200_OK,
    response_model=BalanceResponse,
    summary="Get exchange balances for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def get_balance(
    payload: Annotated[dict, Depends(active_user_guard)],
    monitoring_service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> BalanceResponse:
    """Return balances across all configured exchanges for the authenticated user.

    Fetches live balance data directly from each exchange the user has
    credentials configured for. Only currencies with a non-zero total balance
    are returned.

    If one exchange fails (e.g. wrong credentials or network issue), that
    exchange is skipped and the remaining results are still returned.
    """
    user_id: str = payload["sub"]
    balances = await monitoring_service.get_balance(user_id=user_id)
    return BalanceResponse(balances=balances)


# ===========================================================================
# Monitoring routes (task 10.2)
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /trading/users/me/positions
# ---------------------------------------------------------------------------


@router.get(
    "/positions",
    status_code=status.HTTP_200_OK,
    response_model=list[OpenPositionResponse],
    summary="List open positions for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def get_open_positions(
    payload: Annotated[dict, Depends(active_user_guard)],
    monitoring_service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> list[OpenPositionResponse]:
    """Return the authenticated user's current open positions.

    Each record contains ``id``, ``symbol``, ``side``, ``entry_price``,
    ``quantity``, ``opened_at``, and ``exchange``.  Returns an empty list
    when the user has no open positions (Requirement 15.2).

    Requirements: 15.1, 15.2
    """
    user_id: str = payload["sub"]
    return await monitoring_service.get_open_positions(user_id=user_id)


# ---------------------------------------------------------------------------
# GET /trading/users/me/positions/history
# ---------------------------------------------------------------------------


@router.get(
    "/positions/history",
    status_code=status.HTTP_200_OK,
    response_model=list[ClosedPositionResponse],
    summary="List closed position history for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def get_position_history(
    payload: Annotated[dict, Depends(active_user_guard)],
    monitoring_service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> list[ClosedPositionResponse]:
    """Return the authenticated user's closed position history.

    Records are ordered by ``closed_at`` descending (Requirement 16.3).  Each
    record contains ``id``, ``symbol``, ``side``, ``entry_price``,
    ``exit_price``, ``quantity``, ``opened_at``, ``closed_at``, and
    ``exchange``.  Returns an empty list when the user has no closed positions
    (Requirement 16.2).

    Requirements: 16.1, 16.2, 16.3
    """
    user_id: str = payload["sub"]
    return await monitoring_service.get_position_history(user_id=user_id)


# ---------------------------------------------------------------------------
# GET /trading/users/me/trades
# ---------------------------------------------------------------------------


@router.get(
    "/trades",
    status_code=status.HTTP_200_OK,
    response_model=list[TradeLogResponse],
    summary="Retrieve the trade log for the authenticated user",
    responses={
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def get_trade_log(
    payload: Annotated[dict, Depends(active_user_guard)],
    monitoring_service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> list[TradeLogResponse]:
    """Return the authenticated user's complete trade log.

    Records are ordered by ``created_at`` descending (Requirement 17.3).
    Each record contains ``id``, ``symbol``, ``action``, ``side``,
    ``exchange``, ``size_value``, ``status``, ``order_id``, ``fill_price``,
    ``filled_quantity``, ``error_details``, and ``created_at``.  Returns an
    empty list when the user has no trade log entries (Requirement 17.2).

    Requirements: 17.1, 17.2, 17.3
    """
    user_id: str = payload["sub"]
    return await monitoring_service.get_trade_log(user_id=user_id)
