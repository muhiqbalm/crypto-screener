"""/api/v1/lab — Universal v0 (multi-coin portfolio) + Koin Terkuat. Admin-only, except
GET /strength (Koin Terkuat, "Peluang koin" -> Terkuat), which any logged-in user may read
(CEO decision 12 Nov); its refresh stays admin-only.

Like lab_routes: SQL against lab.db and JSON artifact reads only. Backtests,
data refreshes and paper rebalances run in the lab worker. Paper only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from src.lab import db as labdb
from src.lab import paper
from src.lab import queue as q
from src.lab.data_cache import cached_datasets
from src.lab.settings import get_lab_settings
from src.lab.universal import BAR_TF, TEMPLATE_ID, UNIVERSE_SYMBOL
from src.lab.universal import params as UP

from .lab_auth import lab_admin, lab_user
from .lab_models import N_TRIALS_OPTIONS, Costs, SearchSpec, _check_date
from .lab_routes import _conn, create_run

router = APIRouter(prefix="/api/v1/lab", tags=["lab-universal"])
Admin = Annotated[dict, Depends(lab_admin)]
User = Annotated[dict, Depends(lab_user)]
Conn = Annotated[Any, Depends(_conn)]


# ── models ───────────────────────────────────────────────────────────────

class UniversalRunCreate(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)
    mode: Literal["backtest", "validate", "optimize"] = "validate"
    start: Optional[str] = None
    end: Optional[str] = None
    n_trials: Optional[int] = None
    search: Optional[SearchSpec] = None

    @field_validator("start", "end")
    @classmethod
    def _dates(cls, v: Optional[str]) -> Optional[str]:
        return _check_date(v)

    @field_validator("n_trials")
    @classmethod
    def _trials(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in N_TRIALS_OPTIONS:
            raise ValueError(f"n_trials must be one of {list(N_TRIALS_OPTIONS)}")
        return v


class UniversalWatchCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)
    account_id: Optional[int] = None          # None + autopaper -> a new paper account is created
    starting_balance: float = Field(10000.0, gt=0, le=1e9)
    autopaper: bool = True
    telegram: bool = True
    run_id: Optional[int] = None


class UniversalWatchPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    autopaper: Optional[bool] = None
    telegram: Optional[bool] = None
    account_id: Optional[int] = None
    active: Optional[bool] = None


# ── helpers ──────────────────────────────────────────────────────────────

def _validate(params: dict) -> dict:
    try:
        return UP.validate_params(params)
    except UP.ParamError as e:
        raise HTTPException(422, f"invalid params: {e}")


def _artifact(*parts: str) -> Any:
    p = Path(get_lab_settings().artifacts_dir).joinpath(*parts)
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _universe() -> list[str]:
    return sorted({v["symbol"] for v in cached_datasets().values() if v["timeframe"] == BAR_TF})


def _get_watch(conn, wid: int) -> dict:
    w = conn.execute("SELECT * FROM universal_watches WHERE id=?", (wid,)).fetchone()
    if w is None:
        raise HTTPException(404, "universal watch not found")
    return dict(w)


def _watch_out(conn, w: dict) -> dict:
    st = conn.execute("SELECT * FROM universal_state WHERE watch_id=?", (w["id"],)).fetchone()
    acct = None
    if w["account_id"]:
        try:
            a = paper.account_summary(conn, w["account_id"])
            acct = {k: a[k] for k in ("id", "name", "balance", "equity", "starting_balance", "realized_pnl",
                                      "open_positions")}
        except paper.PaperError:
            acct = None
    last = conn.execute("SELECT * FROM universal_rebalances WHERE watch_id=? ORDER BY id DESC LIMIT 1",
                        (w["id"],)).fetchone()
    return {
        "id": w["id"], "name": w["name"], "params": labdb.loads(w["params_json"], {}),
        "costs": labdb.loads(w["costs_json"], {}), "account_id": w["account_id"],
        "autopaper": bool(w["autopaper_enabled"]), "telegram": bool(w["telegram_enabled"]),
        "active": bool(w["active"]), "run_id": w["run_id"], "created_at": w["created_at"],
        "last_rebalance_bar": w["last_rebalance_bar"], "account": acct,
        "state": None if st is None else {
            "computed_at": st["computed_at"], "last_bar": st["last_bar"],
            "targets": labdb.loads(st["targets_json"], []) or [], "ranks": labdb.loads(st["ranks_json"], []) or [],
            "next_rebalance": st["next_rebalance"], "error": st["error"]},
        "last_rebalance": None if last is None else _rebalance_out(last),
    }


def _rebalance_out(r) -> dict:
    return {"id": r["id"], "bar": r["bar"], "targets": labdb.loads(r["targets_json"], []) or [],
            "orders": labdb.loads(r["orders_json"], []) or [], "equity": r["equity"], "note": r["note"],
            "created_at": r["created_at"]}


def _enqueue_refresh(conn) -> Optional[int]:
    busy = conn.execute("SELECT id FROM lab_jobs WHERE kind='universe_refresh' AND status IN ('queued','running')"
                        ).fetchone()
    if busy:
        return int(busy["id"])
    jid = q.enqueue(conn, "universe_refresh", None, {"manual": True}, priority=10)
    conn.commit()
    return jid


# ── schema / runs ────────────────────────────────────────────────────────

@router.get("/universal/schema")
def universal_schema(_: Admin, conn: Conn) -> dict:
    row = conn.execute("SELECT * FROM holdout_locks WHERE template_id=? AND symbol=? AND timeframe=?",
                       (TEMPLATE_ID, UNIVERSE_SYMBOL, BAR_TF)).fetchone()
    lock = {"holdout_start": row["holdout_start"], "touches": row["touches"]} if row else None
    return {**UP.public_schema(), "defaults": UP.defaults(), "universe": _universe(), "holdout_lock": lock,
            "tunable": [p["key"] for p in UP.tunable_params()]}


@router.post("/universal/runs")
def create_universal_run(body: UniversalRunCreate, _: Admin, conn: Conn) -> dict:
    params = _validate(body.params)
    if body.start and body.end and body.start >= body.end:
        raise HTTPException(422, "start must be before end")
    search = None
    if body.search is not None:
        if body.mode != "optimize":
            raise HTTPException(422, "search is only allowed with mode=optimize")
        try:
            specs = UP.resolve_search(body.search.model_dump())
        except UP.ParamError as e:
            raise HTTPException(422, f"invalid search: {e}")
        search = {"params": [x["key"] for x in specs], "ranges": {x["key"]: [x["min"], x["max"]] for x in specs}}
    run_id, job_id = create_run(
        conn, template_id=TEMPLATE_ID, symbol=UNIVERSE_SYMBOL, timeframe=BAR_TF, mode=body.mode, params=params,
        costs=body.costs.model_dump(), start=body.start, end=body.end, n_trials=body.n_trials, search=search)
    conn.commit()
    return {"run_id": run_id, "job_id": job_id}


@router.get("/universal/runs/{run_id}/contrib")
def universal_contrib(run_id: int, _: Admin, conn: Conn) -> dict:
    r = conn.execute("SELECT template_id FROM lab_runs WHERE id=?", (run_id,)).fetchone()
    if r is None or r["template_id"] != TEMPLATE_ID:
        raise HTTPException(404, "universal run not found")
    return _artifact("runs", str(run_id), "contrib.json") or {"full": [], "holdout": None}


# ── Koin Terkuat ─────────────────────────────────────────────────────────

@router.get("/strength")
def strength(_: User, conn: Conn) -> dict:
    data = _artifact("strength.json")
    job = conn.execute("SELECT id, status, created_at FROM lab_jobs WHERE kind='universe_refresh' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    refresh = None if job is None else {"job_id": job["id"], "status": job["status"], "created_at": job["created_at"]}
    if data is None:
        return {"computed_at": None, "last_bar": None, "rows": [], "refresh": refresh}
    return {**data, "refresh": refresh}


@router.post("/strength/refresh")
def strength_refresh(_: Admin, conn: Conn) -> dict:
    return {"job_id": _enqueue_refresh(conn)}


# ── Universal watches (paper auto-trading) ───────────────────────────────

@router.post("/universal/watches")
def create_universal_watch(body: UniversalWatchCreate, _: Admin, conn: Conn) -> dict:
    params = _validate(body.params)
    acct = body.account_id
    if acct is not None:
        try:
            paper.get_account(conn, acct)
        except paper.PaperError as e:
            raise HTTPException(404, str(e))
    elif body.autopaper:
        acct = paper.create_account(conn, (body.name or "Universal v0")[:60] + " (paper)", body.starting_balance,
                                    risk_pct=1.0, leverage_max=max(1.0, float(params["max_gross"])))
    wid = conn.execute(
        "INSERT INTO universal_watches (name, params_json, costs_json, account_id, autopaper_enabled, telegram_enabled, "
        "active, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (body.name, labdb.dumps(params), labdb.dumps(body.costs.model_dump()), acct, 1 if body.autopaper else 0,
         1 if body.telegram else 0, body.run_id, labdb.utcnow())).lastrowid
    conn.commit()
    _enqueue_refresh(conn)
    return {"watch_id": int(wid), "account_id": acct}


@router.get("/universal/watches")
def list_universal_watches(_: Admin, conn: Conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM universal_watches WHERE active=1 ORDER BY id DESC").fetchall()
    return [_watch_out(conn, dict(r)) for r in rows]


@router.get("/universal/watches/{watch_id}")
def get_universal_watch(watch_id: int, _: Admin, conn: Conn) -> dict:
    return _watch_out(conn, _get_watch(conn, watch_id))


@router.patch("/universal/watches/{watch_id}")
def patch_universal_watch(watch_id: int, body: UniversalWatchPatch, _: Admin, conn: Conn) -> dict:
    w = _get_watch(conn, watch_id)
    if body.account_id is not None:
        try:
            paper.get_account(conn, body.account_id)
        except paper.PaperError as e:
            raise HTTPException(404, str(e))
        conn.execute("UPDATE universal_watches SET account_id=? WHERE id=?", (body.account_id, watch_id))
    if body.autopaper is not None:
        if body.autopaper and not (body.account_id or w["account_id"]):
            raise HTTPException(422, "account_id is required to enable autopaper")
        conn.execute("UPDATE universal_watches SET autopaper_enabled=? WHERE id=?", (int(body.autopaper), watch_id))
    if body.telegram is not None:
        conn.execute("UPDATE universal_watches SET telegram_enabled=? WHERE id=?", (int(body.telegram), watch_id))
    if body.name is not None:
        conn.execute("UPDATE universal_watches SET name=? WHERE id=?", (body.name, watch_id))
    if body.active is not None:
        conn.execute("UPDATE universal_watches SET active=? WHERE id=?", (int(body.active), watch_id))
    conn.commit()
    return _watch_out(conn, _get_watch(conn, watch_id))


@router.delete("/universal/watches/{watch_id}")
def delete_universal_watch(watch_id: int, _: Admin, conn: Conn) -> dict:
    """Deactivates the watch (history, paper positions and journal are kept; open
    paper positions stay open until closed manually)."""
    _get_watch(conn, watch_id)
    conn.execute("UPDATE universal_watches SET active=0 WHERE id=?", (watch_id,))
    conn.commit()
    return {"id": watch_id, "active": False}


@router.get("/universal/watches/{watch_id}/rebalances")
def universal_rebalances(watch_id: int, _: Admin, conn: Conn,
                         limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    _get_watch(conn, watch_id)
    rows = conn.execute("SELECT * FROM universal_rebalances WHERE watch_id=? ORDER BY id DESC LIMIT ?",
                        (watch_id, limit)).fetchall()
    return [_rebalance_out(r) for r in rows]


@router.get("/universal/alerts")
def universal_alerts(_: Admin, conn: Conn, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    rows = conn.execute("SELECT id, channel, ref, text, status, error, created_at, sent_at FROM lab_alerts "
                        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
