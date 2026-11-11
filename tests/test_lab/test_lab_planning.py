"""Runtime estimates, per-type timeouts, scan concurrency, queue ETA, scan cancel, leaderboard."""
import dataclasses
import json
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

from src.lab import db, insights, queue as q
from src.lab import settings as lab_settings
from tests.test_lab.test_lab_api import RUN, client_for  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


# ── settings ─────────────────────────────────────────────────────────────

def test_parse_timeouts_and_timeout_for(lab_env, monkeypatch):
    assert lab_settings.parse_timeouts("optimize=100, validate=50,bad,x=,y=abc,z=-1") == \
        {"optimize": 100, "validate": 50}
    s = lab_settings.get_lab_settings()
    assert s.timeout_for("run", "optimize") == 5 * 3600     # built-in
    assert s.timeout_for("run", "backtest") == 3600         # built-in
    assert s.timeout_for("run", "validate") == s.job_timeout_s == 3 * 3600
    assert s.timeout_for("watch_eval") == 3 * 3600
    monkeypatch.setenv("LAB_JOB_TIMEOUTS", "validate=7200,watch_eval=600,run=999")
    lab_settings.get_lab_settings.cache_clear()
    s = lab_settings.get_lab_settings()
    assert s.timeout_for("run", "validate") == 7200
    assert s.timeout_for("watch_eval") == 600
    assert s.timeout_for("run", None) == 999                 # kind key when mode unknown
    assert s.timeout_for("run", "optimize") == 5 * 3600     # mode beats kind
    assert s.scan_max_concurrent == 1 and s.max_load_per_cpu == 0.75


# ── estimate model ───────────────────────────────────────────────────────

def _mins(mode, tf, start, n=None):
    bars = insights.eval_bars(tf, start, None, now=NOW)
    return insights.base_seconds(mode, tf, bars, n) / 60


def test_estimate_matches_measured_rates():
    # measured on production, ETH, 2024 -> now: 15m 16 min, 30m 8 min, 1h 4 min
    assert 14 <= _mins("validate", "15m", "2024-01-01") <= 18
    assert 7 <= _mins("validate", "30m", "2024-01-01") <= 9
    assert 3.5 <= _mins("validate", "1h", "2024-01-01") <= 4.6
    assert 35 <= _mins("validate", "15m", "2020-01-01") <= 45          # "about 40 min"
    assert 90 <= _mins("optimize", "15m", "2024-01-01", 60) <= 130     # "1.5 - 2 h"
    assert 8 <= _mins("optimize", "4h", "2020-01-01", 60) <= 20        # old FE table: 15 min
    assert _mins("backtest", "4h", "2023-01-01") < 1


def test_tf_defaults_keep_low_tf_jobs_short():
    d = insights.run_defaults(date(2026, 11, 11))
    assert d["15m"] == {"start": "2024-11-11", "n_trials": 10, "reason": d["15m"]["reason"]}
    assert d["30m"]["start"] == "2023-11-11" and d["4h"]["start"] == "2020-01-01"
    for tf, v in d.items():
        bars = insights.eval_bars(tf, v["start"], None, now=NOW)
        assert insights.base_seconds("validate", tf, bars) < 20 * 60, tf
        assert insights.base_seconds("optimize", tf, bars, v["n_trials"]) < 45 * 60, tf


def test_eval_bars_respects_data_first_and_end():
    full = insights.eval_bars("1d", "2020-01-01", "2021-01-01", now=NOW)
    assert full == 366
    assert insights.eval_bars("1d", "2020-01-01", "2021-01-01", data_first="2020-07-01T00:00:00+00:00",
                              now=NOW) == 184
    assert insights.eval_bars("1d", "2030-01-01", None, now=NOW) == 0


