"""Active user guard FastAPI dependency.

Provides :func:`active_user_guard`, a FastAPI dependency that:

1. Extracts the ``Bearer`` token from the ``Authorization`` header
   (returns 401 if the header is absent or malformed).
2. Verifies the JWT signature and ``exp`` claim via
   :func:`~.jwt_utils.decode_access_token` (returns 401 on any
   ``JWTError``).
3. Performs exactly one database query to confirm ``users.is_active = true``
   for the ``sub`` claim (returns 401 if the user is inactive or not found).
4. Returns the decoded JWT payload ``dict`` on success.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .jwt_utils import JWTError, decode_access_token
from .router import get_settings, get_supabase_client
from .config import TradingSettings

logger = logging.getLogger(__name__)

# HTTPBearer automatically returns 403 when the Authorization header is
# missing unless auto_error is set to False.  We override to 401 by
# catching the absence ourselves via auto_error=False.
_bearer_scheme = HTTPBearer(auto_error=False)


async def active_user_guard(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer_scheme),
    ],
    settings: Annotated[TradingSettings, Depends(get_settings)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> dict:
    """FastAPI dependency applied to all JWT-protected endpoints.

    Raises :class:`fastapi.HTTPException` with status 401 for any
    authentication or authorisation failure.  The error detail is kept
    deliberately vague to prevent information leakage (Req 5.2–5.6).

    Args:
        credentials: The parsed ``Authorization: Bearer <token>`` header,
            or ``None`` when the header is absent.
        settings: Injected :class:`~.config.TradingSettings` (provides
            ``jwt_secret``).
        supabase: Injected Supabase client used for the ``is_active`` check.

    Returns:
        The decoded JWT payload as a plain ``dict`` (contains at minimum
        ``sub``, ``exp``, and ``iat`` claims).

    Raises:
        HTTPException: 401 for missing header, invalid/expired JWT, missing
            ``sub`` claim, user not found, or ``is_active = false``.
    """
    # Requirement 5.2 — missing Authorization header
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = credentials.credentials

    # Requirements 5.3, 5.4 — invalid signature or expired token
    try:
        payload = decode_access_token(token, settings.jwt_secret)
    except JWTError:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Guard against tokens with no subject claim
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Requirements 5.5, 5.6 — single DB query to verify is_active
    try:
        response = (
            supabase.table("users")
            .select("is_active")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.error(
            "Database error during active_user_guard for user=%s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="Service unavailable")

    if not response.data or not response.data.get("is_active"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return payload
