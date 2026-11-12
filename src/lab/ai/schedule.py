"""Worker scheduler hook for Ringkasan AI (stdlib; runs in the worker main loop, every 30 s).

Queues one ``ai_factor_summary`` job per Outlook bar, once that bar's outlook_refresh has
finished (lab_kv 'outlook_meta'.last_bar moved on and no outlook job is queued/running).
Nothing is queued while the feature is off (no key / LAB_AI_ENABLED=0 / no SDK), while
today's spend has reached the cap (the bar is picked up after 00:00 UTC if still current),
or when the Outlook data is stale.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from .. import queue as q
from ..outlook import logic as L
from ..outlook import store as S
from . import JOB_KIND, store
from .config import ai_config, off_reason

PRIORITY = 4          # below every other fast-lane kind (watch_eval / universe 10, outlook 8, ledger 5)
BAR_KEY = "ai_factor_bar"


def _busy(conn, kind: str) -> bool:
    return conn.execute("SELECT 1 FROM lab_jobs WHERE kind=? AND status IN ('queued','running') LIMIT 1",
                        (kind,)).fetchone() is not None


def tick(conn, s=None, now: Optional[float] = None) -> Optional[int]:
    cfg = ai_config()
    if off_reason(cfg):
        return None
    now = now or time.time()
    meta = S.kv_get(conn, S.META_KEY) or {}
    bar = meta.get("last_bar")
    if not bar or S.kv_get(conn, BAR_KEY) == bar:
        return None
    from ..outlook import JOB_KIND as OUTLOOK_KIND
    if _busy(conn, OUTLOOK_KIND) or _busy(conn, JOB_KIND):
        return None
    try:
        opened = datetime.strptime(str(bar)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    if (now - opened - 4 * 3600) / 3600.0 > L.STALE_HOURS:      # hours since the 4H close
        return None
    if store.spent_today(conn, datetime.fromtimestamp(now, tz=timezone.utc)) >= cfg.daily_budget_usd:
        return None
    jid = q.enqueue(conn, JOB_KIND, None, {"bar": bar}, priority=PRIORITY)
    S.kv_set(conn, BAR_KEY, bar)
    conn.commit()
    return jid
