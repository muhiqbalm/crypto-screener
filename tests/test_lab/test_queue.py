from datetime import datetime, timedelta, timezone

from src.lab import db, queue as q


def _run(conn):
    rid = conn.execute(
        "INSERT INTO lab_runs (template_id, symbol, timeframe, mode, params_json, costs_json, created_at) "
        "VALUES ('rosyade_family','ETHUSDT','4h','backtest','{}','{}',?)", (db.utcnow(),)).lastrowid
    jid = q.enqueue(conn, "run", rid)
    conn.commit()
    return rid, jid


def test_claim_is_exclusive(conn, lab_env):
    _run(conn)
    other = db.connect()
    try:
        a = q.claim(conn, "w1")
        b = q.claim(other, "w2")
    finally:
        other.close()
    assert a is not None and a["status"] == "running" and a["worker_id"] == "w1"
    assert b is None


def test_claim_order_priority_then_fifo(conn):
    _, j1 = _run(conn)
    _, j2 = _run(conn)
    hi = q.enqueue(conn, "watch_eval", 1, priority=10)
    conn.commit()
    assert q.claim(conn, "w")["id"] == hi
    assert q.claim(conn, "w")["id"] == j1
    assert q.claim(conn, "w")["id"] == j2
    assert q.claim(conn, "w") is None


def test_claim_mirrors_run_status_and_finish(conn):
    rid, jid = _run(conn)
    q.claim(conn, "w")
    assert conn.execute("SELECT status FROM lab_runs WHERE id=?", (rid,)).fetchone()[0] == "running"
    q.finish(conn, jid, "error", "boom")
    row = conn.execute("SELECT status, error FROM lab_runs WHERE id=?", (rid,)).fetchone()
    assert tuple(row) == ("error", "boom")
    # terminal jobs are not resurrected
    q.finish(conn, jid, "done")
    assert q.get_job(conn, jid)["status"] == "error"


def test_heartbeat_and_cancel_running(conn):
    _, jid = _run(conn)
    q.claim(conn, "w")
    assert q.heartbeat(conn, jid, "w", progress={"stage": "x"}) is True
    assert q.get_job(conn, jid)["progress"] == {"stage": "x"}
    assert q.heartbeat(conn, jid, "other-worker") is False
    assert q.request_cancel(conn, jid) == "running"
    assert q.heartbeat(conn, jid, "w") is False  # tells the worker to kill the child


def test_cancel_queued_is_immediate(conn):
    rid, jid = _run(conn)
    assert q.request_cancel(conn, jid) == "cancelled"
    assert conn.execute("SELECT status FROM lab_runs WHERE id=?", (rid,)).fetchone()[0] == "cancelled"
    assert q.claim(conn, "w") is None
    assert q.request_cancel(conn, 9999) is None


def test_reaper_requeues_then_fails(conn):
    rid, jid = _run(conn)
    q.claim(conn, "w")
    later = datetime.now(timezone.utc) + timedelta(seconds=600)
    assert q.reap(conn, 120, now=later) == [jid]
    assert q.get_job(conn, jid)["status"] == "queued"
    assert conn.execute("SELECT status FROM lab_runs WHERE id=?", (rid,)).fetchone()[0] == "queued"
    q.claim(conn, "w")  # attempt 2
    assert q.reap(conn, 120, now=later) == [jid]
    j = q.get_job(conn, jid)
    assert j["status"] == "error" and "heartbeat" in j["error"]


def test_reaper_ignores_fresh_jobs(conn):
    _, jid = _run(conn)
    q.claim(conn, "w")
    assert q.reap(conn, 120) == []
    assert q.get_job(conn, jid)["status"] == "running"


def test_db_is_wal(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
