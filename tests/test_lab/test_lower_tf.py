"""Lower timeframes (15m / 30m) in the Strategy Lab: template, HTF mapping,
warm-up, per-timeframe watch scheduling (batched), data cache and API."""
import json

import pytest

from src.lab import data_cache as dc
from src.lab import engine_adapter as ea
from src.lab import scheduler as sch
from src.lab import watch_eval as we
from src.lab.settings import get_lab_settings
from src.lab.templates import rosyade_family as T

from .test_lab_api import RUN, client_for  # noqa: F401  (fixture re-export)

T0 = 1767254400  # 2026-01-01T08:00:00Z


def test_template_offers_lower_timeframes():
    assert T.TIMEFRAMES == ["15m", "30m", "1h", "4h", "1d"]
    assert "1h" in T.HTF_CHOICES
    for tf in T.TIMEFRAMES:
        assert tf in dc.TF_SECONDS and tf in sch.TF_SECONDS and tf in ea.TF_SECONDS


@pytest.mark.parametrize("value,tf,exp", [
    ("same", "15m", "15m"), ("1h", "15m", "1h"), ("4h", "15m", "4h"), ("1d", "30m", "1d"),
    ("15", "1h", "1h"),        # lower than base -> same
    ("60", "15m", "1h"), ("240", "30m", "4h"), ("1h", "4h", "4h"), ("1h", "1h", "1h"), ("W", "15m", "1w"),
])
def test_htf_mapping(value, tf, exp):
    assert ea._htf(value, tf) == exp


