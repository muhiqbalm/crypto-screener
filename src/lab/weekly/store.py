"""``weekly_reports`` in lab.db: one frozen snapshot per ISO week (stdlib)."""
from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..db import dumps, loads, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS weekly_reports (
    week          TEXT PRIMARY KEY,              -- 2026-W46
    start_at      TEXT NOT NULL,                 -- Monday 00:00 UTC
    end_at        TEXT NOT NULL,                 -- next Monday 00:00 UTC (exclusive)
    data_json     TEXT NOT NULL,
    generator     TEXT NOT NULL,                 -- worker | manual
    generated_at  TEXT NOT NULL
);
-- A snapshot is the record of that week: never rewritten.
CREATE TRIGGER IF NOT EXISTS weekly_reports_immutable
BEFORE UPDATE ON weekly_reports
BEGIN
    SELECT RAISE(ABORT, 'weekly report snapshots are immutable');
END;
"""

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
_lock = threading.Lock()


def ensure_schema(conn) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='weekly_reports'").fetchone():
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


# ── ISO week helpers (UTC) ────────────────────────────────────────────────

def week_id(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def parse_week(week: str) -> date:
    """'2026-W46' -> Monday of that week. ValueError on bad input."""
    m = WEEK_RE.match(week or "")
    if not m:
        raise ValueError("week must look like 2026-W46")
    return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)


def bounds(week: str) -> tuple[datetime, datetime]:
    mon = parse_week(week)
    start = datetime(mon.year, mon.month, mon.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def current_week(now: Optional[datetime] = None) -> str:
    return week_id((now or datetime.now(timezone.utc)).date())


def shift(week: str, n: int) -> str:
    return week_id(parse_week(week) + timedelta(days=7 * n))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── snapshots ─────────────────────────────────────────────────────────────

def get(conn, week: str) -> Optional[dict]:
    ensure_schema(conn)
    r = conn.execute("SELECT data_json, generator, generated_at FROM weekly_reports WHERE week=?", (week,)).fetchone()
    if r is None:
        return None
    data = loads(r["data_json"], {}) or {}
    data["snapshot"] = {"generator": r["generator"], "generated_at": r["generated_at"]}
    return data


def save(conn, report: dict, generator: str = "worker") -> bool:
    """Write-once. Returns False when the week already has a snapshot."""
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT OR IGNORE INTO weekly_reports (week, start_at, end_at, data_json, generator, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (report["week"], report["start"], report["end"], dumps(report), generator, utcnow()))
    conn.commit()
    return cur.rowcount > 0


def listing(conn) -> list[dict]:
    ensure_schema(conn)
    return [dict(r) for r in conn.execute(
        "SELECT week, start_at, end_at, generator, generated_at FROM weekly_reports ORDER BY week DESC")]
