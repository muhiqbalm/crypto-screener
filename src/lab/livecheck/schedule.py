"""Worker scheduler hook for the live check (stdlib; runs in the worker main loop).

Enqueues one ``livecheck_cycle`` (fast lane) ``delay_s`` after every 4H close, plus an
hourly catch-up (log lines and trade_logs rows that arrived late, a failed run). The
first tick on a fresh lab.db runs it right away.
"""
from __future__ import annotations

import time
from typing import Optional

from .. import queue as q
from ..ledger.store import iso, kv_get, kv_set
from . import JOB_KIND
from .store import livecheck_settings

PRIORITY = 5
STEP = 14400


def tick(conn, s=None, now: Optional[float] = None) -> list[int]:
    cfg = livecheck_settings()
    if not cfg.enabled:
        return []
    now = now or time.time()
    if conn.execute("SELECT 1 FROM lab_jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",
                    (JOB_KIND,)).fetchone():
        return []
    t = now - cfg.delay_s
    bar = iso(t - t % STEP)              # newest 4H close at least delay_s ago
    hour = iso(now - now % 3600)
    reason = None
    if kv_get(conn, "livecheck_bar") != bar:
        reason = "4h_close"
    elif kv_get(conn, "livecheck_hour") != hour:
        reason = "hourly"
    if not reason:
        return []
    jid = q.enqueue(conn, JOB_KIND, None, {"reason": reason, "bar_close": bar}, priority=PRIORITY)
    kv_set(conn, "livecheck_bar", bar)
    kv_set(conn, "livecheck_hour", hour)
    conn.commit()
    return [jid]
