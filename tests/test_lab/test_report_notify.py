"""Laporan Mingguan + in-web notifications: store, event hooks, weekly build/snapshot, API.

No network, no bmtm_trading.db: trade_logs / deploy / backup logs are throw-away files in tmp_path.
"""
import json
import pathlib
import sqlite3
from datetime import datetime, timezone

import pytest

from src.lab import notify, notify_events, paper
from src.lab import queue as q
from src.lab.db import utcnow
from src.lab.ledger import scoring
from src.lab.ledger.store import ensure_schema as ledger_schema, insert_signal, iso, kv_get, to_epoch
from src.lab.presets import ensure_schema as presets_schema
from src.lab.weekly import build, schedule, store

WEEK = "2026-W46"                                  # Mon 2026-11-09 .. Mon 2026-11-16
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _types(conn, t=None):
    notify.ensure_schema(conn)
    sql = "SELECT type, title, body, link FROM notifications" + (" WHERE type=?" if t else "") + " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, (t,) if t else ())]


# ── store ─────────────────────────────────────────────────────────────────

def test_notify_dedupe_rate_limit_and_per_user_read_state(conn, monkeypatch):
    a = notify.notify(conn, "job", "Run 1 selesai", "b", "/lab/runs/1", "k1")
    assert a and notify.notify(conn, "job", "Run 1 selesai", "b", "/lab/runs/1", "k1") is None   # dedupe
    assert notify.notify(conn, "job", "x", link="https://evil.example")                           # link dropped
    assert _types(conn)[1]["link"] is None
    monkeypatch.setattr(notify, "MAX_PER_TYPE_PER_HOUR", 3)
    assert notify.notify(conn, "job", "three")
    assert notify.notify(conn, "job", "four") is None                                             # rate-limited
    assert notify.notify(conn, "paper", "other type ok")
    assert notify.unread_count(conn, "u1") == 4 and notify.unread_count(conn, "u2") == 4
    assert notify.mark_read(conn, "u1", a) and not notify.mark_read(conn, "u1", 999)
    lst = notify.list_for(conn, "u1")
    assert lst["unread"] == 3 and [i["read"] for i in lst["items"]][-1] is True
    assert notify.list_for(conn, "u1", unread_only=True)["items"][-1]["id"] != a
    notify.mark_all_read(conn, "u1")
    assert notify.unread_count(conn, "u1") == 0 and notify.unread_count(conn, "u2") == 4
    notify.notify(conn, "deploy", "new")
    assert notify.unread_count(conn, "u1") == 1


def test_notify_never_raises(conn):
    conn.close()
    assert notify.notify(conn, "job", "closed connection") is None


# ── job hooks (queue.finish / reap) ───────────────────────────────────────

def _run(conn, mode="validate", scan_id=None, verdict=None, status="queued"):
    rid = conn.execute(
        "INSERT INTO lab_runs (scan_id, template_id, symbol, timeframe, mode, status, params_json, costs_json, "
        "created_at, net_return_pct, max_dd_pct, trades) VALUES (?, 'rosyade_family', 'ETHUSDT', '4h', ?, ?, '{}', "
        "'{}', ?, 12.5, -8.25, 41)", (scan_id, mode, status, utcnow())).lastrowid
    if verdict:
        conn.execute("UPDATE lab_runs SET verdict=? WHERE id=?", (verdict, rid))
    jid = q.enqueue(conn, "run", rid, {})
    conn.commit()
    return rid, jid


def test_job_done_and_error_notify(conn):
    rid, jid = _run(conn, verdict="PASS")
    q.finish(conn, jid, "done")
    rid2, jid2 = _run(conn, mode="optimize")
    q.finish(conn, jid2, "error", "Traceback ...\nValueError: data kosong")
    rid3, jid3 = _run(conn)
    q.finish(conn, jid3, "cancelled")
    n = _types(conn, "job")
    assert len(n) == 2
    assert n[0]["title"] == f"Uji jujur #{rid} selesai · ETH 4 jam · Rosyade"
    assert n[0]["body"] == "Lolos · hasil bersih +12.50% · turun terdalam \u22128.25% · 41 trade"
    assert n[0]["link"] == f"/lab/runs/{rid}"
    assert n[1]["title"] == f"Cari setting terbaik #{rid2} gagal dijalankan · ETH 4 jam · Rosyade"
    assert n[1]["body"] == "Detail teknis: ValueError: data kosong"
    q.finish(conn, jid, "done")                       # already terminal: no duplicate
    assert len(_types(conn, "job")) == 2