def _done_run(conn, mode="validate", tf="1h", minutes=10.0, bars=25000, verdict="PASS", symbol="ETHUSDT",
              oos=None, scan_id=None, trials_done=None, template="rosyade_family"):
    now = db.utcnow()
    rid = conn.execute(
        "INSERT INTO lab_runs (template_id, symbol, timeframe, mode, status, params_json, costs_json, metrics_json,"
        " oos_metrics_json, checks_json, verdict, scan_id, trials_done, created_at) "
        "VALUES (?, ?, ?, ?, 'done', '{}', '{}', ?, ?, ?, ?, ?, ?, ?)",
        (template, symbol, tf, mode, json.dumps({"data": {"bars": bars}, "profit_factor": 2.0}),
         json.dumps(oos if oos is not None else {"profit_factor": 1.5, "sharpe": 1.0, "net_return_pct": 10.0,
                                                  "trades": 40, "costs": {"cost_drag_pct": 3.0}}),
         json.dumps([{"name": "oos_profit_factor", "passed": verdict == "PASS"}]), verdict, scan_id,
         trials_done, now)).lastrowid
    a = datetime(2026, 1, 1, tzinfo=timezone.utc)
    b = a + timedelta(minutes=minutes)
    jid = conn.execute(
        "INSERT INTO lab_jobs (kind, ref_id, status, created_at, started_at, finished_at) "
        "VALUES ('run', ?, 'done', ?, ?, ?)", (rid, now, a.isoformat(), b.isoformat())).lastrowid
    conn.execute("UPDATE lab_runs SET job_id=? WHERE id=?", (jid, rid))
    conn.commit()
    return rid


def test_calibration_scales_to_history(conn):
    pred = insights.base_seconds("validate", "1h", 25000) / 60
    for _ in range(3):
        _done_run(conn, minutes=pred * 2)
    cal = insights.calibration(conn)
    assert cal["validate"] == pytest.approx(2.0, rel=0.01)
    est = insights.Estimator(conn, {"ETHUSDT_1h": {"first": "2020-01-01T00:00:00+00:00"}})
    e = est.seconds("validate", "ETHUSDT", "1h", "2024-01-01", None)
    assert e["cached"] is True and e["seconds"] > insights.base_seconds("validate", "1h", e["bars"]) * 1.9
    # unknown dataset adds the download time
    assert est.seconds("validate", "XRPUSDT", "1h", "2024-01-01", None)["cached"] is False


# ── queue snapshot ───────────────────────────────────────────────────────

def _queued_run(conn, mode="validate", tf="1h", scan_id=None, priority=0, start="2024-01-01"):
    rid = conn.execute(
        "INSERT INTO lab_runs (template_id, symbol, timeframe, mode, status, start_date, params_json, costs_json,"
        " scan_id, created_at) VALUES ('rosyade_family','ETHUSDT',?,?,'queued',?,'{}','{}',?,?)",
        (tf, mode, start, scan_id, db.utcnow())).lastrowid
    jid = q.enqueue(conn, "run", rid, priority=priority)
    conn.execute("UPDATE lab_runs SET job_id=? WHERE id=?", (jid, rid))
    conn.commit()
    return rid, jid


def test_queue_snapshot_positions_and_scan_cap(conn):
    est = insights.Estimator(conn, {})
    _, j1 = _queued_run(conn, scan_id=1, priority=-1)
    _, j2 = _queued_run(conn, scan_id=1, priority=-1)
    _, j3 = _queued_run(conn)  # single run: priority 0, jumps the scan
    snap = insights.queue_snapshot(conn, est, slots=2, scan_cap=1)
    by = {j["job_id"]: j for j in snap["jobs"]}
    assert [by[j]["position"] for j in (j3, j1, j2)] == [1, 2, 3]
    assert by[j3]["eta_start_s"] == 0 and by[j1]["eta_start_s"] == 0
    # second scan cell waits for the first (cap 1) even though a slot frees earlier
    assert by[j2]["eta_start_s"] == by[j1]["eta_done_s"]
    snap2 = insights.queue_snapshot(conn, est, slots=2, scan_cap=2)
    by2 = {j["job_id"]: j for j in snap2["jobs"]}
    assert by2[j2]["eta_start_s"] == by2[j3]["eta_done_s"]
    assert snap["backlog_s"] == max(j["eta_done_s"] for j in snap["jobs"])


