"""/api/v1/lab/report (Laporan Mingguan) + /api/v1/lab/notifications (in-web). Admin-only.

The report is read-only: a frozen snapshot (written by the lab worker each Monday
00:30 UTC) when the week has one, otherwise built on request from lab.db, the
trade_logs table of bmtm_trading.db (separate read-only connection) and the deploy /
backup logs. Notifications are stored in lab.db by the Lab code (src/lab/notify.py);
read state is per admin (JWT ``sub``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.lab import notify as notif
from src.lab.settings import get_lab_settings
from src.lab.weekly import build, store

from .lab_auth import lab_admin
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/report", tags=["lab-report"])
notifications_router = APIRouter(prefix="/api/v1/lab/notifications", tags=["lab-notifications"])
Admin = Annotated[dict, Depends(lab_admin)]
Conn = Annotated[Any, Depends(_conn)]
WEEKS_BACK = 12


def _week_or_422(week: Optional[str], now: datetime) -> str:
    cur = store.current_week(now)
    if not week:
        return cur
    try:
        store.parse_week(week)
    except ValueError:
        raise HTTPException(status_code=422, detail="week harus berformat YYYY-Www, mis. 2026-W46")
    if week > cur:
        raise HTTPException(status_code=422, detail="minggu ini belum dimulai")
    return week


@router.get("/weeks")
def weeks(_: Admin, conn: Conn) -> dict:
    """Weeks for the selector: the current week, the last WEEKS_BACK weeks, and every snapshot."""
    now = datetime.now(timezone.utc)
    cur = store.current_week(now)
    snaps = {s["week"]: s for s in store.listing(conn)}
    ids = sorted({store.shift(cur, -i) for i in range(WEEKS_BACK)} | set(snaps), reverse=True)
    out = []
    for w in ids:
        a, b = store.bounds(w)
        s = snaps.get(w)
        out.append({"week": w, "start": store.iso(a), "end": store.iso(b), "current": w == cur,
                    "snapshot": bool(s), "generated_at": s["generated_at"] if s else None})
    return {"current": cur, "weeks": out}


@router.get("/weekly")
def weekly(_: Admin, conn: Conn, week: Optional[str] = None) -> dict:
    now = datetime.now(timezone.utc)
    w = _week_or_422(week, now)
    return build.get_or_build(conn, w, get_lab_settings().trading_db_path, now=now)


# ── notifications ─────────────────────────────────────────────────────────

def _user_key(payload: dict) -> str:
    key = str(payload.get("sub") or payload.get("email") or "").strip().lower()
    if not key:
        raise HTTPException(status_code=401, detail="token tanpa identitas user")
    return key


@notifications_router.get("")
def list_notifications(user: Admin, conn: Conn, limit: int = Query(30, ge=1, le=100),
                       unread_only: bool = False, before_id: Optional[int] = Query(None, ge=1)) -> dict:
    return notif.list_for(conn, _user_key(user), limit=limit, unread_only=unread_only, before_id=before_id)


@notifications_router.post("/read-all")
def read_all(user: Admin, conn: Conn) -> dict:
    key = _user_key(user)
    notif.mark_all_read(conn, key)
    return {"ok": True, "unread": notif.unread_count(conn, key)}


@notifications_router.post("/{notification_id}/read")
def read_one(notification_id: int, user: Admin, conn: Conn) -> dict:
    key = _user_key(user)
    if not notif.mark_read(conn, key, notification_id):
        raise HTTPException(status_code=404, detail="notifikasi tidak ditemukan")
    return {"ok": True, "unread": notif.unread_count(conn, key)}
