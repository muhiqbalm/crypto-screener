"""/api/v1/lab/outlook (admin) + /api/v1/lab/regime (any logged-in user).

SQL reads of lab.db only: the outlook rows are computed by the lab worker
(``outlook_refresh`` job after every 4H close). The money projection is computed
here per request from the stored row and the client's capital / leverage / sizing.
Information only: nothing here places, sizes or suggests a live order.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.lab import db as labdb
from src.lab import regime as R
from src.lab.outlook import JOB_KIND
from src.lab.outlook import logic as L
from src.lab.outlook import store as S
from src.lab.outlook.schedule import enqueue_now

from .lab_auth import lab_admin, lab_user
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab", tags=["lab-outlook"])
Admin = Annotated[dict, Depends(lab_admin)]
User = Annotated[dict, Depends(lab_user)]
Conn = Annotated[Any, Depends(_conn)]

Capital = Annotated[float, Query(gt=0, le=1e9, description="Modal (USDT)")]
Leverage = Annotated[float, Query(ge=1, le=20, description="Leverage; posisi = modal x leverage (mode notional)")]
Sizing = Annotated[Literal["notional", "risk"], Query(description="notional = modal x leverage; risk = rugi di SL = risk_pct modal")]
RiskPct = Annotated[float, Query(gt=0, le=10)]

_DISCLAIMER = ("Bukan saran investasi; strategi bisa salah; preset GAGAL/belum diuji = keyakinan rendah. "
               "Angka proyeksi adalah hitungan, bukan jaminan.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(conn) -> dict | None:
    r = conn.execute("SELECT id, status, created_at, started_at, finished_at, error, progress_json FROM lab_jobs WHERE kind=? "
                     "ORDER BY id DESC LIMIT 1", (JOB_KIND,)).fetchone()
    if r is None:
        return None
    out = dict(r)
    out["progress"] = labdb.loads(out.pop("progress_json"))
    return out


def _decorate(row: dict, now: str, capital: float, leverage: float, sizing: str, risk_pct: float) -> dict:
    if row.get("unavailable"):
        return row
    age = L.hours_between(row.get("last_bar_close"), now)
    return {**row, "age_hours": age, "stale": age is not None and age > L.STALE_HOURS,
            "projection": L.project(row, capital, leverage, sizing, risk_pct)}


def _lite(row: dict) -> dict:
    out = dict(row)
    exp = row.get("explanation") or {}
    out["explanation"] = {"summary": exp.get("summary"), "narrator": exp.get("narrator")}
    return out


@router.get("/outlook")
def outlook(_: Admin, conn: Conn, capital: Capital = 1000.0, leverage: Leverage = 1.0, sizing: Sizing = "notional",
            risk_pct: RiskPct = 1.0) -> dict:
    S.ensure_schema(conn)
    now = _now_iso()
    rows = [_lite(_decorate(r, now, capital, leverage, sizing, risk_pct)) for r in S.read_rows(conn)]
    reg = R.load(conn) or {}
    return {
        "meta": S.kv_get(conn, S.META_KEY), "refresh": _job(conn), "now": now,
        "inputs": {"capital": capital, "leverage": leverage, "sizing": sizing, "risk_pct": risk_pct},
        "regime": {k: reg.get(k) and {x: reg[k].get(x) for x in ("label", "label_text", "as_of", "days_in_label",
                                                                  "dist_ema_slow_pct", "slope_pct", "available")}
                   for k in ("btc", "eth")},
        "method": L.method(), "disclaimer": _DISCLAIMER, "rows": rows,
    }


@router.post("/outlook/refresh")
def outlook_refresh(_: Admin, conn: Conn) -> dict:
    j = _job(conn)
    if j and j["status"] in ("queued", "running"):
        return {"job_id": j["id"], "already": True}
    return {"job_id": enqueue_now(conn), "already": False}


@router.get("/outlook/{symbol}")
def outlook_detail(symbol: str, _: Admin, conn: Conn, capital: Capital = 1000.0, leverage: Leverage = 1.0,
                   sizing: Sizing = "notional", risk_pct: RiskPct = 1.0) -> dict:
    sym = symbol.upper().replace("/", "").replace(":USDT", "")
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    got = S.read_one(conn, sym)
    if got is None or got["row"] is None:
        raise HTTPException(404, f"outlook untuk {sym} belum tersedia")
    now = _now_iso()
    reg = R.load(conn) or {}
    row = _decorate(got["row"], now, capital, leverage, sizing, risk_pct)
    return {**row, "error": got["error"], "detail": got["detail"], "now": now,
            "inputs": {"capital": capital, "leverage": leverage, "sizing": sizing, "risk_pct": risk_pct},
            "regime": {"btc": reg.get("btc"), "eth": reg.get("eth"), "rule": reg.get("rule")},
            "method": L.method(), "disclaimer": _DISCLAIMER}


@router.get("/regime")
def regime(user: User, conn: Conn) -> dict:
    """BTC + ETH regime for any logged-in user; per-preset performance by regime for Lab admins only."""
    reg = R.load(conn)
    if reg is None:
        return {"computed_at": None, "rule": R.RULE, "btc": None, "eth": None, "presets": None,
                "available": False}
    out = {**reg, "available": True}
    if not user["is_admin"]:
        out["presets"] = None
        out.pop("btc_history_share_pct", None)
    return out
