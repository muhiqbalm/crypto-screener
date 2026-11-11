"""/api/v1/lab — Strategy Lab API.

Thin by design: SQL against lab.db and file reads only. It never runs a
backtest and never imports the engine; heavy work is queued for the separate
``bmtm-lab-worker`` process. All endpoints are admin-only (LAB_ADMIN_EMAILS).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.lab import db as labdb
from src.lab import journal as jr
from src.lab import market
from src.lab import paper
from src.lab import queue as q
from src.lab.data_cache import cached_datasets
from src.lab.settings import get_lab_settings
from src.lab.templates import TEMPLATES, get_template
from src.lab.templates.rosyade_family import ParamError

from .lab_auth import lab_admin, lab_user
from .lab_models import AutoPaper, JournalPatch, PaperAccountCreate, PaperOrderCreate, RunCreate, ScanCreate, \
    WatchCreate

router = APIRouter(prefix="/api/v1/lab", tags=["lab"])
Admin = Annotated[dict, Depends(lab_admin)]

MAX_SCAN_COMBOS = 200


def _conn():
    conn = labdb.connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[Any, Depends(_conn)]


# ── helpers ──────────────────────────────────────────────────────────────

def _template_or_422(template_id: str):
    t = get_template(template_id)
    if t is None:
        raise HTTPException(422, f"unknown template_id {template_id}")
    return t


def _validate(t, timeframe: str, params: dict) -> dict:
    if timeframe not in t.TIMEFRAMES:
        raise HTTPException(422, f"timeframe must be one of {t.TIMEFRAMES}")
    try:
        return t.validate_params(params)
    except ParamError as e:
        raise HTTPException(422, f"invalid params: {e}")


def _resolve_search(t, mode: str, search) -> Optional[dict]:
    """Validate an optimize search spec -> normalised {params, ranges} (422 on error)."""
    if search is None:
        return None
    if mode != "optimize":
        raise HTTPException(422, "search is only allowed with mode=optimize")
    try:
        specs = t.resolve_search(search.model_dump())
    except ParamError as e:
        raise HTTPException(422, f"invalid search: {e}")
    return {"params": [x["key"] for x in specs], "ranges": {x["key"]: [x["min"], x["max"]] for x in specs}}


def create_run(conn, *, template_id: str, symbol: str, timeframe: str, mode: str, params: dict,
               costs: dict, start: Optional[str], end: Optional[str], n_trials: Optional[int] = None,
               scan_id: Optional[int] = None, priority: int = 0,
               search: Optional[dict] = None) -> tuple[int, int]:
    now = labdb.utcnow()
    cfg = conn.execute(
        "INSERT INTO strategy_configs (template_id, params_json, created_at) VALUES (?, ?, ?)",
        (template_id, labdb.dumps(params), now)).lastrowid
    run_id = conn.execute(
        "INSERT INTO lab_runs (scan_id, config_id, template_id, symbol, timeframe, mode, status, start_date, "
        "end_date, params_json, costs_json, search_json, n_trials, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
        (scan_id, cfg, template_id, symbol, timeframe, mode, start, end, labdb.dumps(params),
         labdb.dumps(costs), labdb.dumps(search), n_trials if mode == "optimize" else None, now)).lastrowid
    job_id = q.enqueue(conn, "run", run_id, {"n_trials": n_trials} if n_trials else {}, priority=priority)
    conn.execute("UPDATE lab_runs SET job_id=? WHERE id=?", (job_id, run_id))
    return int(run_id), int(job_id)


_LIST_FIELDS = ("id", "template_id", "symbol", "timeframe", "mode", "status", "verdict", "net_return_pct",
                "profit_factor", "max_dd_pct", "trades", "created_at")


def _run_list_item(r) -> dict:
    d = {k: r[k] for k in _LIST_FIELDS}
    d["job_id"] = r["job_id"]
    d["scan_id"] = r["scan_id"]
    return d


def _run_detail(r) -> dict:
    d = _run_list_item(r)
    oos = labdb.loads(r["oos_metrics_json"])
    d.update({
        "params": labdb.loads(r["params_json"], {}),
        "costs": labdb.loads(r["costs_json"], {}),
        "start": r["start_date"],
        "end": r["end_date"],
        "metrics": labdb.loads(r["metrics_json"], {}) or {},
        "oos_metrics": oos,
        "checks": labdb.loads(r["checks_json"], []) or [],
        "holdout_touches": r["holdout_touches"],
        "holdout_start": r["holdout_start"],
        "honesty_version": r["honesty_version"],
        "engine_commit": r["engine_commit"],
        "error": r["error"],
        "finished_at": r["finished_at"],
        "best_params": labdb.loads(r["best_params_json"]),
    })
    extra = labdb.loads(r["extra_json"], {}) or {}
    if extra.get("sensitivity"):
        d["sensitivity"] = extra["sensitivity"]
    opt = extra.get("optimizer") or {}
    d.update({
        "search": labdb.loads(r["search_json"]),
        "n_trials": r["n_trials"],
        "trials_done": r["trials_done"],
        "top_trials": labdb.loads(r["top_trials_json"]),
        "objective": opt.get("objective"),
    })
    return d


def _get_run(conn, run_id: int):
    r = conn.execute("SELECT * FROM lab_runs WHERE id=?", (run_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "run not found")
    return r


def _artifact(run_id: int, name: str) -> list:
    p = Path(get_lab_settings().artifacts_dir) / "runs" / str(run_id) / name
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return []


def _screener_symbols() -> list[str]:
    try:
        from src.config.settings import Settings
        out = []
        for s in Settings().symbols_list:
            sym = s.split(":")[0].replace("/", "")
            if sym not in out:
                out.append(sym)
        return out
    except Exception:  # noqa: BLE001
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


# ── meta ─────────────────────────────────────────────────────────────────

@router.get("/me")
def me(user: Annotated[dict, Depends(lab_user)]) -> dict:
    return {"is_admin": bool(user["is_admin"])}


@router.get("/templates")
def templates(_: Admin) -> list[dict]:
    return [t.public_schema() for t in TEMPLATES.values()]


@router.get("/symbols")
def symbols(_: Admin) -> list[dict]:
    idx = cached_datasets()
    cached: dict[str, list[str]] = {}
    for v in idx.values():
        cached.setdefault(v["symbol"], []).append(v["timeframe"])
    order = _screener_symbols()
    for s in sorted(cached):
        if s not in order:
            order.append(s)
    return [{"symbol": s, "has_data": s in cached, "timeframes": sorted(cached.get(s, []))} for s in order]


@router.get("/data/status")
def data_status(_: Admin) -> list[dict]:
    idx = cached_datasets()
    return [{"symbol": v["symbol"], "timeframe": v["timeframe"], "first": v["first"], "last": v["last"],
             "rows": v["rows"]} for _, v in sorted(idx.items())]


# ── runs ─────────────────────────────────────────────────────────────────

@router.post("/runs")
def create_run_ep(body: RunCreate, _: Admin, conn: Conn) -> dict:
    t = _template_or_422(body.template_id)
    params = _validate(t, body.timeframe, body.params)
    if body.start and body.end and body.start >= body.end:
        raise HTTPException(422, "start must be before end")
    search = _resolve_search(t, body.mode, body.search)
    run_id, job_id = create_run(
        conn, template_id=body.template_id, symbol=body.symbol, timeframe=body.timeframe, mode=body.mode,
        params=params, costs=body.costs.model_dump(), start=body.start, end=body.end, n_trials=body.n_trials,
        search=search)
    conn.commit()
    return {"run_id": run_id, "job_id": job_id}


@router.get("/runs")
def list_runs(_: Admin, conn: Conn, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    rows = conn.execute("SELECT * FROM lab_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_run_list_item(r) for r in rows]


def _snooping(conn, r) -> dict:
    """How much this (template, symbol) has been tried across timeframes, so the UI
    can warn that picking the best timeframe/params out of many is data-snooping."""
    locks = conn.execute("SELECT timeframe, touches FROM holdout_locks WHERE template_id=? AND symbol=?",
                         (r["template_id"], r["symbol"])).fetchall()
    runs = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT timeframe) AS tfs, COALESCE(SUM(trials_done), 0) AS trials "
        "FROM lab_runs WHERE template_id=? AND symbol=? AND mode IN ('validate','optimize') "
        "AND status NOT IN ('cancelled','error')", (r["template_id"], r["symbol"])).fetchone()
    return {"timeframes_tested": sorted(x["timeframe"] for x in locks),
            "holdout_touches_all_tf": int(sum(x["touches"] or 0 for x in locks)),
            "validated_runs_all_tf": int(runs["n"] or 0),
            "optimizer_trials_all_tf": int(runs["trials"] or 0)}


@router.get("/runs/{run_id}")
def get_run(run_id: int, _: Admin, conn: Conn) -> dict:
    r = _get_run(conn, run_id)
    d = _run_detail(r)
    d["snooping"] = _snooping(conn, r)
    return d


@router.get("/runs/{run_id}/equity")
def run_equity(run_id: int, _: Admin, conn: Conn) -> list[dict]:
    _get_run(conn, run_id)
    return _artifact(run_id, "equity.json")


@router.get("/runs/{run_id}/trades")
def run_trades(run_id: int, _: Admin, conn: Conn) -> list[dict]:
    _get_run(conn, run_id)
    return _artifact(run_id, "trades.json")


# ── scans ────────────────────────────────────────────────────────────────

@router.post("/scans")
def create_scan(body: ScanCreate, _: Admin, conn: Conn) -> dict:
    t = _template_or_422(body.template_id)
    tfs = list(dict.fromkeys(body.timeframes))
    params = None
    for tf in tfs:
        params = _validate(t, tf, body.params)
    search = _resolve_search(t, body.mode, body.search)
    combos = [(s, tf) for s in body.symbols for tf in tfs]
    if len(combos) > MAX_SCAN_COMBOS:
        raise HTTPException(422, f"too many combinations ({len(combos)} > {MAX_SCAN_COMBOS})")
    scan_id = conn.execute(
        "INSERT INTO lab_scans (template_id, mode, symbols_json, timeframes_json, params_json, costs_json, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.template_id, body.mode, labdb.dumps(body.symbols), labdb.dumps(tfs), labdb.dumps(params),
         labdb.dumps(body.costs.model_dump()), labdb.utcnow())).lastrowid
    for s, tf in combos:
        run_id, _job = create_run(conn, template_id=body.template_id, symbol=s, timeframe=tf, mode=body.mode,
                                  params=params, costs=body.costs.model_dump(), start=body.start,
                                  end=body.end, n_trials=body.n_trials, scan_id=scan_id, priority=-1,
                                  search=search)
        conn.execute("INSERT INTO scan_rows (scan_id, symbol, timeframe, run_id) VALUES (?, ?, ?, ?)",
                     (scan_id, s, tf, run_id))
    conn.commit()
    return {"scan_id": int(scan_id)}


_VERDICT_ORDER = {"PASS": 0, "FAIL": 1, None: 2}


def _scan_out(conn, scan) -> dict:
    rows = conn.execute(
        "SELECT sr.symbol, sr.timeframe, sr.run_id, r.status, r.verdict, r.oos_metrics_json, r.trades "
        "FROM scan_rows sr JOIN lab_runs r ON r.id = sr.run_id WHERE sr.scan_id=?", (scan["id"],)).fetchall()
    out_rows = []
    for r in rows:
        oos = labdb.loads(r["oos_metrics_json"], {}) or {}
        out_rows.append({
            "symbol": r["symbol"], "timeframe": r["timeframe"], "run_id": r["run_id"], "status": r["status"],
            "verdict": r["verdict"], "oos_net_return_pct": oos.get("net_return_pct"),
            "oos_profit_factor": oos.get("profit_factor"), "oos_max_dd_pct": oos.get("max_dd_pct"),
            "trades": oos.get("trades") if oos else r["trades"],
        })
    out_rows.sort(key=lambda x: (_VERDICT_ORDER.get(x["verdict"], 2),
                                 -(x["oos_profit_factor"] if x["oos_profit_factor"] is not None else -1e9)))
    statuses = [r["status"] for r in out_rows]
    done = sum(1 for s in statuses if s in q.TERMINAL)
    if statuses and all(s == "cancelled" for s in statuses):
        status = "cancelled"
    elif done == len(statuses):
        status = "done"
    elif any(s == "running" for s in statuses) or done:
        status = "running"
    else:
        status = "queued"
    return {"id": scan["id"], "template_id": scan["template_id"], "mode": scan["mode"],
            "created_at": scan["created_at"], "status": status,
            "progress": {"done": done, "total": len(statuses)}, "rows": out_rows}


@router.get("/scans")
def list_scans(_: Admin, conn: Conn, limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    scans = conn.execute("SELECT * FROM lab_scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_scan_out(conn, s) for s in scans]


@router.get("/scans/{scan_id}")
def get_scan(scan_id: int, _: Admin, conn: Conn) -> dict:
    s = conn.execute("SELECT * FROM lab_scans WHERE id=?", (scan_id,)).fetchone()
    if s is None:
        raise HTTPException(404, "scan not found")
    return _scan_out(conn, s)


# ── jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
def get_job(job_id: int, _: Admin, conn: Conn) -> dict:
    j = q.get_job(conn, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return {"id": j["id"], "kind": j["kind"], "ref_id": j["ref_id"], "status": j["status"],
            "progress": j["progress"], "error": j["error"], "created_at": j["created_at"],
            "started_at": j["started_at"], "finished_at": j["finished_at"]}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, _: Admin, conn: Conn) -> dict:
    status = q.request_cancel(conn, job_id)
    if status is None:
        raise HTTPException(404, "job not found")
    return {"id": job_id, "status": status}


# ── chart data (light, cached public fetch; never src.trading) ───────────

@router.get("/klines")
def klines(_: Admin, symbol: str, timeframe: str = "4h", limit: int = Query(500, ge=10, le=1500)) -> list[dict]:
    from .lab_models import norm_symbol
    try:
        sym = norm_symbol(symbol)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if timeframe not in market.TF_SECONDS:
        raise HTTPException(422, f"timeframe must be one of {list(market.TF_SECONDS)}")
    try:
        return market.klines(sym, timeframe, limit, ttl=get_lab_settings().klines_cache_s)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"market data unavailable: {type(e).__name__}")


# ── watches ──────────────────────────────────────────────────────────────

def _get_watch(conn, watch_id: int):
    w = conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
    if w is None:
        raise HTTPException(404, "watch not found")
    return w


def _state_out(watch_id: int, st) -> dict:
    if st is None:
        return {"watch_id": watch_id, "computed_at": None, "last_bar": None, "position": None,
                "recent_trades": [], "last_signal": None, "error": None}
    return {"watch_id": watch_id, "computed_at": st["computed_at"], "last_bar": st["last_bar"],
            "position": labdb.loads(st["position_json"]), "recent_trades": labdb.loads(st["recent_trades_json"], []),
            "last_signal": labdb.loads(st["last_signal_json"]), "error": st["error"]}


def _watch_out(conn, w) -> dict:
    st = conn.execute("SELECT * FROM watch_state WHERE watch_id=?", (w["id"],)).fetchone()
    state = _state_out(w["id"], st)
    state.pop("recent_trades")
    return {"id": w["id"], "template_id": w["template_id"], "symbol": w["symbol"], "timeframe": w["timeframe"],
            "params": labdb.loads(w["params_json"], {}), "costs": labdb.loads(w["costs_json"], {}),
            "created_at": w["created_at"],
            "autopaper": ({"account_id": w["autopaper_account_id"], "enabled": bool(w["autopaper_enabled"])}
                          if w["autopaper_account_id"] else None),
            "state": state}


@router.post("/watches")
def create_watch(body: WatchCreate, _: Admin, conn: Conn) -> dict:
    t = _template_or_422(body.template_id)
    params = _validate(t, body.timeframe, body.params)
    n_active = conn.execute("SELECT COUNT(*) FROM watches WHERE active=1").fetchone()[0]
    if n_active >= get_lab_settings().watch_max_active:
        raise HTTPException(422, f"too many active watches ({n_active}); delete one first")
    wid = conn.execute(
        "INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (body.template_id, body.symbol, body.timeframe, labdb.dumps(params), labdb.dumps(body.costs.model_dump()),
         labdb.utcnow())).lastrowid
    q.enqueue(conn, "watch_eval", wid, {"initial": True}, priority=10)
    conn.commit()
    return {"watch_id": int(wid)}


@router.get("/watches")
def list_watches(_: Admin, conn: Conn) -> list[dict]:
    return [_watch_out(conn, w) for w in conn.execute("SELECT * FROM watches WHERE active=1 ORDER BY id DESC")]


@router.delete("/watches/{watch_id}")
def delete_watch(watch_id: int, _: Admin, conn: Conn) -> dict:
    _get_watch(conn, watch_id)
    conn.execute("DELETE FROM watch_state WHERE watch_id=?", (watch_id,))
    conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))
    # single-watch jobs only; a batched job (payload.watch_ids) just skips the deleted watch
    conn.execute("UPDATE lab_jobs SET status='cancelled', finished_at=? WHERE kind='watch_eval' AND ref_id=? "
                 "AND status='queued' AND payload_json NOT LIKE '%\"watch_ids\"%'", (labdb.utcnow(), watch_id))
    conn.commit()
    return {"id": watch_id, "deleted": True}


@router.get("/watches/{watch_id}/state")
def watch_state(watch_id: int, _: Admin, conn: Conn) -> dict:
    _get_watch(conn, watch_id)
    st = conn.execute("SELECT * FROM watch_state WHERE watch_id=?", (watch_id,)).fetchone()
    return _state_out(watch_id, st)


@router.post("/watches/{watch_id}/autopaper")
def watch_autopaper(watch_id: int, body: AutoPaper, _: Admin, conn: Conn) -> dict:
    w = _get_watch(conn, watch_id)
    acct = body.account_id or w["autopaper_account_id"]
    if body.enabled:
        if not acct:
            raise HTTPException(422, "account_id is required to enable autopaper")
        try:
            paper.get_account(conn, acct)
        except paper.PaperError as e:
            raise HTTPException(404, str(e))
    conn.execute("UPDATE watches SET autopaper_account_id=?, autopaper_enabled=? WHERE id=?",
                 (acct, 1 if body.enabled else 0, watch_id))
    conn.commit()
    return {"watch_id": watch_id, "autopaper": {"account_id": acct, "enabled": bool(body.enabled)}}


@router.get("/watches/{watch_id}/compare")
def watch_compare(watch_id: int, _: Admin, conn: Conn) -> dict:
    """Paper results of this watch vs the watch's own backtest trades over the same period."""
    w = _get_watch(conn, watch_id)
    entries = jr.query(conn, watch_id=watch_id)
    open_pos = [dict(r) for r in conn.execute(
        "SELECT * FROM paper_positions WHERE watch_id=? AND status='open'", (watch_id,))]
    starts = [e["entry_time"] for e in entries if e.get("entry_time")] + [p["entry_time"] for p in open_pos]
    period_from = min(starts) if starts else w["created_at"]
    st = conn.execute("SELECT * FROM watch_state WHERE watch_id=?", (watch_id,)).fetchone()
    bt = [t for t in (labdb.loads(st["recent_trades_json"], []) if st else [])
          if (t.get("entry_time") or "") >= period_from[:19]]
    p_stats = jr.stats(entries)
    roe = [t.get("return_on_equity_pct") or 0.0 for t in bt]
    growth = 1.0
    for r in roe:
        growth *= 1 + r / 100.0
    b_sum = jr.summarize_trades([t.get("pnl_pct") or 0.0 for t in bt])
    return {
        "watch_id": watch_id,
        "period": {"from": period_from, "to": labdb.utcnow()},
        "paper": {"trades": p_stats["trades"], "open_positions": len(open_pos), "winrate": p_stats["winrate"],
                  "profit_factor": p_stats["profit_factor"], "net_pnl": p_stats["net_pnl"],
                  "avg_r": p_stats["avg_r"], "entries": entries},
        "backtest": {"trades": len(bt), "winrate": b_sum["winrate"],
                     "net_return_pct": (growth - 1.0) * 100.0 if bt else 0.0,
                     "profit_factor": jr.summarize_trades(roe)["profit_factor"],
                     "position": labdb.loads(st["position_json"]) if st else None, "trades_list": bt},
    }


