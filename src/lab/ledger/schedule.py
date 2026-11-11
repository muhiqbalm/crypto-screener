"""Worker scheduler hook for the ledger (stdlib only; runs in the worker's main loop).

  * one ``ledger_cycle`` job per closed hour (fast lane, so a long optimise run can't
    starve it)
  * one ``ledger_backfill`` job, once per lab.db (LAB_LEDGER_BACKFILL_DAYS > 0)

The jobs themselves run in child processes; this only enqueues.
"""
from __future__ import annotations

import time
from typing import Optional

from .. import queue as q
from .store import ensure_schema, iso, kv_get, kv_set, ledger_settings, to_epoch

CYCLE_PRIORITY = 5        # below watch_eval / universe_refresh (10): they matter more right after a 4H close
BACKFILL_PRIORITY = -5


def _busy(conn, kind: str) -> bool:
    return conn.execute("SELECT 1 FROM lab_jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",
                        (kind,)).fetchone() is not None


def tick(conn, s, now: Optional[float] = None) -> list[int]:
    from ..scheduler import last_closed_bar_open
    cfg = ledger_settings()
    if not cfg.enabled:
        return []
    ensure_schema(conn)
    now = now or time.time()
    queued: list[int] = []
    bar = iso(to_epoch(last_closed_bar_open("1h", now, s.watch_delay_s)) + 3600)   # hour CLOSE time
    if kv_get(conn, "ledger_cycle_bar") != bar and not _busy(conn, "ledger_cycle"):
        queued.append(q.enqueue(conn, "ledger_cycle", None, {"bar": bar}, priority=CYCLE_PRIORITY))
        kv_set(conn, "ledger_cycle_bar", bar)
        conn.commit()
    if cfg.backfill_days > 0 and kv_get(conn, "ledger_backfill") is None and not _busy(conn, "ledger_backfill"):
        queued.append(q.enqueue(conn, "ledger_backfill", None, {"days": cfg.backfill_days},
                                priority=BACKFILL_PRIORITY))
        kv_set(conn, "ledger_backfill", {"status": "queued", "days": cfg.backfill_days, "queued_at": iso(now)})
        conn.commit()
    return queued
