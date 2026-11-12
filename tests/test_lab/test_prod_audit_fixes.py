"""Audit 2026-11-13 (03-produksi-data.md) fixes:

  K1  a rejected / failed live order is "perlu dicek" and raises a STICKY in-web notification
  P3  "terbukti" only when the BTC-relative interval is above zero too ("searah pasar" otherwise)
  P4  short post-close jobs get a priority lane next to the ~3 min outlook_refresh
  S1  "Funding 7 hari" sums the last 21 (8 h) settlements even when the newest is not cached yet
  S3  the worker no longer SIGTERMs a child that already finished its job ("rc=-15 but done")

No network, no engine, no trading code: expected signals come from a fake compute_fn, logs and
bmtm_trading.db are throw-away files, worker children are `python -c "sleep"`.
"""
import json
import os
import pathlib
import sys

import pytest

from src.lab import notify, notify_events
from src.lab import queue as q
from src.lab.db import utcnow
from src.lab.ledger import scoring
from src.lab.ledger.store import ensure_schema as ledger_schema, insert_signal, iso, kv_get, kv_set, to_epoch
from src.lab.ledger.verdicts import honest_verdict, verdicts
from src.lab.livecheck import jobs
from tests.test_lab.test_livecheck import B0, H4, _done, _nginx, _trading_db, ev, fake_compute, lc_env, run_match  # noqa: F401
from tests.test_lab.test_livecheck import _nginx_ev

REJECT = "An open position for 'ETH/USDT:USDT' already exists on the exchange for user 'user-rosyade-02'"


# ── K1: rejected live order -> perlu dicek + sticky notification ─────────────

def test_rejected_open_and_failed_close_are_perlu_dicek():
    t_open, t_close = B0 + H4 + 3, B0 + 3 * H4 + 4
    variants = {"utama": [ev("open", "short", B0), ev("close", "short", B0 + 2 * H4)]}
    tl = [{"ts": t_open + 2, "action": "open", "side": "short", "status": "rejected", "fill_price": None,
           "fill_qty": None, "reason": REJECT},
          {"ts": t_close + 2, "action": "close", "side": "short", "status": "failed", "fill_price": None,
           "fill_qty": None, "reason": "No open position for ETH/USDT:USDT"}]
    rows = run_match(variants, [_nginx_ev(t_open), _nginx_ev(t_close)], tl, now=B0 + 10 * H4)
    assert [(r["action"], r["status"], r["perlu_dicek"]) for r in rows] == [
        ("open", "gagal", True), ("close", "gagal", True)]


def test_executed_rows_are_not_flagged_by_the_new_rule():
    t = B0 + H4 + 3
    tl = [{"ts": t + 2, "action": "open", "side": "short", "status": "success", "fill_price": 2000.0,
           "fill_qty": 1.0, "reason": None}]
    rows = run_match({"utama": [ev("open", "short", B0)]}, [_nginx_ev(t)], tl, now=B0 + 10 * H4)
    assert rows[0]["status"] == "cocok" and not rows[0]["perlu_dicek"]


def _cycle_with_rejected_open(conn, lc_env, now):
    from src.lab import presets
    presets.seed(conn)
    t1 = B0 + H4 + 4
    (lc_env["nginx"] / "access.log").write_text(_nginx(t1, 202) + "\n")
    (lc_env["app"] / "bmtm-api-out.log").write_text(_done(t1, 202, 30.0) + "\n")
    db = lc_env["root"] / "bmtm_trading.db"
    _trading_db(db, [{"ts": t1 + 2, "action": "open", "side": "short", "status": "rejected", "err": REJECT}])
    return jobs.execute_cycle(conn, None, now=now, compute_fn=fake_compute([ev("open", "short", B0)], now - H4),
                              trading_db_path=str(db))


