"""/api/v1/lab/arena — "Arena Paper". Admin-only, read-only.

SQL against lab.db only (presets, watches, paper accounts/positions, journal and
the arena_equity_snapshots table written by the worker's ``arena_snapshot`` job).
Never places, closes or sizes a paper or live order, never calls an exchange.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.lab.arena import report

from .lab_auth import lab_admin
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/arena", tags=["lab-arena"])
Admin = Annotated[dict, Depends(lab_admin)]
Conn = Annotated[Any, Depends(_conn)]


@router.get("")
def arena_leaderboard(_: Admin, conn: Conn) -> dict:
    """Every paper preset: equity, return, max DD, Sharpe (when enough data), trades / progress to the
    30-trade review, win rate, open position, last action, and the drift check vs its backtest."""
    return report.build(conn)


@router.get("/curves")
def arena_curves(_: Admin, conn: Conn) -> dict:
    """Equity curve per paper preset (start, hourly snapshots, every close, now). Raw USDT equity;
    the page normalises."""
    return report.curves(conn)
