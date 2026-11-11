"""Worker scheduler hook: one ``arena_snapshot`` job (fast lane) per closed hour.

Skipped while one is queued/running, and when there is no paper account yet.
"""
from __future__ import annotations

import time
from typing import Optional

from .. import queue as q
from ..ledger.store import iso, kv_get, kv_set
from . import JOB_KIND

PRIORITY = 3          # just below the ledger (5) and shadow (4) cycles: a snapshot is never urgent


def tick(conn, s=None, now: Optional[float] = None) -> Optional[int]:
    now = now or time.time()
    hour = iso(now - now % 3600)
    if kv_get(conn, "arena_snapshot_hour") == hour:
        return None
    if not conn.execute("SELECT 1 FROM paper_accounts LIMIT 1").fetchone():
        return None
    if conn.execute("SELECT 1 FROM lab_jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",
                    (JOB_KIND,)).fetchone():
        return None
    jid = q.enqueue(conn, JOB_KIND, None, {"hour": hour}, priority=PRIORITY)
    kv_set(conn, "arena_snapshot_hour", hour)
    conn.commit()
    return jid
