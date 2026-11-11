"""Worker scheduler hook for shadow execution (stdlib; runs in the worker main loop).

Enqueues one ``shadow_cycle`` (fast lane) when
  * trade_logs changed (row count / newest created_at; short read-only query), or
  * a recorded signal is due (first look ~3 min after the alert, then as each
    time-to-live window closes), or
  * once per hour as a catch-up.
The first tick on a fresh lab.db sees "changed" and so runs the backfill.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from .. import queue as q
from ..ledger.store import iso, kv_get, kv_set
from . import JOB_KIND
from .store import ensure_schema, shadow_settings

PRIORITY = 4          # just below the ledger cycle


def source_mark(trading_db_path: str) -> Optional[list]:
    if not trading_db_path or not Path(trading_db_path).exists():
        return None
    src = sqlite3.connect(f"file:{trading_db_path}?mode=ro", uri=True, timeout=1.0)
    try:
        src.execute("PRAGMA query_only=1")
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_logs'").fetchone():
            return None
        n, last = src.execute("SELECT COUNT(*), MAX(created_at) FROM trade_logs").fetchone()
        return [n, last]
    finally:
        src.close()


def tick(conn, s, now: Optional[float] = None) -> list[int]:
    cfg = shadow_settings()
    if not cfg.enabled:
        return []
    ensure_schema(conn)
    now = now or time.time()
    if conn.execute("SELECT 1 FROM lab_jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",
                    (JOB_KIND,)).fetchone():
        return []
    try:
        mark = source_mark(s.trading_db_path)
    except sqlite3.Error:
        mark = kv_get(conn, "shadow_src_mark")          # trading DB busy: try again next tick
    hour = iso(now - now % 3600)
    reason = None
    if mark != kv_get(conn, "shadow_src_mark"):
        reason = "trade_logs"
    elif conn.execute("SELECT 1 FROM shadow_signals WHERE status IN ('pending','partial') AND next_due <= ? LIMIT 1",
                      (iso(now),)).fetchone():
        reason = "due"
    elif kv_get(conn, "shadow_cycle_hour") != hour:
        reason = "hourly"
    if not reason:
        return []
    jid = q.enqueue(conn, JOB_KIND, None, {"reason": reason}, priority=PRIORITY)
    kv_set(conn, "shadow_src_mark", mark)
    kv_set(conn, "shadow_cycle_hour", hour)
    conn.commit()
    return [jid]