# ── paper trading (simulated only) ───────────────────────────────────────

@router.post("/paper/accounts")
def create_paper_account(body: PaperAccountCreate, _: Admin, conn: Conn) -> dict:
    return {"id": paper.create_account(conn, body.name, body.starting_balance, body.risk_pct, body.leverage_max)}


@router.get("/paper/accounts")
def list_paper_accounts(_: Admin, conn: Conn) -> list[dict]:
    return [paper.account_summary(conn, r["id"]) for r in conn.execute("SELECT id FROM paper_accounts ORDER BY id")]


@router.get("/paper/positions")
def list_paper_positions(_: Admin, conn: Conn, account_id: Optional[int] = None,
                         status: str = Query("open", pattern="^(open|closed|all)$")) -> list[dict]:
    sql, args = "SELECT * FROM paper_positions WHERE 1=1", []
    if account_id is not None:
        sql += " AND account_id=?"
        args.append(account_id)
    if status != "all":
        sql += " AND status=?"
        args.append(status)
    return [paper.position_out(dict(r)) for r in conn.execute(sql + " ORDER BY id DESC LIMIT 500", args)]


def _price(symbol: str) -> float:
    try:
        return market.last_price(symbol)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"price unavailable for {symbol}: {type(e).__name__}")


@router.post("/paper/orders")
def paper_order(body: PaperOrderCreate, _: Admin, conn: Conn) -> dict:
    try:
        paper.get_account(conn, body.account_id)
    except paper.PaperError as e:
        raise HTTPException(404, str(e))
    if body.watch_id is not None:
        _get_watch(conn, body.watch_id)
    px = _price(body.symbol)
    try:
        pos = paper.open_position(conn, account_id=body.account_id, symbol=body.symbol, side=body.side, price=px,
                                  sl=body.sl, tp=body.tp, qty=body.qty, note=body.note, watch_id=body.watch_id,
                                  source="paper_manual")
    except paper.PaperError as e:
        raise HTTPException(422, str(e))
    return {"position_id": pos["id"], "position": paper.position_out(pos), "market_price": px}


