"""API Key authentication dependency for securing endpoints.

Provides a configurable X-API-Key header-based authentication mechanism.
When enabled via SCREENER_REQUIRE_API_KEY=true, all protected endpoints
require a valid API key in the X-API-Key header.

Usage in routers:
    from src.api.auth import verify_api_key

    router = APIRouter(dependencies=[Depends(verify_api_key)])
"""

import logging
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

# Define the security scheme — appears in Swagger UI as "X-API-Key" header
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,  # We handle missing key ourselves for conditional auth
    description="API key for authenticating requests. "
    "Required when SCREENER_REQUIRE_API_KEY is enabled.",
)


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> None:
    """Validate the X-API-Key header against the configured secret.

    This dependency is a no-op when ``require_api_key`` is ``False``
    in Settings, allowing the same router to work in both public
    (testing) and protected (production) modes without code changes.

    Args:
        request: Current FastAPI request (used to read app.state.settings).
        api_key: Value of the X-API-Key header, or None if absent.

    Raises:
        HTTPException 401: When auth is enabled and the key is missing.
        HTTPException 403: When auth is enabled and the key is invalid.
    """
    settings = request.app.state.settings

    # If authentication is disabled, allow all requests through
    if not settings.require_api_key:
        return

    # Auth is enabled — key must be present
    if api_key is None:
        logger.warning(
            "Request rejected: missing X-API-Key header",
            extra={"endpoint": request.url.path},
        )
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide a valid X-API-Key header.",
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, settings.api_key):
        logger.warning(
            "Request rejected: invalid API key",
            extra={"endpoint": request.url.path},
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid API key.",
        )

    logger.debug("API key verified successfully")
