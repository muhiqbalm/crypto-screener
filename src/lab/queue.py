"""SQLite job queue: atomic claim, heartbeat, reaper, cancel."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db import dumps, loads, utcnow

MAX_ATTEMPTS = 2
TERMINAL = ("done", "error", "cancelled")


def enqueue(conn: sqlite3.Connection, kind: str, ref_id: Optional[int] = None,
            payload: Optional[dict] = None, priority: int = 0) -> int:
    cur = conn.execute(
        "INSERT INTO lab_jobs (kind, ref_id, status, priority, payload_json, created_at) "
        "VALUES (?, ?, 'queued', ?, ?, ?)",
        (kind, ref_id, priority, dumps(payload or {}), utcnow()),
    )
    return int(cur.lastrowid)


_SCAN_CELL_SQL = "(kind='run' AND ref_id IN (SELECT id FROM lab_runs WHERE scan_id IS NOT NULL))"


def claim(conn: sqlite3.Connection, worker_id: str,
          kinds: Optional[tuple[str, ...]] = None, exclude_scan_cells: bool = False) -> Optional[dict]:
    """Atomically move the next queued job to 'running'.

    The UPDATE ... WHERE id=(subselect) AND status='queued' pattern means two
    workers racing for the same row cannot both win: the loser's UPDATE
    matches zero rows.
    """
    now = utcnow()
    kind_sql, args = "", []
    if kinds:
        kind_sql = f" AND kind IN ({','.join('?' * len(kinds))})"
        args = list(kinds)
    if exclude_scan_cells:
        kind_sql += f" AND NOT {_SCAN_CELL_SQL}"
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "UPDATE lab_jobs SET status='running', worker_id=?, started_at=?, heartbeat_at=?, "
            "attempts=attempts+1 "
            "WHERE id = (SELECT id FROM lab_jobs WHERE status='queued' AND cancel_requested=0"
            f"{kind_sql} ORDER BY priority DESC, id ASC LIMIT 1) AND status='queued' "
            "RETURNING *",
            [worker_id, now, now, *args],
        ).fetchone()
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    if row is None:
        return None
    job = dict(row)
    _sync_run_status(conn, job, "running")
    conn.commit()
    return job


def heartbeat(conn: sqlite3.Connection, job_id: int, worker_id: str,
              progress: Optional[dict] = None, pid: Optional[int] = None) -> bool:
    """Refresh heartbeat. Returns False when the job was cancelled or lost."""
    sets, args = ["heartbeat_at=?"], [utcnow()]
    if progress is not None:
        sets.append("progress_json=?")
        args.append(dumps(progress))
    if pid is not None:
        sets.append("pid=?")
        args.append(pid)
    cur = conn.execute(
        f"UPDATE lab_jobs SET {', '.join(sets)} WHERE id=? AND worker_id=? AND status='running'",
        [*args, job_id, worker_id],
    )
    conn.commit()
    if cur.rowcount == 0:
        return False
    row = conn.execute("SELECT cancel_requested FROM lab_jobs WHERE id=?", (job_id,)).fetchone()
    return not (row and row["cancel_requested"])


def set_progress(conn: sqlite3.Connection, job_id: int, progress: dict) -> None:
    conn.execute("UPDATE lab_jobs SET progress_json=?, heartbeat_at=? WHERE id=? AND status='running'",
                 (dumps(progress), utcnow(), job_id))
    conn.commit()


def finish(conn: sqlite3.Connection, job_id: int, status: str, error: Optional[str] = None) -> None:
    assert status in TERMINAL
    conn.execute(
        "UPDATE lab_jobs SET status=?, error=?, finished_at=? WHERE id=? AND status NOT IN "
        "('done','error','cancelled')",
        (status, (error or None) and error[:4000], utcnow(), job_id),
    )
    job = conn.execute("SELECT * FROM lab_jobs WHERE id=?", (job_id,)).fetchone()
    if job is not None:
        _sync_run_status(conn, dict(job), job["status"], job["error"])
    conn.commit()
    if job is not None:
        from .notify_events import job_finished  # in-web notification; never raises
        job_finished(conn, dict(job))


def request_cancel(conn: sqlite3.Connection, job_id: int) -> Optional[str]:
    """Queued jobs are cancelled at once; running ones are flagged for the worker."""
    row = conn.execute("SELECT * FROM lab_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    if row["status"] == "queued":
        cur = conn.execute("UPDATE lab_jobs SET status='cancelled', cancel_requested=1, finished_at=? "
                           "WHERE id=? AND status='queued'", (utcnow(), job_id))
        if cur.rowcount:
            _sync_run_status(conn, dict(row), "cancelled")
        else:  # claimed by a worker in the meantime: flag it like a running job
            conn.execute("UPDATE lab_jobs SET cancel_requested=1 WHERE id=? AND status='running'", (job_id,))
    elif row["status"] == "running":
        conn.execute("UPDATE lab_jobs SET cancel_requested=1 WHERE id=?", (job_id,))
    conn.commit()
    return conn.execute("SELECT status FROM lab_jobs WHERE id=?", (job_id,)).fetchone()["status"]


def is_scan_cell(conn: sqlite3.Connection, job: dict) -> bool:
    if job.get("kind") != "run" or job.get("ref_id") is None:
        return False
    row = conn.execute("SELECT scan_id FROM lab_runs WHERE id=?", (job["ref_id"],)).fetchone()
    return bool(row and row["scan_id"] is not None)


def cancel_scan(conn: sqlite3.Connection, scan_id: int) -> dict:
    """Cancel every unfinished cell of a scan: queued at once, running flagged for the worker."""
    jobs = conn.execute(
        "SELECT j.id, j.status FROM lab_jobs j JOIN lab_runs r ON r.id = j.ref_id "
        "WHERE j.kind='run' AND r.scan_id=? AND j.status IN ('queued','running')", (scan_id,)).fetchall()
    out = {"cancelled": 0, "cancelling": 0}
    for j in jobs:
        st = request_cancel(conn, j["id"])
        if st == "cancelled":
            out["cancelled"] += 1
        elif st == "running":
            out["cancelling"] += 1
    return out


def reap(conn: sqlite3.Connection, stale_after_s: int, now: Optional[datetime] = None) -> list[int]:
    """Requeue (or fail after MAX_ATTEMPTS) running jobs whose heartbeat is stale."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=stale_after_s)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale = conn.execute(
        "SELECT * FROM lab_jobs WHERE status='running' AND (heartbeat_at IS NULL OR heartbeat_at < ?)",
        (cutoff,),
    ).fetchall()
    reaped = []
    for job in stale:
        if job["cancel_requested"]:
            new_status, err = "cancelled", "cancelled (worker lost)"
        elif job["attempts"] < MAX_ATTEMPTS:
            new_status, err = "queued", None
        else:
            new_status, err = "error", "worker heartbeat lost (reaped)"
        cur = conn.execute(
            "UPDATE lab_jobs SET status=?, error=?, worker_id=NULL, pid=NULL, "
            "finished_at=CASE WHEN ?='queued' THEN NULL ELSE ? END "
            "WHERE id=? AND status='running' AND heartbeat_at IS ?",
            (new_status, err, new_status, utcnow(), job["id"], job["heartbeat_at"]),
        )
        if cur.rowcount:
            reaped.append(job["id"])
            _sync_run_status(conn, dict(job), new_status, err)
    conn.commit()
    if reaped:
        from .notify_events import job_finished  # in-web notification; never raises
        for jid in reaped:
            row = conn.execute("SELECT * FROM lab_jobs WHERE id=?", (jid,)).fetchone()
            if row is not None and row["status"] != "queued":
                job_finished(conn, dict(row))
    return reaped


def get_job(conn: sqlite3.Connection, job_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM lab_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["progress"] = loads(d.pop("progress_json", None))
    return d


def _sync_run_status(conn: sqlite3.Connection, job: dict, status: str,
                     error: Optional[str] = None) -> None:
    """Mirror job status onto lab_runs (runs are what the UI lists)."""
    if job.get("kind") != "run" or job.get("ref_id") is None:
        return
    if status in TERMINAL:
        conn.execute(
            "UPDATE lab_runs SET status=?, error=COALESCE(?, error), finished_at=COALESCE(finished_at, ?) "
            "WHERE id=? AND status NOT IN ('done','error','cancelled')",
            (status, error, utcnow(), job["ref_id"]),
        )
    else:
        conn.execute("UPDATE lab_runs SET status=? WHERE id=? AND status NOT IN "
                     "('done','error','cancelled')", (status, job["ref_id"]))