def test_queue_snapshot_running_uses_progress(conn):
    est = insights.Estimator(conn, {})
    _, jid = _queued_run(conn)
    q.claim(conn, "w")
    started = datetime.now(timezone.utc) - timedelta(seconds=100)
    conn.execute("UPDATE lab_jobs SET started_at=?, progress_json=? WHERE id=?",
                 (started.isoformat(), json.dumps({"done": 50, "total": 100}), jid))
    conn.commit()
    j = insights.queue_snapshot(conn, est, 1, 1)["jobs"][0]
    assert j["status"] == "running" and j["position"] is None
    assert 90 <= j["remaining_s"] <= 110 and j["eta_start_s"] == 0


# ── worker: scan cap, per-type timeout, load guard ───────────────────────

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def _worker(**kw):
    from src.lab.worker import Worker
    s = dataclasses.replace(lab_settings.get_lab_settings(), **kw)
    return Worker(settings=s, command=SLEEP)


def _stop(w):
    for r in list(w.running.values()):
        w._kill(r, "test")


def test_worker_scan_cap_leaves_a_slot_for_single_runs(conn):
    _, a = _queued_run(conn, scan_id=7, priority=-1)
    _, b = _queued_run(conn, scan_id=7, priority=-1)
    w = _worker(max_concurrent_jobs=2, scan_max_concurrent=1, max_load_per_cpu=1000.0)
    try:
        w.tick(conn)
        assert list(w.running) == [a]                     # 2nd scan cell held back
        _, single = _queued_run(conn)
        w.tick(conn)
        assert sorted(w.running) == sorted([a, single])
        assert q.get_job(conn, b)["status"] == "queued"
    finally:
        _stop(w)


def test_worker_load_guard_only_blocks_extra_jobs(conn, monkeypatch):
    import os
    monkeypatch.setattr(os, "getloadavg", lambda: (99.0, 99.0, 99.0))
    _, a = _queued_run(conn)
    _, b = _queued_run(conn)
    w = _worker(max_concurrent_jobs=2, max_load_per_cpu=0.75)
    try:
        w.tick(conn)
        assert list(w.running) == [a]   # the first heavy job still starts
        assert q.get_job(conn, b)["status"] == "queued"
    finally:
        _stop(w)


def test_worker_per_type_timeout(conn):
    _, jid = _queued_run(conn, mode="backtest")
    w = _worker(job_timeouts={"backtest": 1}, heartbeat_s=0)
    try:
        w.tick(conn)
        assert w.running[jid].timeout_s == 1
        w.running[jid].started -= 5
        w.tick(conn)
        import time
        for _ in range(50):
            w.tick(conn)
            if jid not in w.running:
                break
            time.sleep(0.1)
        j = q.get_job(conn, jid)
        assert j["status"] == "error" and "timeout after 1s" in j["error"]
    finally:
        _stop(w)


def test_worker_cancel_running_kills_child(conn):
    import time
    rid, jid = _queued_run(conn)
    w = _worker(heartbeat_s=0)
    try:
        w.tick(conn)
        assert q.request_cancel(conn, jid) == "running"
        for _ in range(50):
            w.tick(conn)
            if jid not in w.running:
                break
            time.sleep(0.1)
        assert q.get_job(conn, jid)["status"] == "cancelled"
        assert conn.execute("SELECT status FROM lab_runs WHERE id=?", (rid,)).fetchone()[0] == "cancelled"
    finally:
        _stop(w)


def test_cancel_queued_that_was_just_claimed_does_not_mark_run_cancelled(conn, monkeypatch):
    rid, jid = _queued_run(conn)
    stale = dict(q.get_job(conn, jid))
    q.claim(conn, "w")                              # worker wins the race
    real = conn.execute

    class C:  # first SELECT returns the stale 'queued' row
        def __init__(self):
            self.first = True

        def __call__(self, sql, *a):
            if self.first and sql.startswith("SELECT * FROM lab_jobs WHERE id=?"):
                self.first = False

                class R:
                    def fetchone(_s):
                        return stale
                return R()
            return real(sql, *a)

    class Proxy:
        def __init__(self, c):
            self._c, self.execute = c, C()

        def __getattr__(self, k):
            return getattr(self._c, k)

    st = q.request_cancel(Proxy(conn), jid)
    assert st == "running"
    assert q.get_job(conn, jid)["cancel_requested"] == 1
    assert conn.execute("SELECT status FROM lab_runs WHERE id=?", (rid,)).fetchone()[0] == "running"


