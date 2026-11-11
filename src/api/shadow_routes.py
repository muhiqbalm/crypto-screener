"""/api/v1/lab/shadow — "Kualitas eksekusi" (shadow execution). Admin-only, read-only.

SQL against lab.db only. Collection and evaluation run in the lab worker
(src/lab/shadow, job ``shadow_cycle``); this endpoint never calls an exchange and
never touches bmtm_trading.db.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.lab.shadow import report

from .lab_auth import lab_admin
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/shadow", tags=["lab-shadow"])
Admin = Annotated[dict, Depends(lab_admin)]
Conn = Annotated[Any, Depends(_conn)]


@router.get("")
def shadow_report(_: Admin, conn: Conn) -> dict:
    """Per live webhook signal: actual execution quality + shadow limit outcomes, and the
    aggregate fill rate / saving per (k, time-to-live)."""
    return report.build(conn)
