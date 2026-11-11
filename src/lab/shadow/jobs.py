"""``shadow_cycle`` job: collect live webhook signals from trade_logs (read-only) and
evaluate every signal that is due. The first cycle is the backfill: every row in
trade_logs is collected and evaluated (older windows via data.binance.vision).

A signal is first looked at ``first_delay_s`` after the alert, re-evaluated as each
time-to-live window closes ("partial"), and is "done" once the longest one is over.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from ..db import dumps, loads, utcnow
from ..ledger.store import iso, kv_set, to_epoch
from ..settings import get_lab_settings
from .market import PublicMarket, default_cache_dir
from .simulate import evaluate
from .source import group_signals, read_trade_logs
from .store import ensure_schema, shadow_settings

log = logging.getLogger("lab.shadow.jobs")

GIVE_UP_S = 3 * 86400          # stop retrying a signal that still can't be evaluated
NONFINAL_WAIT_S = 86400        # stop waiting for trade_logs rows to reach a final status


def _sync(conn, sigs: list[dict], first_delay_s: int, now: float) -> dict:
    """Insert new signals; re-queue known ones whose trade_logs facts changed."""
    new = changed = 0
    for s in sigs:
        row = conn.execute("SELECT id, fill_price, arrival_ts, n_rows, statuses_json FROM shadow_signals "
                           "WHERE key=?", (s["key"],)).fetchone()
        facts = (s["fill_price"], s["fill_qty"], iso(s["fill_s"]) if s["fill_s"] else None, s["fill_ts_basis"],
                 iso(s["arrival_s"]), s["arrival_basis"], s["off_close"], s["n_rows"], s["n_users"],
                 dumps({"statuses": s["statuses"], "final": s["final"]}))
        if row is None:
            conn.execute(
                "INSERT INTO shadow_signals (key, symbol, action, side, trade_dir, tf, bar_close_ts, fill_price, "
                "fill_qty, fill_ts, fill_ts_basis, arrival_ts, arrival_basis, off_close, n_rows, n_users, "
                "statuses_json, status, next_due, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, 'pending', ?, ?)",
                (s["key"], s["symbol"], s["action"], s["side"], s["trade_dir"], s["tf"], iso(s["bar_close_s"]),
                 *facts, iso(max(now, s["arrival_s"] + first_delay_s)), utcnow()))
            new += 1
            continue
        same = (row["fill_price"] == s["fill_price"] and row["arrival_ts"] == iso(s["arrival_s"])
                and row["n_rows"] == s["n_rows"] and row["statuses_json"] == facts[-1])
        if not same:
            conn.execute(
                "UPDATE shadow_signals SET fill_price=?, fill_qty=?, fill_ts=?, fill_ts_basis=?, arrival_ts=?, "
                "arrival_basis=?, off_close=?, n_rows=?, n_users=?, statuses_json=?, status='pending', next_due=? "
                "WHERE id=?", (*facts, iso(now), row["id"]))
            changed += 1
    conn.commit()
    return {"new": new, "changed": changed}


def _sig_input(r) -> dict:
    return {"symbol": r["symbol"], "trade_dir": r["trade_dir"], "tf": r["tf"],
            "bar_close_s": to_epoch(r["bar_close_ts"]), "arrival_s": to_epoch(r["arrival_ts"]),
            "fill_price": r["fill_price"], "fill_s": to_epoch(r["fill_ts"]) if r["fill_ts"] else None}


def _store(conn, sig_id: int, res: dict, cfg, row, now: float) -> str:
    a = res["actual"] or {}
    status = res["status"]
    arrival = to_epoch(row["arrival_ts"])
    final_logs = (loads(row["statuses_json"], {}) or {}).get("final", True)
    if status in ("pending", "no_data") and not res["complete"] and now - arrival > GIVE_UP_S:
        status = "no_data"
    nxt: Optional[str] = None
    if status == "partial" or (status == "pending" and now - arrival <= GIVE_UP_S):
        ends = [arrival + t * 60 for t in cfg.ttls_min if arrival + t * 60 + 60 > now]
        nxt = iso((min(ends) if ends else now) + 90) if status == "partial" else iso(now + 300)
    if status == "done" and not final_logs and now - arrival < NONFINAL_WAIT_S:
        status, nxt = "partial", iso(now + 600)           # trade_logs may still get the fill
    conn.execute(
        "UPDATE shadow_signals SET bar_close_px=?, atr=?, p0=?, p0_basis=?, slippage_bps=?, drift_bps=?, "
        "impact_bps=?, latency_s=?, exec_latency_s=?, status=?, error=?, next_due=?, computed_at=? WHERE id=?",
        (a.get("bar_close_px"), a.get("atr"), a.get("p0"), a.get("p0_basis"), a.get("slippage_bps"),
         a.get("drift_bps"), a.get("impact_bps"), a.get("latency_s"), a.get("exec_latency_s"), status,
         res.get("error"), nxt, utcnow(), sig_id))
    conn.execute("DELETE FROM shadow_results WHERE signal_id=?", (sig_id,))
    conn.executemany(
        "INSERT INTO shadow_results (signal_id, k, ttl_min, limit_px, outcome, fill_ts, time_to_fill_s, "
        "price_diff_bps, saving_bps, end_px, runaway_end_bps, runaway_max_bps, ref_px, ref_basis, data_basis) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(sig_id, x["k"], x["ttl_min"], x["limit_px"], x["outcome"], x["fill_ts"], x["time_to_fill_s"],
          x["price_diff_bps"], x["saving_bps"], x["end_px"], x["runaway_end_bps"], x["runaway_max_bps"],
          x["ref_px"], x["ref_basis"], x["data_basis"]) for x in res["results"]])
    conn.commit()
    return status


def execute_cycle(conn, job: Optional[dict] = None, market=None, now: Optional[float] = None,
                  trading_db_path: Optional[str] = None) -> dict:
    ensure_schema(conn)
    cfg = shadow_settings()
    now = now or time.time()
    path = trading_db_path if trading_db_path is not None else get_lab_settings().trading_db_path
    out: dict = {"started": iso(now)}
    rows = read_trade_logs(path)
    out["trade_log_rows"] = len(rows)
    out["sync"] = _sync(conn, group_signals(rows, cfg.tf, cfg.off_close_s), cfg.first_delay_s, now)

    tmp: Optional[str] = None
    if market is None:
        base = Path(default_cache_dir())
        base.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix="run-", dir=base)
        market = PublicMarket(cache_dir=tmp)
    counts: dict[str, int] = {}
    try:
        due = conn.execute("SELECT * FROM shadow_signals WHERE status IN ('pending','partial') AND next_due <= ? "
                           "ORDER BY arrival_ts", (iso(now),)).fetchall()
        for r in due:
            sig = _sig_input(r)
            try:
                res = evaluate(sig, market, cfg.ks, cfg.ttls_min, cfg.fee_diff_bps, int(now * 1000))
                st = _store(conn, r["id"], res, cfg, r, now)
            except Exception as e:  # noqa: BLE001 — one bad signal must not stop the rest
                log.exception("shadow: evaluating %s failed", r["key"])
                arrival = to_epoch(r["arrival_ts"])
                st = "error" if now - arrival > GIVE_UP_S else r["status"]
                conn.execute("UPDATE shadow_signals SET status=?, error=?, next_due=?, computed_at=? WHERE id=?",
                             (st, f"{type(e).__name__}: {str(e)[:200]}", None if st == "error" else iso(now + 3600),
                              utcnow(), r["id"]))
                conn.commit()
            counts[st] = counts.get(st, 0) + 1
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    out["evaluated"] = counts
    out["calls"] = getattr(market, "calls", None)
    out["finished"] = utcnow()
    kv_set(conn, "shadow_last_cycle", out)
    conn.commit()
    log.info("shadow cycle %s", out)
    return out


def execute(conn, job: dict) -> None:
    execute_cycle(conn, job)
