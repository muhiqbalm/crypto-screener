"""Worker scheduler hooks for the Outlook (stdlib only; run in the worker's main loop).

  * ``outlook_refresh``: one job per closed 4H bar, queued AFTER that bar's ``universe_refresh``
    job has finished (it refreshes the 4H cache and Koin Terkuat, which the outlook reads).
    Disabled with LAB_OUTLOOK_REFRESH=0.
  * ``outlook_calibrate`` (heavy historical replay, NOT a fast-lane kind): when no calibration
    exists or the last one is older than CALIBRATE_EVERY_DAYS, at most one attempt per day, and only
    in a quiet window (UTC hour % 4 in {1, 2}, minute 15-44: far from the 4H closes the live bot
    trades on). Disabled with LAB_OUTLOOK_CALIBRATE=0.
"""
from __future__ import annotations

import calendar
import os
import time
from typing import Optional

from .. import queue as q
from ..settings import REPO_ROOT, _read_dotenv
from . import JOB_KIND
from .store import BAR_KEY, kv_get, kv_set

PRIORITY = 8   # below watch_eval / universe_refresh (10), above the ledger cycle (5)
CALIBRATE_PRIORITY = 3
CALIBRATE_EVERY_DAYS = 7
CALIBRATE_ATTEMPT_KEY = "outlook_calibrate_attempt"


def _flag(name: str) -> bool:
    v = os.environ.get(name, _read_dotenv(REPO_ROOT / ".env").get(name, "1"))
    return v != "0"


def enabled() -> bool:
    return _flag("LAB_OUTLOOK_REFRESH")


def calibrate_enabled() -> bool:
    return _flag("LAB_OUTLOOK_CALIBRATE")


def quiet_window(now: float) -> bool:
    t = time.gmtime(now)
    return t.tm_hour % 4 in (1, 2) and 15 <= t.tm_min <= 44


def _age_days(iso: Optional[str], now: float) -> Optional[float]:
    if not iso:
        return None
    try:
        t = calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None
    return (now - t) / 86400.0


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


def calibrate_tick(conn, s=None, now: Optional[float] = None) -> Optional[int]:
    from .replay import JOB_KIND as CALIB_KIND
    from .replay import KV_KEY as CALIB_KEY
    now = now or time.time()
    if not quiet_window(now) or not calibrate_enabled() or _busy(conn, CALIB_KIND):
        return None
    cal = kv_get(conn, CALIB_KEY)
    age = _age_days((cal or {}).get("computed_at"), now)
    if age is not None and age < CALIBRATE_EVERY_DAYS:
        return None
    last = _age_days(kv_get(conn, CALIBRATE_ATTEMPT_KEY), now)
    if last is not None and last < 1.0:
        return None
    jid = q.enqueue(conn, CALIB_KIND, None, {"scheduled": True}, priority=CALIBRATE_PRIORITY)
    kv_set(conn, CALIBRATE_ATTEMPT_KEY, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)))
    conn.commit()
    return jid