def test_cancel_scan_cancels_queued_and_flags_running(conn):
    _, a = _queued_run(conn, scan_id=3, priority=-1)
    _, b = _queued_run(conn, scan_id=3, priority=-1)
    _, other = _queued_run(conn)
    q.claim(conn, "w", kinds=None)  # claims `other` (priority 0)
    assert q.claim(conn, "w")["id"] == a
    assert q.cancel_scan(conn, 3) == {"cancelled": 1, "cancelling": 1}
    assert q.get_job(conn, b)["status"] == "cancelled"
    assert q.get_job(conn, a)["cancel_requested"] == 1
    assert q.get_job(conn, other)["cancel_requested"] == 0


# ── leaderboard ──────────────────────────────────────────────────────────

def test_leaderboard_pass_first_rank_only_pass_and_snooping(conn):
    hi_fail = _done_run(conn, verdict="FAIL", oos={"profit_factor": 9.0, "sharpe": 3.0, "trades": 5})
    ok = _done_run(conn, verdict="PASS", tf="4h", oos={"profit_factor": 1.4, "sharpe": 2.5, "trades": 40,
                                                       "costs": {"cost_drag_pct": 4.0}})
    best = _done_run(conn, verdict="PASS", tf="1d", oos={"profit_factor": 1.9, "sharpe": 0.5, "trades": 35})
    sol = _done_run(conn, verdict="PASS", symbol="SOLUSDT", oos={"profit_factor": 1.3, "trades": 31})
    lb = insights.leaderboard(conn)
    ids = [r["run_id"] for r in lb["rows"]]
    assert ids == [best, ok, sol, hi_fail]                 # FAIL never above PASS
    assert [r["rank"] for r in lb["rows"]] == [1, 2, 3, None]
    eth = lb["rows"][0]
    assert eth["attempts"]["runs"] == 3 and eth["attempts"]["timeframes"] == 3
    assert eth["snooping"] == "medium"                    # 3 timeframes tried
    assert lb["rows"][2]["snooping"] == "low"
    assert lb["summary"] == {"runs": 4, "pass": 3, "fail": 1, "trials": 0, "combinations": 4}
    by_sharpe = insights.leaderboard(conn, sort="oos_sharpe")
    assert [r["run_id"] for r in by_sharpe["rows"]][:2] == [ok, best]
    assert [r["run_id"] for r in insights.leaderboard(conn, verdict="FAIL")["rows"]] == [hi_fail]
    assert [r["run_id"] for r in insights.leaderboard(conn, timeframe="4h")["rows"]] == [ok]
    assert insights.leaderboard(conn, symbol="SOLUSDT")["rows"][0]["holdout"]["profit_factor"] == 1.3


def test_snooping_levels():
    assert insights.snooping_level(1, 1, 0) == "low"
    assert insights.snooping_level(4, 1, 0) == "medium"
    assert insights.snooping_level(2, 3, 0) == "medium"
    assert insights.snooping_level(2, 1, 300) == "high"
    assert insights.snooping_level(10, 1, 0) == "high"


def test_leaderboard_backtests_and_unfinished_excluded(conn):
    _done_run(conn, mode="backtest")
    _queued_run(conn)
    assert insights.leaderboard(conn)["rows"] == []


# ── API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def admin(client_for):
    return client_for("u-admin")