@router.post("/paper/positions/{position_id}/close")
def paper_close(position_id: int, _: Admin, conn: Conn) -> dict:
    p = conn.execute("SELECT * FROM paper_positions WHERE id=?", (position_id,)).fetchone()
    if p is None:
        raise HTTPException(404, "position not found")
    if p["status"] != "open":
        raise HTTPException(409, "position already closed")
    px = _price(p["symbol"])
    try:
        out = paper.close_position(conn, position_id, px, "manual_close")
    except paper.PaperError as e:
        raise HTTPException(409, str(e))
    j = conn.execute("SELECT * FROM journal_entries WHERE id=?", (out["journal_id"],)).fetchone()
    return {"id": position_id, "exit_price": out["exit_price"], "pnl": out["pnl"],
            "r_multiple": j["r_multiple"] if j else None, "journal_id": out["journal_id"]}


# ── journal ──────────────────────────────────────────────────────────────

@router.get("/journal")
def journal_list(_: Admin, conn: Conn, account_id: Optional[int] = None, source: Optional[str] = None,
                 symbol: Optional[str] = None, from_: Optional[str] = Query(None, alias="from"),
                 to: Optional[str] = None, limit: int = Query(1000, ge=1, le=5000)) -> list[dict]:
    return jr.query(conn, account_id=account_id, source=source, symbol=symbol.upper() if symbol else None,
                    date_from=from_, date_to=to, limit=limit)


@router.get("/journal/stats")
def journal_stats(_: Admin, conn: Conn, account_id: Optional[int] = None, source: Optional[str] = None) -> dict:
    entries = jr.query(conn, account_id=account_id, source=source, limit=100000)
    start = None
    if account_id is not None:
        try:
            start = paper.get_account(conn, account_id)["starting_balance"]
        except paper.PaperError as e:
            raise HTTPException(404, str(e))
    return jr.stats(entries, start)


@router.patch("/journal/{entry_id}")
def journal_patch(entry_id: int, body: JournalPatch, _: Admin, conn: Conn) -> dict:
    r = conn.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "journal entry not found")
    if body.notes is not None:
        conn.execute("UPDATE journal_entries SET notes=? WHERE id=?", (body.notes, entry_id))
    if body.tags is not None:
        conn.execute("UPDATE journal_entries SET tags=? WHERE id=?", (labdb.dumps(body.tags), entry_id))
    conn.commit()
    return jr.entry_out(conn.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone())
