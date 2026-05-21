"""Auth router for the Trading User Management API.

Provides authentication endpoints under the ``/trading/auth`` prefix:
- POST /register → 201 UserProfileResponse
- POST /login    → 200 TokenResponse
- POST /refresh  → 200 AccessTokenResponse
- POST /logout   → 200 {"message": "Logged out"}  [requires active_user_guard]

The router is thin: it delegates all business logic to :class:`~..services.auth_service.AuthService`.

Requirements: 1.1, 2.1, 3.1, 4.1, 4.2, 4.3
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from ..active_user_guard import active_user_guard
from ..config import TradingSettings
from ..router import get_settings, get_supabase_client
from ..services.auth_service import AuthService
from ..user_models import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserProfileResponse,
)

router = APIRouter(prefix="/trading/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# Dependency: AuthService
# ---------------------------------------------------------------------------


def get_auth_service(
    settings: Annotated[TradingSettings, Depends(get_settings)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> AuthService:
    """FastAPI dependency that constructs and returns an :class:`AuthService`."""
    return AuthService(supabase=supabase, settings=settings)


# ---------------------------------------------------------------------------
# POST /trading/auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserProfileResponse,
    summary="Register a new user account",
    responses={
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
        503: {"description": "Service unavailable"},
    },
)
async def register(
    body: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    """Create a new user account.

    Hashes the password with bcrypt and inserts a new row into ``users``.
    Returns the created profile on success (201).

    Raises 409 if the email is already registered, 422 for validation errors.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
    """
    return await auth_service.register(
        email=body.email,
        name=body.name,
        password=body.password,
        telegram_chat_id=body.telegram_chat_id,
    )


# ---------------------------------------------------------------------------
# POST /trading/auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
    summary="Login and receive access + refresh tokens",
    responses={
        401: {"description": "Invalid credentials"},
        422: {"description": "Validation error"},
        503: {"description": "Service unavailable"},
    },
)
async def login(
    body: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate a registered user and issue JWT + refresh token.

    Verifies the bcrypt password hash, checks ``is_active``, and returns a
    full :class:`~..user_models.TokenResponse` on success (200).

    Returns 401 for wrong email, wrong password, or inactive account (no
    distinction is made between these cases to prevent enumeration).

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
    """
    return await auth_service.login(email=body.email, password=body.password)


# ---------------------------------------------------------------------------
# POST /trading/auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=AccessTokenResponse,
    summary="Exchange a refresh token for a new access token",
    responses={
        401: {"description": "Invalid or expired refresh token"},
        422: {"description": "Validation error"},
        503: {"description": "Service unavailable"},
    },
)
async def refresh(
    body: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    """Exchange a valid refresh token for a new JWT access token.

    Looks up the SHA-256 hash of the provided refresh token in ``user_tokens``,
    validates expiry and ``is_active``, and returns a new
    :class:`~..user_models.AccessTokenResponse` (200).

    Returns 401 when the token is missing, expired, or the user is inactive.

    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    return await auth_service.refresh(refresh_token=body.refresh_token)


# ---------------------------------------------------------------------------
# POST /trading/auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout and revoke all refresh tokens",
    responses={
        200: {"description": "Logged out"},
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def logout(
    payload: Annotated[dict, Depends(active_user_guard)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """Revoke all refresh tokens for the authenticated user.

    Requires a valid ``Authorization: Bearer <token>`` header (enforced by
    :func:`~..active_user_guard.active_user_guard`).  Deletes every row in
    ``user_tokens`` for the caller's ``user_id``, ending all active sessions.

    Returns ``{"message": "Logged out"}`` on success (200).

    Requirements: 4.1, 4.2, 4.3
    """
    user_id: str = payload["sub"]
    await auth_service.logout(user_id=user_id)
    return {"message": "Logged out"}
