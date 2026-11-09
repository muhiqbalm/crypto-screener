"""Strategy Lab admin gate.

Reuses the trading JWT dependency (``active_user_guard``) unchanged — imported,
not modified — and additionally requires the user's id or email to be listed in
LAB_ADMIN_EMAILS. Non-admins get 403.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from src.lab.settings import get_lab_settings
from src.trading.active_user_guard import active_user_guard
from src.trading.router import get_supabase_client

logger = logging.getLogger(__name__)


def _lookup_email(supabase: Any, user_id: str) -> str | None:
    try:
        resp = supabase.table("users").select("email").eq("id", user_id).single().execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("lab auth: email lookup failed for user=%s: %s", user_id, exc)
        return None
    data = getattr(resp, "data", None) or {}
    email = data.get("email") if isinstance(data, dict) else None
    return email.lower() if isinstance(email, str) else None


def is_lab_admin(payload: dict, supabase: Any) -> bool:
    admins = get_lab_settings().admin_set
    if not admins:
        return False
    user_id = str(payload.get("sub") or "").lower()
    if user_id and user_id in admins:
        return True
    email = payload.get("email")
    if isinstance(email, str) and email.lower() in admins:
        return True
    email = _lookup_email(supabase, payload.get("sub") or "")
    return bool(email and email in admins)


async def lab_user(
    payload: Annotated[dict, Depends(active_user_guard)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> dict:
    """Authenticated user (any) + is_admin flag; used by GET /lab/me."""
    return {"payload": payload, "is_admin": is_lab_admin(payload, supabase)}


async def lab_admin(user: Annotated[dict, Depends(lab_user)]) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Strategy Lab is restricted to admins")
    return user["payload"]
