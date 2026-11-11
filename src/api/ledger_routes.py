"""/api/v1/lab/ledger — Signal Ledger ("Catatan Sinyal"). Admin-only, read-only.

SQL against lab.db only. Recording and scoring happen in the lab worker
(src/lab/ledger); these endpoints never call an exchange.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.lab.db import loads
from src.lab.ledger import HORIZONS, SOURCES
from src.lab.ledger.scoring import outcome_rows
from src.lab.ledger.stats import MIN_N_ANY, MIN_N_OK, horizon_stats
from src.lab.ledger.store import ensure_schema, kv_get

from .lab_auth import lab_admin
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/ledger", tags=["lab-ledger"])
Admin = Annotated[dict, Depends(lab_admin)]
Conn = Annotated[Any, Depends(_conn)]


def _day(v: Optional[str], name: str) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be YYYY-MM-DD")


def _where(source: Optional[str], symbol: Optional[str], signal_type: Optional[str], since: Optional[str],
           until: Optional[str], direction: Optional[int] = None) -> tuple[str, list]:
    if source and source not in SOURCES:
        raise HTTPException(status_code=422, detail=f"source must be one of {list(SOURCES)}")
    sql, args = ["1=1"], []
    if source:
        sql.append("s.source=?")
        args.append(source)
    if symbol:
        sql.append("s.symbol=?")
        args.append(symbol.upper().replace("/", "").split(":")[0])
    if signal_type:
        sql.append("s.signal_type=?")
        args.append(signal_type)
    if direction in (1, -1):
        sql.append("s.direction=?")
        args.append(direction)
    a, b = _day(since, "since"), _day(until, "until")
    if a:
        sql.append("s.ts >= ?")
        args.append(a.isoformat())
    if b:
        sql.append("s.ts < ?")
        args.append((b + timedelta(days=1)).isoformat())
    return " AND ".join(sql), args


@router.get("/meta")
def meta(_: Admin, conn: Conn) -> dict:
    """Recording status + filter options."""
    ensure_schema(conn)
    counts = [dict(r) for r in conn.execute(
        "SELECT source, signal_type, COUNT(*) AS n, SUM(status='pending') AS pending, MIN(ts) AS first_ts, "
        "MAX(ts) AS last_ts FROM ledger_signals GROUP BY source, signal_type ORDER BY source, signal_type")]
    symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ledger_signals ORDER BY symbol")]
    last_snap = conn.execute("SELECT MAX(bar) FROM ledger_screener_snapshots WHERE kind='live'").fetchone()[0]
    cycle = kv_get(conn, "ledger_last_cycle") or None
    if cycle:
        cycle = {k: cycle.get(k) for k in ("bar", "started", "finished", "screener", "collect", "score")}
    job = conn.execute("SELECT id, status, progress_json, error FROM lab_jobs WHERE kind='ledger_backfill' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "horizons": list(HORIZONS),
        "sources": list(SOURCES),
        "types": counts,
        "symbols": symbols,
        "live_since": kv_get(conn, "ledger_live_since"),
        "last_live_snapshot": last_snap,
        "last_cycle": cycle,
        "backfill": kv_get(conn, "ledger_backfill"),
        "backfill_job": {"id": job["id"], "status": job["status"], "progress": loads(job["progress_json"]),
                         "error": job["error"]} if job else None,
        "thresholds": {"min_n_any": MIN_N_ANY, "min_n_ok": MIN_N_OK},
    }


@router.get("/summary")
def summary(_: Admin, conn: Conn, source: Optional[str] = None, symbol: Optional[str] = None,
            signal_type: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None,
            split: Literal["none", "direction"] = "none") -> dict:
    """Per (source, signal type[, direction]) statistics for every horizon."""
    ensure_schema(conn)
    where, args = _where(source, symbol, signal_type, since, until)
    groups: dict[tuple, dict] = {}
    for r in conn.execute(
            "SELECT s.id, s.source, s.signal_type, s.direction, s.symbol, s.ts, s.status, o.horizon, o.dir_ret_pct, "
            "o.rel_btc_pct, o.mfe_pct, o.mae_pct, o.hit FROM ledger_signals s "
            f"LEFT JOIN ledger_outcomes o ON o.signal_id = s.id WHERE {where}", args):
        key = (r["source"], r["signal_type"], r["direction"] if split == "direction" else 0)
        g = groups.setdefault(key, {"ids": set(), "pending": set(), "no_data": set(), "rows": {h: [] for h in HORIZONS}})
        g["ids"].add(r["id"])
        if r["status"] == "pending":
            g["pending"].add(r["id"])
        elif r["status"] == "no_data":
            g["no_data"].add(r["id"])
        if r["horizon"] in g["rows"]:
            g["rows"][r["horizon"]].append(dict(r))
    out = []
    for (src, stype, d), g in sorted(groups.items()):
        out.append({
            "source": src, "signal_type": stype, "direction": d or None,
            "n_signals": len(g["ids"]), "n_pending": len(g["pending"]), "n_no_data": len(g["no_data"]),
            "horizons": {h: horizon_stats(rows) for h, rows in g["rows"].items()},
        })
    return {"groups": out, "horizons": list(HORIZONS),
            "filters": {"source": source, "symbol": symbol, "signal_type": signal_type, "since": since,
                        "until": until, "split": split}}


@router.get("/signals")
def signals(_: Admin, conn: Conn, source: Optional[str] = None, symbol: Optional[str] = None,
            signal_type: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None,
            direction: Optional[int] = Query(None, ge=-1, le=1),
            limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    """Most recent signals first, with their outcomes per horizon."""
    ensure_schema(conn)
    where, args = _where(source, symbol, signal_type, since, until, direction)
    total = conn.execute(f"SELECT COUNT(*) FROM ledger_signals s WHERE {where}", args).fetchone()[0]
    rows = [dict(r) for r in conn.execute(
        "SELECT s.id, s.source, s.signal_type, s.symbol, s.direction, s.ts, s.ref, s.price, s.entry_ts, "
        f"s.entry_price, s.status, s.meta_json FROM ledger_signals s WHERE {where} ORDER BY s.ts DESC, s.id DESC "
        "LIMIT ? OFFSET ?", [*args, limit, offset])]
    outs = outcome_rows(conn, [r["id"] for r in rows])
    for r in rows:
        r["meta"] = loads(r.pop("meta_json"), {}) or {}
        r["outcomes"] = outs.get(r["id"], {})
    return {"items": rows, "total": total, "limit": limit, "offset": offset}