def test_scan_notifies_once_when_last_cell_finishes(conn):
    sid = conn.execute("INSERT INTO lab_scans (template_id, mode, symbols_json, timeframes_json, created_at) "
                       "VALUES ('rosyade_family', 'validate', '[]', '[]', ?)", (utcnow(),)).lastrowid
    cells = [_run(conn, scan_id=sid, verdict=v) for v in ("PASS", "FAIL", None)]
    q.finish(conn, cells[0][1], "done")
    q.finish(conn, cells[1][1], "done")
    assert _types(conn, "job") == []
    q.finish(conn, cells[2][1], "cancelled")
    n = _types(conn, "job")
    assert len(n) == 1 and n[0]["title"] == f"Uji banyak koin #{sid} selesai · Rosyade"
    assert "dari 3 kombinasi koin × timeframe selesai · 1 lolos · 1 gagal" in n[0]["body"]
    assert "1 dibatalkan" in n[0]["body"] and n[0]["link"] == f"/lab/scan?id={sid}"


def test_reaped_job_that_fails_notifies(conn):
    rid, jid = _run(conn, mode="backtest")
    conn.execute("UPDATE lab_jobs SET status='running', attempts=9, heartbeat_at='2000-01-01T00:00:00Z' WHERE id=?",
                 (jid,))
    conn.commit()
    assert q.reap(conn, 60) == [jid]
    assert "gagal" in _types(conn, "job")[0]["title"]


# ── paper hooks ───────────────────────────────────────────────────────────

def _preset_watch(conn, name="4H-ETH-Basic", created="2026-11-09T01:00:00Z"):
    presets_schema(conn)
    acct = paper.create_account(conn, f"Paper {name}")
    wid = conn.execute(
        "INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, autopaper_account_id, "
        "autopaper_enabled, created_at) VALUES ('rosyade_family','ETHUSDT','4h','{}','{}',?,1,?)",
        (acct, created)).lastrowid
    pid = conn.execute(
        "INSERT INTO lab_presets (name, label, template_id, symbol, timeframe, params_json, costs_json, created_at) "
        "VALUES (?, 'x', 'rosyade_family', 'ETHUSDT', '4h', '{}', '{}', ?)", (name, created)).lastrowid
    conn.execute("INSERT INTO lab_preset_links (kind, ref_id, preset_id, created_at) VALUES ('watch', ?, ?, ?)",
                 (wid, pid, created))
    conn.commit()
    return acct, wid


def test_paper_auto_open_close_notify_manual_does_not(conn):
    acct, wid = _preset_watch(conn)
    p = paper.open_position(conn, account_id=acct, symbol="ETHUSDT", side="long", price=2000, sl=1900, tp=2300,
                            watch_id=wid, source="paper_auto")
    paper.close_position(conn, p["id"], 2100, "hard_tp")
    m = paper.open_position(conn, account_id=acct, symbol="ETHUSDT", side="short", price=2000, sl=2100)
    paper.close_position(conn, m["id"], 1990, "manual_close")
    n = _types(conn, "paper")
    assert [x["title"] for x in n] == ["Paper 4H-ETH-Basic: buka LONG ETH", "Paper 4H-ETH-Basic: tutup LONG ETH"]
    assert "batal jika (SL) 1,900.00 · target (TP) 2,300.00" in n[0]["body"]
    assert "R)" in n[1]["body"] and "kena target (TP)" in n[1]["body"] and "hard_tp" not in n[1]["body"]
    assert all("simulasi, bukan order sungguhan" in x["body"] for x in n)
    pid = conn.execute("SELECT preset_id FROM lab_preset_links WHERE ref_id=?", (wid,)).fetchone()[0]
    assert n[0]["link"] == f"/lab/arena?highlight={pid}" and n[1]["link"] == f"/journal?account_id={acct}"