def test_livecheck_cycle_raises_one_sticky_notification_per_failed_order(conn, lc_env):
    now = B0 + 4 * H4
    out = _cycle_with_rejected_open(conn, lc_env, now)
    assert out["counts"] == {"gagal": 1}
    assert conn.execute("SELECT perlu_dicek FROM livecheck_rows").fetchone()[0] == 1
    rows = [dict(r) for r in conn.execute("SELECT id, type, title, body, link FROM notifications")]
    assert len(rows) == 1
    n = rows[0]
    assert n["type"] == "live" and n["link"] == "/bot#cek"
    assert n["title"] == "Bot live tidak ikut sinyal: open SHORT ETH tidak tereksekusi"
    assert "posisi manual" in n["body"] and "Sudah dicek" in n["body"] and "WIB" in n["body"]
    assert "rosyade" not in json.dumps(rows)
    # every later cycle rebuilds the rows: still exactly one notification
    jobs.execute_cycle(conn, None, now=now + 3600, compute_fn=fake_compute([ev("open", "short", B0)], now - H4),
                       trading_db_path=str(lc_env["root"] / "bmtm_trading.db"))
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 1
    lst = notify.list_for(conn, "admin-a")
    assert [p["id"] for p in lst["pinned"]] == [n["id"]] and lst["pinned"][0]["sticky"] is True


def test_old_failed_rows_stay_flagged_but_do_not_alarm(conn, lc_env):
    now = B0 + H4 + 15 * 86400                       # 9 Nov 07:00 WIB-like row, seen 15 days later
    _cycle_with_rejected_open(conn, lc_env, now)
    assert conn.execute("SELECT perlu_dicek FROM livecheck_rows").fetchone()[0] == 1
    notify.ensure_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_alarm_text_for_a_failed_close_and_hook_never_raises(conn):
    rows = [{"status": "gagal", "action": "close", "side": "long", "bar_open": B0, "bar_close": B0 + H4,
             "reason": "close ditolak: tidak ada posisi terbuka di exchange"},
            {"status": "cocok", "action": "open", "side": "long", "bar_open": B0 - H4, "bar_close": B0}]
    ids = notify_events.livecheck_alarms(conn, rows, "ETHUSDT", "4H-ETH-Basic", B0 + 2 * H4)
    assert len(ids) == 1
    t = conn.execute("SELECT title, body FROM notifications").fetchone()
    assert t["title"] == "Bot live: sinyal close LONG ETH tidak tereksekusi"
    assert "bisa masih terbuka" in t["body"] and "4H-ETH-Basic" in t["body"]
    assert notify_events.livecheck_alarms(conn, [{"status": "gagal", "bar_close": "x"}], "ETHUSDT", "p", 0) is None


