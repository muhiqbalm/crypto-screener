"""/api/v1/lab/baskets: basket paper strategies (one default strategy on a fixed, pre-registered
coin list, one paper account). Admin-only, read-only.

SQL against lab.db only (src/lab/basket/report.py). Baskets are created by the coordinator's
seed script (ops/lab_seed_baskets.py) from the pre-registration, never from the web: a basket
cannot be edited after it starts. Never places, closes or sizes an order, never calls an exchange.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from src.lab.basket import report

from .lab_auth import lab_admin
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/baskets", tags=["lab-baskets"])
Admin = Annotated[dict, Depends(lab_admin)]
Conn = Annotated[Any, Depends(_conn)]


@router.get("")
def baskets(_: Admin, conn: Conn) -> dict:
    """Every basket: equity, return, drawdown, x/30 closed trades across coins, the checkpoint
    gate, the pre-registered outcome so far, per-coin breakdown and the paper-vs-engine check."""
    return report.build(conn)


@router.get("/{basket_id}")
def basket_detail(basket_id: int, _: Admin, conn: Conn) -> dict:
    """One basket with its equity curve, recent trades, skip log, missed engine entries and rules."""
    d = report.detail(conn, basket_id)
    if d is None:
        raise HTTPException(404, "basket not found")
    return d
