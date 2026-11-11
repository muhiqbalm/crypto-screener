"""Worker scheduler hook (runs in the lab worker main loop, stdlib, never in the API).

  * weekly snapshot: from Monday 00:30 UTC, freeze the report of the week that just
    ended (once; ``weekly_reports`` is write-once). Weeks that were already over when
    this feature first ran are not back-filled: a report built days later would not be
    the record of that week. A missed Monday (worker down) is caught up on the next tick.
  * deploy log: every DEPLOY_SCAN_S, notify on new "live @" / "GAGAL:" lines.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import notify_events
from ..ledger.store import kv_get, kv_set
from ..notify import notify
from . import SNAPSHOT_AFTER_S, build, store

log = logging.getLogger("lab.weekly")

DEPLOY_SCAN_S = 120
KV_SINCE = "weekly_report_since"

_last_deploy_scan = 0.0


def due_week(conn, now: datetime) -> Optional[str]:
    """The finished week that should be snapshotted now, or None."""
    store.ensure_schema(conn)
    since = kv_get(conn, KV_SINCE)
    if since is None:
        kv_set(conn, KV_SINCE, store.iso(now))
        conn.commit()
        since = store.iso(now)
    cur_start, _ = store.bounds(store.current_week(now))
    if now < cur_start + timedelta(seconds=SNAPSHOT_AFTER_S):
        return None
    prev = store.shift(store.current_week(now), -1)
    _, prev_end = store.bounds(prev)
    if store.iso(prev_end) <= since:            # week was already over when the feature started
        return None
    if conn.execute("SELECT 1 FROM weekly_reports WHERE week=?", (prev,)).fetchone():
        return None
    return prev


def snapshot_week(conn, s, week: str, now: Optional[datetime] = None) -> bool:
    rep = build.build(conn, week, s.trading_db_path, now=now)
    rep["source"] = "snapshot"
    ok = store.save(conn, rep, "worker")
    if ok:
        log.info("weekly report %s saved", week)
        notify(conn, "report", f"Laporan mingguan {week} siap",
               f"{rep['start'][:10]} s/d {(store.bounds(week)[1] - timedelta(days=1)).date().isoformat()} (UTC)",
               f"/lab/report?week={week}", f"report:{week}")
    return ok


def tick(conn, s, now: Optional[float] = None) -> None:
    global _last_deploy_scan
    t = now or time.time()
    dt = datetime.fromtimestamp(t, tz=timezone.utc)
    store.ensure_schema(conn)
    try:
        week = due_week(conn, dt)
        if week:
            snapshot_week(conn, s, week, now=dt)
    except Exception:  # noqa: BLE001
        log.exception("weekly report snapshot failed")
    if t - _last_deploy_scan >= DEPLOY_SCAN_S:
        _last_deploy_scan = t
        notify_events.deploy_log_scan(conn)
