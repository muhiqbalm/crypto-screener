"""/api/v1/lab/live-check — "Cek bot live vs strategi". Admin-only, read-only.

SQL against lab.db only. Log reading, the trade_logs read (``mode=ro``) and the engine
run happen in the lab worker (src/lab/livecheck, job ``livecheck_cycle``); this endpoint
never touches bmtm_trading.db, the logs, an exchange or the webhook.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from src.lab.livecheck import report

from .lab_auth import lab_admin
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/live-check", tags=["lab-live-check"])
Admin = Annotated[dict, Depends(lab_admin)]
Conn = Annotated[Any, Depends(_conn)]


@router.get("")
def live_check(_: Admin, conn: Conn, bars: int = Query(270, ge=6, le=report.MAX_BARS)) -> dict:
    """Last ``bars`` 4H bars: expected 4H-ETH-Basic signals vs webhook deliveries, one row
    per event with status, causes and sanitised detail, plus summary counts."""
    return report.build(conn, bars=bars)