def test_sticky_survives_read_all_and_prune_until_acked(conn, monkeypatch):
    plain = notify.notify(conn, "job", "biasa")
    sticky = notify.notify(conn, "live", "order ditolak", "b", "/bot#cek", "live:1", sticky=True)
    assert notify.unread_count(conn, "a") == 2 and notify.unread_count(conn, "b") == 2
    notify.mark_all_read(conn, "a")
    notify.mark_read(conn, "a", sticky)
    assert notify.unread_count(conn, "a") == 1                       # the sticky one stays
    lst = notify.list_for(conn, "a")
    by_id = {i["id"]: i for i in lst["items"]}
    assert by_id[plain]["read"] is True and by_id[sticky]["read"] is False and by_id[sticky]["sticky"] is True
    assert [p["id"] for p in lst["pinned"]] == [sticky]
    assert notify.list_for(conn, "a", unread_only=True)["items"][0]["id"] == sticky
    # retention prune keeps an unacknowledged sticky notification
    conn.execute("UPDATE notifications SET created_at='2000-01-01T00:00:00.000000Z'")
    conn.commit()
    notify.prune(conn)
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT id FROM notifications")] == [sticky]
    # one admin acknowledges: gone from every admin's pinned list and badge
    assert notify.ack(conn, "b", sticky) and not notify.ack(conn, "b", 999)
    assert notify.unread_count(conn, "a") == 0 and notify.unread_count(conn, "b") == 0
    item = notify.list_for(conn, "a")["items"][0]
    assert item["acked_at"] and item["read"] is True and notify.list_for(conn, "a")["pinned"] == []
    assert notify.ack(conn, "a", sticky)                              # idempotent
    notify.prune(conn)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_api_ack(conn):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers

    def client(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    sticky = notify.notify(conn, "live", "order ditolak", sticky=True)
    admin, other = client("u-admin"), client("admin-uuid-1")
    assert client("u-plain").post(f"/api/v1/lab/notifications/{sticky}/ack").status_code == 403
    body = admin.get("/api/v1/lab/notifications").json()
    assert body["unread"] == 1 and body["pinned"][0]["id"] == sticky
    assert admin.post("/api/v1/lab/notifications/read-all").json()["unread"] == 1
    assert admin.post("/api/v1/lab/notifications/999/ack").status_code == 404
    assert admin.post(f"/api/v1/lab/notifications/{sticky}/ack").json() == {"ok": True, "unread": 0}
    seen = other.get("/api/v1/lab/notifications").json()             # unpinned for everyone, still news to them
    assert seen["pinned"] == [] and seen["items"][0]["acked_at"] and seen["unread"] == 1


# ── P3: "terbukti" needs the BTC-relative interval above zero too ────────────

T0 = int(to_epoch("2026-10-14T00:00:00Z"))


def _bars_market(sym, a, b):
    """Every coin, BTC included, falls 0.05 % per 15 min: a short is right, but only as right as BTC."""
    out = []
    for i in range(int((b - a) // 900) + 2):
        ts = (a // 900) * 900 + i * 900
        o, c = 100 * 0.9995 ** i, 100 * 0.9995 ** (i + 1)
        out.append({"ts": ts * 1000, "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": 1.0})
    return out


def _short_signals(conn, n, rekon_from=0):
    ledger_schema(conn)
    for i in range(n):
        insert_signal(conn, source="screener_rekon" if i >= rekon_from else "screener", signal_type="funding",
                      symbol="ETHUSDT" if i % 2 else "SOLUSDT", direction=-1, ts=iso(T0 + i * 86400),
                      dedupe_key=f"f{i}")
    conn.commit()
    scoring.score_pending(conn, lambda s, a, b: _bars_market(s, a // 1000, b // 1000), now_s=T0 + 40 * 86400)


def test_honest_verdict_mapping():
    assert honest_verdict("terbukti", "terbukti") == "terbukti"
    assert honest_verdict("terbukti", "belum_terbukti") == "searah_pasar"
    assert honest_verdict("terbukti", "negatif") == "searah_pasar"
    assert honest_verdict("terbukti", "belum_cukup_data") == "searah_pasar"
    assert honest_verdict("negatif", "belum_terbukti") == "negatif"
    assert honest_verdict("belum_terbukti", "terbukti") == "belum_terbukti"


def test_verdict_is_searah_pasar_when_btc_moved_the_same(conn):
    _short_signals(conn, 14, rekon_from=2)
    v = verdicts(conn)[0]
    assert v["verdict_raw"] == "terbukti" and v["verdict"] == "searah_pasar"
    assert v["verdict_rel_btc"] != "terbukti" and v["mean_pct"] > 0
    assert v["n_rekon"] == 12 and v["n_signals"] == 14
    assert v["first_ts"].startswith("2026-10-14") and v["last_ts"].startswith("2026-10-27")


def test_notification_downgrades_an_oversold_terbukti_with_btc_and_sample(conn):
    _short_signals(conn, 14, rekon_from=2)
    kv_set(conn, notify_events.KV_LEDGER, {"screener|funding|short": "terbukti"})   # what prod sent on 12 Nov
    conn.commit()
    ids = notify_events.ledger_verdicts(conn)
    n = conn.execute("SELECT title, body FROM notifications WHERE id=?", (ids[0],)).fetchone()
    assert n["title"] == "Rekam jejak sinyal: Funding short (screener) kini searah pasar (belum terbukti dibanding BTC)"
    body = n["body"]
    assert body.startswith("terbukti → searah pasar · 14 sinyal dinilai di 14 hari (14–27 Okt, 86% rekonstruksi)")
    assert "dibanding BTC" in body and "pasar yang turun" in body and "belum teruji di pasar naik" in body
    assert "sebelum biaya" in body and len(body) <= notify.BODY_MAX
    assert kv_get(conn, notify_events.KV_LEDGER) == {"screener|funding|short": "searah_pasar"}
    assert notify_events.ledger_verdicts(conn) == []                                 # no repeat


def test_weekly_report_carries_btc_relative_fields(conn, tmp_path):
    from datetime import datetime, timezone
    from src.lab.weekly import build
    _short_signals(conn, 14, rekon_from=2)
    rep = build.build(conn, "2026-W44", str(tmp_path / "none.db"), now=datetime(2026, 11, 12, tzinfo=timezone.utc))
    g = rep["sections"]["ledger"]["groups"][0]["overall"]
    assert g["verdict"] == "searah_pasar" and g["verdict_raw"] == "terbukti"
    assert g["mean_rel_btc_pct"] is not None and g["n_rekon"] == 12 and g["first_ts"]
    assert rep["sections"]["ledger"]["counts_overall"] == {"searah_pasar": 1}


# ── P4: priority lane next to the long outlook job ───────────────────────────

def _worker(lab_env, **env):
    from src.lab import settings as lab_settings
    from src.lab.worker import Worker
    for k, v in env.items():
        os.environ[k] = v
    lab_settings.get_lab_settings.cache_clear()
    return Worker(command=[sys.executable, "-c", "import time; time.sleep(30)"])


def _running(w):
    return sorted(r.job["kind"] for r in w.running.values())


@pytest.fixture
def wconn(lab_env, monkeypatch):
    from src.lab import db as labdb
    monkeypatch.delenv("LAB_PRIORITY_LANE", raising=False)
    c = labdb.connect()
    ws = []
    yield c, ws
    for w in ws:
        for r in list(w.running.values()):
            w._kill(r, "test")
    c.close()


def test_short_jobs_run_next_to_outlook_refresh(lab_env, wconn):
    c, ws = wconn
    # the 16:00 close on 12 Nov: outlook (8) got the only slot, the rest waited up to 274 s
    q.enqueue(c, "outlook_refresh", None, {}, priority=8)
    q.enqueue(c, "ledger_cycle", None, {}, priority=5)
    q.enqueue(c, "livecheck_cycle", None, {}, priority=5)
    q.enqueue(c, "shadow_cycle", None, {}, priority=4)
    c.commit()
    w = _worker(lab_env)
    ws.append(w)
    w.tick(c)
    assert _running(w) == ["ledger_cycle", "outlook_refresh"]
    w.tick(c)
    assert _running(w) == ["ledger_cycle", "outlook_refresh"]       # still one short job at a time
    ledger = next(r for r in w.running.values() if r.job["kind"] == "ledger_cycle")
    w._kill(ledger, "test")
    q.finish(c, ledger.job["id"], "done")
    w.tick(c)
    assert _running(w) == ["livecheck_cycle", "outlook_refresh"]


def test_two_watch_evals_never_overlap_and_heavy_jobs_keep_their_slot(lab_env, wconn):
    c, ws = wconn
    q.enqueue(c, "run", None)
    c.commit()
    w = _worker(lab_env)
    ws.append(w)
    w.tick(c)                                                        # a long optimise run holds the general slot
    for i in range(3):                                               # 71 watches: batches of 25 at a 4H close
        q.enqueue(c, "watch_eval", i + 1, {"watch_ids": [i + 1]}, priority=10)
    q.enqueue(c, "outlook_refresh", None, {}, priority=8)
    c.commit()
    w.tick(c)
    w.tick(c)
    assert _running(w) == ["run", "watch_eval"]                      # fast lane busy, priority lane: one short
    assert len(w.running) == 2


def test_worst_case_is_general_plus_one_long_plus_one_short(lab_env, wconn):
    c, ws = wconn
    q.enqueue(c, "run", None)
    c.commit()
    w = _worker(lab_env)
    ws.append(w)
    w.tick(c)
    q.enqueue(c, "outlook_refresh", None, {}, priority=8)
    q.enqueue(c, "universe_refresh", None, {}, priority=10)
    q.enqueue(c, "arena_snapshot", None, {}, priority=3)
    q.enqueue(c, "ledger_cycle", None, {}, priority=5)
    c.commit()
    for _ in range(3):
        w.tick(c)
    assert _running(w) == ["ledger_cycle", "run", "universe_refresh"]   # outlook waits for the long lane


def test_priority_lane_can_be_switched_off(lab_env, wconn):
    c, ws = wconn
    q.enqueue(c, "outlook_refresh", None, {}, priority=8)
    q.enqueue(c, "ledger_cycle", None, {}, priority=5)
    c.commit()
    w = _worker(lab_env, LAB_PRIORITY_LANE="0")
    ws.append(w)
    try:
        w.tick(c)
        assert _running(w) == ["outlook_refresh"]
    finally:
        os.environ.pop("LAB_PRIORITY_LANE", None)


def test_priority_kinds_are_fast_kinds():
    from src.lab.worker import FAST_KINDS, PRIORITY_KINDS
    assert set(PRIORITY_KINDS) <= set(FAST_KINDS)
    assert "outlook_refresh" not in PRIORITY_KINDS and "universe_refresh" not in PRIORITY_KINDS


# ── S3: a child that already finished is not SIGTERMed ───────────────────────

def test_worker_does_not_kill_a_child_that_finished_its_job(lab_env, wconn):
    c, ws = wconn
    jid = q.enqueue(c, "arena_snapshot", None, {}, priority=3)
    c.commit()
    w = _worker(lab_env)
    ws.append(w)
    w.tick(c)
    r = w.running[jid]
    q.finish(c, jid, "done")                       # what the child does right before it exits
    w._last_hb = 0.0
    w._supervise(c)
    assert r.killed_reason is None and r.proc.poll() is None
    # a cancel request still kills
    jid2 = q.enqueue(c, "ledger_cycle", None, {}, priority=5)
    c.commit()
    w._kill(r, "test")
    w._reap_children(c)
    w.tick(c)
    r2 = w.running[jid2]
    q.request_cancel(c, jid2)
    w._last_hb = 0.0
    w._supervise(c)
    assert r2.killed_reason == "cancelled"


# ── cache writes safe for two writers ────────────────────────────────────────

def test_cache_temp_names_are_per_process_and_index_keeps_both_writers(lab_env):
    import pandas as pd
    from src.lab import data_cache as dc
    p = dc.ohlcv_path("ETHUSDT", "4h")
    assert str(os.getpid()) in dc._tmp(p).name and dc._tmp(p).name.endswith(".tmp")
    assert not dc._tmp(p).name.endswith(".parquet")                 # never picked up as a cached dataset

    class Frame:                                                     # parquet engines are not in the test venv
        def to_parquet(self, path, index=False):
            pathlib.Path(path).write_bytes(b"PAR1")

    dc._save(Frame(), p)
    assert p.read_bytes() == b"PAR1"
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2026-11-01", "2026-11-02"], utc=True)})
    dc._write_index_entry("ETHUSDT", "4h", df)
    dc._write_index_entry("BTCUSDT", "4h", df)
    assert set(dc.read_index()) == {"ETHUSDT_4h", "BTCUSDT_4h"}
    assert not [f for f in os.listdir(dc.data_dir()) if f.endswith(".tmp")]

    class Boom:
        def to_parquet(self, path, index=False):
            pathlib.Path(path).write_bytes(b"half")
            raise OSError("disk full")
    with pytest.raises(OSError):
        dc._save(Boom(), p)
    assert p.read_bytes() == b"PAR1" and not [f for f in os.listdir(dc.data_dir()) if f.endswith(".tmp")]


# ── S1: Funding 7 hari = the last 21 settlements ─────────────────────────────

def _panel_with_funding(interval_h: int, missing_last: bool, rate: float = 0.0001):
    import pandas as pd
    from src.lab.universal import strategy as S
    ts = pd.date_range("2026-11-01", "2026-11-12 12:00", freq="4h", tz="UTC")     # last bar 12:00-16:00
    ohlcv = {"ETHUSDT": pd.DataFrame({"timestamp": ts, "close": 100.0})}
    end = ts[-1] + pd.Timedelta(hours=4)                                          # 12 Nov 16:00 settlement
    st = pd.date_range(pd.Timestamp("2026-11-01", tz="UTC"), end, freq=f"{interval_h}h")
    if missing_last:
        st = st[:-1]                                                              # not cached yet at 16:00:53
    fund = {"ETHUSDT": pd.DataFrame({"timestamp": st, "funding_rate": rate})}
    return S.build_panel(ohlcv, fund)


@pytest.mark.parametrize("interval_h,expected_n", [(8, 21), (4, 42)])
@pytest.mark.parametrize("missing_last", [False, True])
def test_funding_7d_uses_seven_full_days_of_settlements(interval_h, expected_n, missing_last):
    from src.lab.universal import strength
    p = _panel_with_funding(interval_h, missing_last)
    t = len(p.ts) - 1
    got = strength.funding_7d_apr_pct(p, t, 0)
    assert got == pytest.approx(expected_n * 0.0001 * 365.0 / 7.0 * 100.0)


def test_funding_7d_without_settlement_counts_falls_back_to_the_old_window():
    from dataclasses import replace
    from src.lab.universal import strength
    p = replace(_panel_with_funding(8, False), funding_n=None)
    assert strength.funding_7d_apr_pct(p, len(p.ts) - 1, 0) == pytest.approx(21 * 0.0001 * 365.0 / 7.0 * 100.0)
