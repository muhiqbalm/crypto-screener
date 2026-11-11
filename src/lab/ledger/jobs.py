"""Ledger job bodies, run by ``src.lab.runner`` in a child process started with the
SCREENER venv interpreter (the screener pipeline needs pydantic-settings + ccxt).

  ledger_cycle     hourly: live screener snapshot, collect watch/universal/webhook
                   signals, fill outcomes whose horizons have closed
  ledger_backfill  one-off: causal reconstruction of the screener over the last
                   LAB_LEDGER_BACKFILL_DAYS days, then scoring
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .. import queue as q
from ..db import loads, utcnow
from ..settings import get_lab_settings
from . import binance
from .collect import collect_all
from .scoring import score_pending
from .screener import fetch_history, live_snapshot, reconstruct
from .store import ensure_schema, iso, kv_set, ledger_settings, norm_symbol

log = logging.getLogger("lab.ledger.jobs")


def _err(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


def execute_cycle(conn, job: dict, processor=None, fetch=None) -> dict:
    ensure_schema(conn)
    payload = loads(job.get("payload_json"), {}) or {}
    bar = payload.get("bar") or iso(time.time() - time.time() % 3600)
    started = iso(time.time())
    out: dict = {"bar": bar, "started": started}
    try:
        out["screener"] = live_snapshot(conn, bar, ts=started, processor=processor)
    except Exception as e:  # noqa: BLE001
        log.exception("ledger: screener snapshot failed")
        out["screener"] = _err(e)
    out["collect"] = collect_all(conn, get_lab_settings().trading_db_path)
    try:
        out["score"] = score_pending(conn, fetch or binance.klines_15m)
    except Exception as e:  # noqa: BLE001
        log.exception("ledger: scoring failed")
        out["score"] = _err(e)
    out["finished"] = utcnow()
    kv_set(conn, "ledger_last_cycle", out)
    conn.commit()
    from ..notify_events import ledger_verdicts  # in-web notification on a verdict change; never raises
    ledger_verdicts(conn)
    log.info("ledger cycle %s", out)
    return out


def _screener_symbols() -> list[str]:
    from src.config.settings import Settings
    return [norm_symbol(s) for s in Settings().symbols_list]


def execute_backfill(conn, job: dict, api=None, fetch=None, symbols: Optional[list[str]] = None,
                     now: Optional[float] = None) -> dict:
    ensure_schema(conn)
    payload = loads(job.get("payload_json"), {}) or {}
    days = int(payload.get("days") or ledger_settings().backfill_days)
    now = now or time.time()
    end_s = int(now - now % 3600)                 # last closed hour
    start_s = end_s - days * 86400 + 3600
    symbols = symbols or _screener_symbols()
    state = {"status": "running", "days": days, "started": utcnow(), "from": iso(start_s), "to": iso(end_s)}
    kv_set(conn, "ledger_backfill", state)
    conn.commit()

    def prog(stage, done=0, total=0):
        q.set_progress(conn, job["id"], {"stage": stage, "done": done, "total": total})

    try:
        hist = fetch_history(symbols, start_s, end_s, api=api, progress=prog)
        res = reconstruct(conn, symbols, start_s, end_s, hist, progress=prog)
        prog("score", 0, 0)
        score = score_pending(conn, fetch or binance.klines_15m, sleep_s=0.05)
    except Exception as e:
        kv_set(conn, "ledger_backfill", {**state, "status": "error", **_err(e), "finished": utcnow()})
        conn.commit()
        raise
    state.update(status="done", finished=utcnow(), coins=len(hist), hours=res["hours"], signals=res["events"],
                 score=score)
    kv_set(conn, "ledger_backfill", state)
    conn.commit()
    return state


def execute(conn, job: dict) -> None:
    if job["kind"] == "ledger_cycle":
        execute_cycle(conn, job)
    elif job["kind"] == "ledger_backfill":
        execute_backfill(conn, job)
    else:
        raise ValueError(f"unknown ledger job kind {job['kind']}")

