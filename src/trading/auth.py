"""Passphrase-based authentication for the TradingView webhook trading module.

Looks up users by passphrase in the webhook_configs table and returns
the associated user_id and config record. Intentionally generic error
responses to avoid leaking user/passphrase existence information.
"""

import logging
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def authenticate_by_passphrase(
    passphrase: str,
    supabase: Any,
) -> dict:
    """Look up a user by matching their passphrase against the webhook_configs table.

    Queries the webhook_configs table for an active config matching the given
    passphrase, then retrieves the associated user record via a join.

    Args:
        passphrase: The passphrase string from the incoming webhook payload.
        supabase: An async (or sync) Supabase client instance.

    Returns:
        A dict with keys:
          - ``user_id``: The UUID string of the authenticated user.
          - ``config``: The full webhook_config row as a dict.

    Raises:
        HTTPException(401): If the passphrase does not match any active
            webhook_config record. The message is intentionally generic
            ("Unauthorized") to avoid leaking whether the passphrase or the
            user account exists (Requirement 2.2).
        HTTPException(503): If the database is unavailable or raises an
            unexpected error during lookup. The failure is logged at ERROR
            level before raising (Requirement 2.3).
    """
    try:
        response = (
            supabase.table("webhook_configs")
            .select("id, user_id, passphrase, is_active, created_at")
            .eq("passphrase", passphrase)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "Database connection failure during passphrase lookup: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail="Service unavailable",
        ) from exc

    rows = response.data if response.data else []

    if not rows:
        # Log at WARNING level but return no detail to the caller.
        logger.warning(
            "Passphrase authentication failed: no matching active webhook_config found."
        )
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    config = rows[0]
    user_id: str = config["user_id"]

    return {
        "user_id": user_id,
        "config": config,
    }