def test_effective_warmup_covers_closed_htf_bars():
    p = T.validate_params({})                         # EMA-194, "same"
    assert ea.effective_warmup(p, "15m") == 300       # same TF: template warm-up
    p4 = T.validate_params({"ema_htf_tf": "4h"})
    assert ea.effective_warmup(p4, "4h") == 300
    assert ea.effective_warmup(p4, "1h") == int(-(-(194 * 1.25 + 1) * 4 // 1))
    w15 = ea.effective_warmup(p4, "15m")
    assert w15 >= 194 * 16 and w15 == ea.effective_warmup(p4, "15m")
    off = T.validate_params({"ema_htf_tf": "4h", "use_ema_htf": False})
    assert ea.effective_warmup(off, "15m") == 300


def test_last_closed_bar_open_lower_tfs():
    t = T0 + 20                                       # 08:00:20, 30 s delay
    assert sch.last_closed_bar_open("15m", t, 30) == "2026-01-01T07:30:00Z"
    assert sch.last_closed_bar_open("15m", t + 15, 30) == "2026-01-01T07:45:00Z"
    assert sch.last_closed_bar_open("30m", t + 15, 30) == "2026-01-01T07:30:00Z"


def _watch(conn, tf, symbol="ETHUSDT"):
    cur = conn.execute("INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, created_at) "
                       "VALUES ('rosyade_family', ?, ?, '{}', '{}', '2026-01-01T00:00:00Z')", (symbol, tf))
    conn.commit()
    return cur.lastrowid


def _jobs(conn):
    return [(r["ref_id"], json.loads(r["payload_json"])) for r in
            conn.execute("SELECT * FROM lab_jobs WHERE kind='watch_eval' ORDER BY id")]


def test_watches_batched_per_timeframe_close(conn):
    s = get_lab_settings()
    w15 = [_watch(conn, "15m", f"C{i}USDT") for i in range(30)]
    w4 = _watch(conn, "4h")
    now = T0 + 45                                     # 4h, 1h, 30m and 15m all just closed
    jobs = sch.schedule_watches(conn, s, now)
    got = _jobs(conn)
    assert len(jobs) == 3                             # 25 + 5 (15m) and 1 (4h)
    by_tf = {}
    for _ref, p in got:
        by_tf.setdefault(p["timeframe"], []).extend(p["watch_ids"])
        assert len(p["watch_ids"]) <= sch.WATCH_BATCH_MAX
    assert by_tf == {"15m": w15, "4h": [w4]}
    assert sch.schedule_watches(conn, s, now + 30) == []          # same bars
    # next 15m close while the 15m batches are still queued: coalesced, nothing new
    assert sch.schedule_watches(conn, s, now + 900) == []
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    nxt = sch.schedule_watches(conn, s, now + 900)                # only the 15m ones are due
    assert len(nxt) == 2
    assert all(p["timeframe"] == "15m" and p["bar"] == "2026-01-01T08:00:00Z" for _r, p in _jobs(conn)[3:])


def test_single_watch_job_still_marks_busy(conn):
    s = get_lab_settings()
    wid = _watch(conn, "15m")
    from src.lab import queue as q
    q.enqueue(conn, "watch_eval", wid, {"initial": True}, priority=10)   # API's initial evaluation
    conn.commit()
    assert sch.schedule_watches(conn, s, T0 + 45) == []


def test_batch_executes_all_and_tolerates_failures(conn, monkeypatch):
    a, b, c = _watch(conn, "15m", "BTCUSDT"), _watch(conn, "15m", "ETHUSDT"), _watch(conn, "15m", "ADAUSDT")
    conn.execute("DELETE FROM watches WHERE id=?", (c,))           # deleted after scheduling
    conn.commit()
    seen = []

    def fake_eval(w, offline=False):
        seen.append(w["symbol"])
        if w["symbol"] == "BTCUSDT":
            raise RuntimeError("boom")
        return {"last_bar": "2026-01-01T07:45:00Z", "position": None, "recent_trades": [], "last_signal": None}

    monkeypatch.setattr(we, "evaluate", fake_eval)
    job = {"id": 1, "ref_id": a, "payload_json": json.dumps({"watch_ids": [a, b, c]})}
    we.execute_watch(conn, job)                                    # one failure does not fail the batch
    assert seen == ["BTCUSDT", "ETHUSDT"]                          # grouped by symbol
    st = {r["watch_id"]: r for r in conn.execute("SELECT * FROM watch_state")}
    assert "boom" in st[a]["error"] and st[b]["error"] is None
    with pytest.raises(RuntimeError):                              # all failed -> job error
        we.execute_watch(conn, {"id": 2, "ref_id": a, "payload_json": json.dumps({"watch_ids": [a]})})


def test_cached_datasets_lists_lower_tfs(lab_env):
    d = lab_env / "cache"
    d.mkdir(exist_ok=True)
    for tf in ("15m", "30m", "4h", "5m"):
        (d / f"ETHUSDT_PERP_{tf}.parquet").write_bytes(b"x")
    assert sorted(v["timeframe"] for v in dc.cached_datasets().values()) == ["15m", "30m", "4h"]


def test_prefetch_cli_rejects_unknown_tf(lab_env):
    with pytest.raises(ValueError):
        dc.prefetch(["ETHUSDT"], ["7m"], log=lambda *_: None)


def test_api_accepts_15m_run_watch_and_klines_tf(client_for):  # noqa: F811
    c = client_for("u-admin")
    r = c.post("/api/v1/lab/runs", json={**RUN, "timeframe": "15m", "params": {"ema_htf_tf": "4h"}})
    assert r.status_code == 200, r.text
    d = c.get(f"/api/v1/lab/runs/{r.json()['run_id']}").json()
    assert d["timeframe"] == "15m"
    assert d["snooping"] == {"timeframes_tested": [], "holdout_touches_all_tf": 0, "validated_runs_all_tf": 0,
                             "optimizer_trials_all_tf": 0}
    assert c.post("/api/v1/lab/runs", json={**RUN, "timeframe": "5m"}).status_code == 422
    w = c.post("/api/v1/lab/watches", json={"template_id": "rosyade_family", "symbol": "ETHUSDT",
                                             "timeframe": "30m", "params": {}})
    assert w.status_code == 200
    sc = c.post("/api/v1/lab/scans", json={"template_id": "rosyade_family", "symbols": ["ETHUSDT"],
                                            "timeframes": ["15m", "30m", "1h"], "mode": "validate"})
    assert sc.status_code == 200
    assert len(c.get(f"/api/v1/lab/scans/{sc.json()['scan_id']}").json()["rows"]) == 3


def test_watch_cap(client_for, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LAB_WATCH_MAX_ACTIVE", "2")
    get_lab_settings.cache_clear()
    c = client_for("u-admin")
    body = {"template_id": "rosyade_family", "symbol": "ETHUSDT", "timeframe": "15m", "params": {}}
    assert c.post("/api/v1/lab/watches", json=body).status_code == 200
    assert c.post("/api/v1/lab/watches", json=body).status_code == 200
    assert c.post("/api/v1/lab/watches", json=body).status_code == 422


def test_delete_watch_keeps_batched_job(client_for, lab_env):  # noqa: F811
    from src.lab import db, queue as q
    c = client_for("u-admin")
    body = {"template_id": "rosyade_family", "symbol": "ETHUSDT", "timeframe": "15m", "params": {}}
    a = c.post("/api/v1/lab/watches", json=body).json()["watch_id"]
    b = c.post("/api/v1/lab/watches", json=body).json()["watch_id"]
    conn = db.connect()
    try:
        jid = q.enqueue(conn, "watch_eval", a, {"bar": "x", "timeframe": "15m", "watch_ids": [a, b]}, priority=10)
        conn.commit()
        c.delete(f"/api/v1/lab/watches/{a}")
        assert q.get_job(conn, jid)["status"] == "queued"            # b still gets evaluated
    finally:
        conn.close()
