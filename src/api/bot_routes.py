"""/api/v1/lab/bot/status — "Status bot" summary for the /bot page. Admin-only, read-only.

Webhook on/off per account, exchanges with a stored key, and the last alert the bot
processed (src/lab/botstatus.py). Reads bmtm_trading.db through a read-only connection;
never returns passphrases, keys, user ids, order ids or error text, never calls an
exchange or the webhook. Lives under /api/v1/lab/ so the existing Lab auth (Bearer JWT +
LAB_ADMIN_EMAILS) applies unchanged.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.lab import botstatus
from src.lab.settings import get_lab_settings

from .lab_auth import lab_admin

router = APIRouter(prefix="/api/v1/lab/bot", tags=["lab-bot"])
Admin = Annotated[dict, Depends(lab_admin)]


@router.get("/status")
def bot_status(_: Admin) -> dict:
    """Accounts with a webhook config: active or not, exchanges with a key, last processed
    alert and the 7-day alert / failure counts."""
    return botstatus.build(get_lab_settings().trading_db_path)
