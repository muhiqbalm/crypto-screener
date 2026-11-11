"""Worker scheduler hook for the Outlook (stdlib only; runs in the worker's main loop).

One ``outlook_refresh`` job per closed 4H bar, queued AFTER that bar's ``universe_refresh``
job has finished (it refreshes the 4H cache and Koin Terkuat, which the outlook reads).
Disabled with LAB_OUTLOOK_REFRESH=0.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from .. import queue as q
from ..settings import REPO_ROOT, _read_dotenv
from . import JOB_KIND
from .store import BAR_KEY, kv_get, kv_set

PRIORITY = 8   # below watch_eval / universe_refresh (10), above the ledger cycle (5)


def enabled() -> bool:
    v = os.environ.get("LAB_OUTLOOK_REFRESH", _read_dotenv(REPO_ROOT / ".env").get("LAB_OUTLOOK_REFRESH", "1"))
    return v != "0"


def _busy(conn, kind: str) -> bool:
    return conn.execute("SELECT 1 FROM lab_jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",
                        (kind,)).fetchone() is not None


def enqueue_now(conn, bar: Optional[str] = None) -> int:
    jid = q.enqueue(conn, JOB_KIND, None, {"bar": bar, "manual": bar is None}, priority=PRIORITY)
    conn.commit()
    return jid


def tick(conn, s, now: Optional[float] = None) -> Optional[int]:
    from ..scheduler import last_closed_bar_open
    if not enabled():
        return None
    now = now or time.time()
    bar = last_closed_bar_open("4h", now, s.watch_delay_s)
    if kv_get(conn, BAR_KEY) == bar or _busy(conn, JOB_KIND):
        return None
    # wait for this bar's universe refresh (fresh cache + strength.json) when one is expected
    uni = conn.execute("SELECT value FROM lab_kv WHERE key='universe_refresh_bar'").fetchone()
    if _busy(conn, "universe_refresh"):
        return None
    if s.strength_refresh and (uni is None or uni["value"] != bar):
        return None
    jid = q.enqueue(conn, JOB_KIND, None, {"bar": bar}, priority=PRIORITY)
    kv_set(conn, BAR_KEY, bar)
    conn.commit()
    return jid