# ── ledger verdict hook ───────────────────────────────────────────────────

T0 = int(to_epoch("2026-10-01T00:00:00Z"))


def _bars(sym, a, b):
    out = []
    for i in range(int((b - a) // 900) + 2):
        ts = (a // 900) * 900 + i * 900
        o, c = (100.0, 100.0) if sym == "BTCUSDT" else (100 * 1.0005 ** i, 100 * 1.0005 ** (i + 1))
        out.append({"ts": ts * 1000, "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": 1.0})
    return out


def _signals(conn, n, start_i=0):
    ledger_schema(conn)
    for i in range(start_i, start_i + n):
        insert_signal(conn, source="screener", signal_type="tier_a", symbol="ETHUSDT" if i % 2 else "SOLUSDT",
                      direction=1, ts=iso(T0 + i * 86400), dedupe_key=f"a{i}")
    conn.commit()
    scoring.score_pending(conn, lambda s, a, b: _bars(s, a // 1000, b // 1000), now_s=T0 + 40 * 86400)


def test_ledger_verdict_change_baseline_then_notify(conn):
    _signals(conn, 4)
    assert notify_events.ledger_verdicts(conn) == []          # baseline only
    assert kv_get(conn, notify_events.KV_LEDGER) == {"screener|tier_a|long": "belum_cukup_data"}
    assert notify_events.ledger_verdicts(conn) == []          # unchanged
    _signals(conn, 10, start_i=4)
    ids = notify_events.ledger_verdicts(conn)
    n = _types(conn, "ledger")
    assert len(ids) == 1 and n[0]["title"] == "Rekam jejak sinyal: Tier A long (screener) kini terbukti"
    assert n[0]["body"].startswith("belum cukup data → terbukti · ")
    assert n[0]["link"] == "/lab/signals?type=tier_a"


def test_ledger_cycle_calls_the_hook(conn, monkeypatch):
    from src.lab.ledger import jobs
    called = []
    monkeypatch.setattr(notify_events, "ledger_verdicts", lambda c: called.append(1))
    monkeypatch.setattr(jobs, "live_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "collect_all", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "score_pending", lambda *a, **k: {})
    jobs.execute_cycle(conn, {"payload_json": "{}"})
    assert called == [1]


# ── deploy log hook ───────────────────────────────────────────────────────

DEPLOY_LINES = [
    "[2026-11-11T15:25:00Z] andra deploy be release/x @ 7ad7731 (msg)",
    "[2026-11-11T15:27:06Z] backend live @ 7ad7731; health 200. backup /root/backups/deploy-be-1",
]


def test_deploy_log_scan(conn, tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text("[2026-11-10T00:00:00Z] backend live @ 1111111; old\n")
    assert notify_events.deploy_log_scan(conn, str(log)) == []           # baseline at EOF
    with log.open("a") as fh:
        fh.write("\n".join(DEPLOY_LINES) + "\n")
        fh.write("[2026-11-11T16:00:00Z] backend live @ 2222222 [dry-run]\n")
        fh.write("[2026-11-11T16:10:00Z] GAGAL: tes backend gagal token=abc123\n")
        fh.write("[2026-11-11T16:11:00Z] backend live @ 3333333 partial")   # no newline yet
    ids = notify_events.deploy_log_scan(conn, str(log))
    n = _types(conn, "deploy")
    assert len(ids) == 2 and n[0]["title"] == "Pembaruan sistem: backend terpasang @ 7ad7731"
    assert n[1]["title"].startswith("Pembaruan sistem gagal: tes backend gagal") and "abc123" not in n[1]["body"]
    with log.open("a") as fh:
        fh.write("\n")
    assert len(notify_events.deploy_log_scan(conn, str(log))) == 1       # completed line picked up once
    log.write_text("[2026-11-12T00:00:00Z] frontend live @ 4444444\n")   # rotated / truncated
    notify_events.deploy_log_scan(conn, str(log))
    assert _types(conn, "deploy")[-1]["title"] == "Pembaruan sistem: frontend terpasang @ 4444444"


# ── weekly report ─────────────────────────────────────────────────────────

def _trading_db(path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE trade_logs (id TEXT, user_id TEXT, symbol TEXT, action TEXT, side TEXT, status TEXT, "
              "fill_price REAL, created_at TEXT, error_details TEXT)")
    c.execute("CREATE TABLE webhook_configs (id TEXT, user_id TEXT, passphrase TEXT)")
    c.execute("INSERT INTO webhook_configs VALUES ('w', 'u1', 'super-secret')")
    c.executemany("INSERT INTO trade_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    c.commit()
    c.close()


def _seed_week(conn, tmp_path):
    a1, w1 = _preset_watch(conn, "4H-ETH-Basic")
    a2, w2 = _preset_watch(conn, "4H-SOL-Opt")
    _preset_watch(conn, "4H-BTC-Later", created="2026-11-20T00:00:00Z")      # starts after the week
    # ETH: one loss last week (before the presets' week), then win + loss this week
    p = paper.open_position(conn, account_id=a1, symbol="ETHUSDT", side="long", price=2000, sl=1900, qty=1,
                            watch_id=w1, source="paper_auto", when="2026-11-05T00:00:00Z")
    paper.close_position(conn, p["id"], 1950, "hard_sl", when="2026-11-06T00:00:00Z")
    p = paper.open_position(conn, account_id=a1, symbol="ETHUSDT", side="long", price=2000, sl=1900, qty=1,
                            watch_id=w1, source="paper_auto", when="2026-11-10T00:00:00Z")
    paper.close_position(conn, p["id"], 2200, "hard_tp", when="2026-11-10T08:00:00Z")
    p = paper.open_position(conn, account_id=a1, symbol="ETHUSDT", side="long", price=2000, sl=1900, qty=1,
                            watch_id=w1, source="paper_auto", when="2026-11-11T00:00:00Z")
    paper.close_position(conn, p["id"], 1900, "hard_sl", when="2026-11-11T08:00:00Z")
    # SOL: one trade this week, still open
    paper.open_position(conn, account_id=a2, symbol="SOLUSDT", side="short", price=150, sl=160, qty=10,
                        watch_id=w2, source="paper_auto", when="2026-11-11T00:00:00Z")
    tdb = tmp_path / "bmtm_trading.db"
    _trading_db(tdb, [
        ("1", "u1", "ETH/USDT:USDT", "open", "long", "success", 2001.0, "2026-11-09T00:00:07+00:00", None),
        ("2", "u2", "ETH/USDT:USDT", "open", "long", "rejected", None, "2026-11-09T00:00:08+00:00", "x"),
        ("3", "u1", "ETH/USDT:USDT", "close", "long", "failed", None, "2026-11-10T04:00:05+00:00", "y"),
        ("4", "u1", "ETH/USDT:USDT", "open", "long", "success", 1.0, "2026-11-02T00:00:05+00:00", None),
    ])
    rid, jid = _run(conn, mode="validate", verdict="PASS")
    conn.execute("UPDATE lab_runs SET created_at='2026-11-10T10:00:00Z' WHERE id=?", (rid,))
    conn.commit()
    return str(tdb)


def test_weekly_build_sections(conn, tmp_path):
    tdb = _seed_week(conn, tmp_path)
    dlog = tmp_path / "deploy.log"
    dlog.write_text("[2026-11-08T23:00:00Z] backend live @ 0000000\n" + "\n".join(DEPLOY_LINES) + "\n"
                    "[2026-11-11T16:10:00Z] GAGAL: backend hanya boleh di menit :15-:44 UTC\n")
    blog = tmp_path / "backup.log"
    blog.write_text("2026-11-10T07:36:33Z ok /root/backups/daily/bmtm-20261110.tar.gz (56K)\n"
                    "2026-11-11T02:30:01Z ok /root/backups/daily/bmtm-20261111.tar.gz (64K)\n")
    pm2 = json.dumps([{"name": "bmtm-api", "pm2_env": {"status": "online", "restart_time": 1, "pm_uptime": 1.79e12,
                                                         "SECRET_KEY": "must-not-leak"}}]).encode()
    rep = build.build(conn, WEEK, tdb, now=NOW, deploy_log=str(dlog), backup_log=str(blog), pm2_runner=lambda: pm2)
    assert rep["start"] == "2026-11-09T00:00:00Z" and rep["end"] == "2026-11-16T00:00:00Z" and rep["partial"]
    s = rep["sections"]
    pp = {p["preset"]: p for p in s["paper"]["presets"]}
    assert set(pp) == {"4H-ETH-Basic", "4H-SOL-Opt"}
    eth = pp["4H-ETH-Basic"]
    assert eth["trades_week"] == 2 and eth["trades_total"] == 3 and eth["wins_week"] == 1
    assert eth["balance_start"] == pytest.approx(10000 - 50 - 2000 * 0.0005 - 1950 * 0.0005 * 0.9995, rel=1e-3)
    assert eth["week_return_pct"] > 0 and eth["max_dd_pct"] > 0 and eth["progress_pct"] == pytest.approx(10.0)
    sol = pp["4H-SOL-Opt"]
    assert sol["trades_week"] == 0 and sol["open_positions"] == 1 and sol["unrealized_pnl"] is not None
    assert s["paper"]["best"]["preset"] == "4H-ETH-Basic" and s["paper"]["worst"] is None
    lb = s["live_bot"]
    assert lb["available"] and lb["orders"] == 3 and lb["signals"] == 2 and lb["executed"] == 1 and lb["rejected"] == 2
    assert "super-secret" not in json.dumps(rep) and "u1" not in json.dumps(lb)
    lab = s["lab"]
    assert lab["runs"] == 1 and lab["pass"] == 1 and lab["runs_by_mode"] == {"validate": 1}
    assert s["ledger"]["available"] is False and s["execution"]["available"] is False
    sysx = s["system"]
    assert sysx["deploys"]["live"] == 1 and sysx["deploys"]["failed"] == 1
    assert sysx["backups"]["ok"] == 2 and sysx["backups"]["last"]["ts"] == "2026-11-11T02:30:01Z"
    assert sysx["processes"] == [{"name": "bmtm-api", "status": "online", "restarts": 1, "unstable_restarts": None,
                                  "up_since": sysx["processes"][0]["up_since"]}]
    assert "must-not-leak" not in json.dumps(rep)
    assert {h["href"] for h in rep["hooks"]} == {"/lab/arena", "/lab/live-check", "/lab/outlook"}


def test_weekly_empty_week_says_no_data(conn, tmp_path):
    rep = build.build(conn, "2026-W40", str(tmp_path / "none.db"), now=NOW, deploy_log=str(tmp_path / "x"),
                      backup_log=str(tmp_path / "y"), pm2_runner=lambda: b"")
    s = rep["sections"]
    assert not rep["partial"]
    assert all(not s[k]["available"] for k in ("paper", "ledger", "execution", "live_bot", "lab"))
    assert s["system"]["deploys"]["available"] is False and s["system"]["processes"] is None


def test_weekly_ledger_week_vs_overall(conn, tmp_path):
    _signals(conn, 14)
    rep = build.build(conn, "2026-W41", str(tmp_path / "none.db"), now=NOW)   # 2026-10-05 .. 10-12
    lg = rep["sections"]["ledger"]
    g = lg["groups"][0]
    assert lg["available"] and g["overall"]["n"] == 11 and g["week"]["n"] == 7
    assert g["overall"]["verdict"] == "terbukti" and g["week"]["verdict"] == "belum_cukup_data"


def test_snapshot_schedule_write_once_and_no_backfill(conn, tmp_path, lab_env, monkeypatch):
    from src.lab.settings import get_lab_settings
    monkeypatch.setenv("LAB_DEPLOY_LOG_PATH", str(tmp_path / "missing.log"))
    s = get_lab_settings()
    first = datetime(2026, 11, 11, 10, tzinfo=timezone.utc)
    assert schedule.due_week(conn, first) is None                      # W45 was over before the feature ran
    mon_early = datetime(2026, 11, 16, 0, 10, tzinfo=timezone.utc)
    assert schedule.due_week(conn, mon_early) is None                  # before 00:30
    mon = datetime(2026, 11, 16, 0, 31, tzinfo=timezone.utc)
    assert schedule.due_week(conn, mon) == WEEK
    schedule.tick(conn, s, mon.timestamp())
    snap = store.get(conn, WEEK)
    assert snap["source"] == "snapshot" and snap["snapshot"]["generator"] == "worker"
    assert schedule.due_week(conn, mon) is None
    rep = _types(conn, "report")[0]
    assert rep["link"] == f"/lab/report?week={WEEK}" and rep["title"] == "Laporan mingguan siap: 9–16 Nov"
    assert rep["body"].startswith("Senin 9 Nov 07:00 WIB s/d Senin 16 Nov 07:00 WIB (minggu 2026-W46).")
    assert store.save(conn, {"week": WEEK, "start": "a", "end": "b"}) is False
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE weekly_reports SET data_json='{}' WHERE week=?", (WEEK,))
    assert build.get_or_build(conn, WEEK, "")["source"] == "snapshot"


def test_week_helpers():
    assert store.parse_week("2026-W46").isoformat() == "2026-11-09"
    assert store.shift("2026-W01", -1) == "2025-W52" or store.shift("2026-W01", -1) == "2025-W53"
    with pytest.raises(ValueError):
        store.parse_week("2026-46")


# ── API ───────────────────────────────────────────────────────────────────

@pytest.fixture
def api(lab_env):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers

    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    return make


def test_api_report_readable_by_team_notifications_admin_only(api, monkeypatch):
    """CEO decision 2026-11-12: every logged-in team account reads the weekly report;
    notifications (and every other Lab tool) stay admin-only."""
    from src.lab.weekly import system
    monkeypatch.setattr(system, "pm2_processes", lambda runner=None: None)
    c = api("u-plain")
    r = c.get("/api/v1/lab/report/weeks")
    assert r.status_code == 200 and len(r.json()["weeks"]) == 12
    r = c.get("/api/v1/lab/report/weekly", params={"week": "2026-W40"})
    assert r.status_code == 200 and r.json()["partial"] is False
    assert c.get("/api/v1/lab/report/weekly", params={"week": "bad"}).status_code == 422
    assert c.get("/api/v1/lab/notifications").status_code == 403
    assert c.post("/api/v1/lab/notifications/read-all").status_code == 403
    assert c.post("/api/v1/lab/notifications/1/read").status_code == 403
    assert c.get("/api/v1/lab/journal").status_code == 403               # other Lab tools: still admin


def test_api_report_needs_login(lab_env):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers
    app = create_app()
    app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
    c = TestClient(app)
    assert c.get("/api/v1/lab/report/weeks").status_code == 401
    assert c.get("/api/v1/lab/report/weekly").status_code == 401


def test_api_report(api, conn, monkeypatch):
    from src.lab.weekly import system
    monkeypatch.setattr(system, "pm2_processes", lambda runner=None: None)
    c = api("u-admin")
    r = c.get("/api/v1/lab/report/weeks")
    assert r.status_code == 200 and r.json()["weeks"][0]["current"] and len(r.json()["weeks"]) == 12
    r = c.get("/api/v1/lab/report/weekly")
    assert r.status_code == 200 and r.json()["source"] == "live" and set(r.json()["sections"]) == {
        "paper", "ledger", "execution", "live_bot", "lab", "system"}
    assert c.get("/api/v1/lab/report/weekly", params={"week": "bad"}).status_code == 422
    assert c.get("/api/v1/lab/report/weekly", params={"week": "2999-W01"}).status_code == 422
    assert c.get("/api/v1/lab/report/weekly", params={"week": "2026-W40"}).json()["partial"] is False


def test_api_notifications(api, conn):
    a = notify.notify(conn, "job", "satu")
    notify.notify(conn, "paper", "dua")
    c, other = api("u-admin"), api("admin-uuid-1")
    body = c.get("/api/v1/lab/notifications").json()
    assert body["unread"] == 2 and [i["title"] for i in body["items"]] == ["dua", "satu"]
    assert c.post(f"/api/v1/lab/notifications/{a}/read").json() == {"ok": True, "unread": 1}
    assert c.post("/api/v1/lab/notifications/999/read").status_code == 404
    assert c.post("/api/v1/lab/notifications/read-all").json()["unread"] == 0
    assert other.get("/api/v1/lab/notifications", params={"unread_only": True}).json()["unread"] == 2


def test_no_trading_imports_orders_or_telegram():
    root = pathlib.Path(__file__).resolve().parents[2] / "src"
    files = [*(root / "lab" / "weekly").glob("*.py"), root / "lab" / "notify.py", root / "lab" / "notify_events.py",
             root / "lab" / "ledger" / "verdicts.py", root / "api" / "report_routes.py"]
    for f in files:
        text = f.read_text()
        imports = [ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any("trading" in ln for ln in imports), f
        assert "/fapi/v1/order" not in text and "telegram" not in text.lower().replace("no telegram", ""), f


# ── notification copy: one vocabulary, exchange-style numbers, WIB ─────────

def test_notification_formatters():
    ne = notify_events
    assert ne._signed(1234.5) == "+1,234.50" and ne._signed(-8.25) == "−8.25" and ne._signed(-0.001) == "0.00"
    assert ne._pct(None) == "tidak tersedia" and ne._pct(12.5) == "+12.50%"
    assert [ne._px(v) for v in (2000, 150, 1.5, 0.00001234)] == ["2,000.00", "150.00", "1.50", "0.00001234"]
    assert ne._wib("2026-11-09T00:00:00Z")[1] == "9 Nov 07:00 WIB"
    assert ne._wib("2026-12-31T20:00:00Z")[1] == "1 Jan 03:00 WIB"
    assert ne._strategy("rosyade_family") == "Rosyade" and ne._strategy("new_thing") == "New thing"
    assert ne._signal_type("tier_a") == "Tier A" and ne._signal_type("donchian_breakout_1d") == "Donchian breakout 1 hari"
    assert ne._tf("4h") == "4 jam" and ne._tf("15m") == "15 menit"
    assert ne._exit("hard_sl") == "kena batal jika (SL)" and ne._exit("strategy_exit:flat").startswith("strategi keluar")
    assert ne._exit(None) is None


def test_report_ready_across_months(conn):
    i = notify_events.report_ready(conn, "2026-W49", "2026-11-30T00:00:00Z", "2026-12-07T00:00:00Z")
    n = _types(conn, "report")
    assert i and n[0]["title"] == "Laporan mingguan siap: 30 Nov – 7 Des"
    assert notify_events.report_ready(conn, "2026-W49", "2026-11-30T00:00:00Z", "2026-12-07T00:00:00Z") is None


RAW_CODES = ("PASS", "FAIL", "rosyade_family", "Optimasi", "Validasi", "Catatan Sinyal", "hard_tp", "hard_sl",
             "Deploy ", "Scan #", "4H-ETH rosyade")


def test_notification_text_has_no_raw_codes(conn):
    rid, jid = _run(conn, verdict="FAIL")
    q.finish(conn, jid, "done")
    _, jid2 = _run(conn, mode="backtest")
    q.finish(conn, jid2, "error", "boom")
    sid = conn.execute("INSERT INTO lab_scans (template_id, mode, symbols_json, timeframes_json, created_at) "
                       "VALUES ('rosyade_family', 'optimize', '[]', '[]', ?)", (utcnow(),)).lastrowid
    q.finish(conn, _run(conn, scan_id=sid, verdict="PASS")[1], "done")
    acct, wid = _preset_watch(conn)
    p = paper.open_position(conn, account_id=acct, symbol="ETHUSDT", side="short", price=2000, sl=2100,
                            watch_id=wid, source="paper_auto")
    paper.close_position(conn, p["id"], 2100, "hard_sl")
    rows = _types(conn)
    assert len(rows) == 5
    for r in rows:
        text = f"{r['title']} {r['body'] or ''}"
        assert not any(code in text for code in RAW_CODES), text
    assert "Gagal" in rows[0]["body"] and "Uji historis cepat" in rows[1]["title"]