def test_api_run_defaults_and_estimate(admin):
    d = admin.get("/api/v1/lab/run-defaults").json()
    assert d["timeframes"]["15m"]["n_trials"] == 10 and d["timeouts"]["optimize"] == 18000
    assert d["slots"] == 1 and d["scan_slots"] == 1 and d["trial_options"] == [10, 30, 60]
    body = {"mode": "validate", "symbols": ["ETHUSDT"], "timeframes": ["15m"], "start": "2020-01-01"}
    e = admin.post("/api/v1/lab/estimate", json=body).json()
    assert e["cells"][0]["cached"] is False and 35 * 60 <= e["total_s"] <= 50 * 60
    assert e["timeout_s"] == 10800 and e["exceeds_timeout"] == [] and e["near_timeout"] is False
    assert e["long"] is False and e["queue"]["wait_s"] == 0
    opt = admin.post("/api/v1/lab/estimate", json={**body, "mode": "optimize", "n_trials": 60}).json()
    assert opt["total_s"] > 3 * 3600 and opt["long"] is True       # > the old 3 h limit ...
    assert opt["timeout_s"] == 18000 and opt["exceeds_timeout"] == []  # ... fits the 5 h optimize limit
    scan = admin.post("/api/v1/lab/estimate", json={
        "mode": "validate", "symbols": ["ETHUSDT", "BTCUSDT", "SOLUSDT"], "timeframes": ["1h", "15m"],
        "starts": {"15m": "2024-11-11"}, "scan": True}).json()
    assert len(scan["cells"]) == 6 and set(scan["by_timeframe"]) == {"1h", "15m"}
    assert scan["wall_s"] == scan["total_s"] and scan["parallel"] == 1
    assert admin.post("/api/v1/lab/estimate", json={**body, "timeframes": ["2h"]}).status_code == 422
    assert admin.post("/api/v1/lab/estimate", json={**body, "symbols": []}).status_code == 422


def test_api_job_eta_queue_and_scan_cancel(admin):
    r = admin.post("/api/v1/lab/runs", json={**RUN, "mode": "validate", "timeframe": "1h"}).json()
    j = admin.get(f"/api/v1/lab/jobs/{r['job_id']}").json()
    assert j["status"] == "queued" and j["queue_position"] == 1 and j["eta_start_s"] == 0
    assert j["est_s"] > 0 and j["timeout_s"] == 10800
    sc = admin.post("/api/v1/lab/scans", json={
        "template_id": "rosyade_family", "symbols": ["ETHUSDT", "BTCUSDT"], "timeframes": ["4h", "15m"],
        "starts": {"15m": "2024-11-11"}, "mode": "validate"}).json()
    detail = admin.get(f"/api/v1/lab/scans/{sc['scan_id']}").json()
    assert detail["queue"]["queued"] == 4 and detail["queue"]["queue_position"] == 2
    assert detail["queue"]["eta_s"] > 0
    runs = {(x["symbol"], x["timeframe"]): x["run_id"] for x in detail["rows"]}
    assert admin.get(f"/api/v1/lab/runs/{runs[('ETHUSDT', '15m')]}").json()["start"] == "2024-11-11"
    assert admin.get(f"/api/v1/lab/runs/{runs[('ETHUSDT', '4h')]}").json()["start"] is None
    qs = admin.get("/api/v1/lab/queue").json()
    assert qs["queued"] == 5 and [x["position"] for x in qs["jobs"]] == [1, 2, 3, 4, 5]
    c = admin.post(f"/api/v1/lab/scans/{sc['scan_id']}/cancel").json()
    assert c == {"scan_id": sc["scan_id"], "cancelled": 4, "cancelling": 0}
    after = admin.get(f"/api/v1/lab/scans/{sc['scan_id']}").json()
    assert after["status"] == "cancelled" and after["queue"] is None
    assert admin.post("/api/v1/lab/scans/999/cancel").status_code == 404
    assert admin.post(f"/api/v1/lab/jobs/{r['job_id']}/cancel").json()["status"] == "cancelled"


def test_api_leaderboard(admin, lab_env):
    c = db.connect()
    try:
        _done_run(c, verdict="PASS")
        _done_run(c, verdict="FAIL", tf="4h")
    finally:
        c.close()
    lb = admin.get("/api/v1/lab/leaderboard").json()
    assert [r["verdict"] for r in lb["rows"]] == ["PASS", "FAIL"] and lb["summary"]["pass"] == 1
    assert admin.get("/api/v1/lab/leaderboard?verdict=PASS").json()["summary"]["runs"] == 1
    assert admin.get("/api/v1/lab/leaderboard?sort=bogus").status_code == 422


def test_new_planning_endpoints_admin_only(client_for):
    c = client_for("u-plain")
    for path in ("/api/v1/lab/run-defaults", "/api/v1/lab/queue", "/api/v1/lab/leaderboard"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/v1/lab/estimate", json={"symbols": ["ETHUSDT"], "timeframes": ["4h"]}).status_code == 403
    assert c.post("/api/v1/lab/scans/1/cancel").status_code == 403
