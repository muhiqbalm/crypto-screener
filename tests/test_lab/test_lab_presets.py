"""Preset library: seeding the read-only live reference, save-from-run, best-per-cell, links."""
import json

import pytest

from src.lab import db, presets as pr
from src.lab.templates import get_template
from tests.test_lab.test_lab_api import RUN, client_for  # noqa: F401  (fixture)
from tests.test_lab.test_lab_planning import _done_run


@pytest.fixture
def admin(client_for):
    return client_for("u-admin")


def test_names_and_labels():
    assert pr.make_name("4h", "ETHUSDT", "Basic") == "4H-ETH-Basic"
    assert pr.make_name("1h", "BTCUSDT", "Opt1") == "1H-BTC-Opt1"
    assert pr.make_name("15m", "1000PEPEUSDT", "A") == "15M-1000PEPE-A"
    for bad in ("", "has space", "x" * 25, "-lead", "a/b"):
        with pytest.raises(pr.PresetError):
            pr.check_label(bad)


def test_seed_live_reference_once_and_readonly(conn):
    pr.seed(conn)
    pr.seed(conn)
    rows = pr.list_presets(conn)
    assert [p["name"] for p in rows] == ["4H-ETH-Basic"]
    live = rows[0]
    assert live["readonly"] and live["live_reference"] and live["symbol"] == "ETHUSDT" and live["timeframe"] == "4h"
    assert live["params"] == get_template("rosyade_family").defaults()
    with pytest.raises(pr.PresetError) as e:
        pr.update(conn, live["id"], notes="x")
    assert e.value.status == 403
    with pytest.raises(pr.PresetError):
        pr.archive(conn, live["id"])
    # the DB itself refuses too (trigger), not just the API
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_presets SET params_json='{}' WHERE id=?", (live["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM lab_presets WHERE id=?", (live["id"],))


def test_create_from_run_snapshots_evidence(conn):
    rid = _done_run(conn, mode="optimize", tf="1h", symbol="BTCUSDT", trials_done=90,
                    oos={"profit_factor": 1.7, "net_return_pct": 12.0, "trades": 44, "costs": {"cost_drag_pct": 5.0}})
    conn.execute("UPDATE lab_runs SET best_params_json=?, params_json=? WHERE id=?",
                 (json.dumps({"swing_len": 7}), json.dumps({"swing_len": 5}), rid))
    conn.commit()
    p = pr.create_from_run(conn, rid, "Opt1", "first try")
    assert p["name"] == "1H-BTC-Opt1" and p["params"] == {"swing_len": 7}   # optimize -> best params
    assert p["verdict"] == "PASS" and p["source_run_id"] == rid and p["source_mode"] == "optimize"
    assert p["holdout"]["profit_factor"] == 1.7 and p["holdout"]["cost_drag_pct"] == 5.0
    assert p["snooping"] == {"runs": 1, "timeframes": 1, "trials": 90, "holdout_touches": 0}
    with pytest.raises(pr.PresetError) as e:
        pr.create_from_run(conn, rid, "Opt1")
    assert e.value.status == 409
    pr.archive(conn, p["id"])
    assert pr.create_from_run(conn, rid, "Opt1")["name"] == "1H-BTC-Opt1"   # name free again after delete
    assert pr.names_for_runs(conn, [rid])[rid]["saved_as"] == ["1H-BTC-Opt1"]


def test_unfinished_or_universal_run_cannot_be_preset(conn):
    rid = conn.execute("INSERT INTO lab_runs (template_id, symbol, timeframe, mode, status, params_json, costs_json,"
                       " created_at) VALUES ('rosyade_family','ETHUSDT','4h','validate','running','{}','{}',?)",
                       (db.utcnow(),)).lastrowid
    with pytest.raises(pr.PresetError) as e:
        pr.create_from_run(conn, rid, "X")
    assert e.value.status == 409
    uni = _done_run(conn, template="universal_v0")
    with pytest.raises(pr.PresetError):
        pr.create_from_run(conn, uni, "X")


def test_best_for_prefers_pass_never_fail(conn):
    a = _done_run(conn, tf="1h", symbol="BTCUSDT", oos={"profit_factor": 1.3, "trades": 40})
    b = _done_run(conn, tf="1h", symbol="BTCUSDT", oos={"profit_factor": 1.8, "trades": 40})
    f = _done_run(conn, tf="1h", symbol="SOLUSDT", verdict="FAIL", oos={"profit_factor": 5.0, "trades": 40})
    pa, pb = pr.create_from_run(conn, a, "A"), pr.create_from_run(conn, b, "B")
    pr.create_from_run(conn, f, "F")
    best = pr.best_for(conn, "rosyade_family", ["BTCUSDT", "SOLUSDT", "ETHUSDT"], ["1h", "4h"])
    assert best["BTCUSDT|1h"]["id"] == pb["id"] != pa["id"]
    assert best["SOLUSDT|1h"] is None                         # FAIL preset never auto-picked
    assert best["ETHUSDT|4h"]["name"] == "4H-ETH-Basic"       # live reference fallback
    assert best["ETHUSDT|1h"] is None


def test_params_match():
    assert pr.params_match({"a": 1, "b": True}, {"a": 1.0, "b": True})
    assert not pr.params_match({"a": 1}, {"a": 2})


# ── API ──────────────────────────────────────────────────────────────────

def test_api_preset_library_flow(admin, lab_env):
    lst = admin.get("/api/v1/lab/presets").json()
    live = lst[0]
    assert live["name"] == "4H-ETH-Basic" and live["readonly"] is True
    assert admin.patch(f"/api/v1/lab/presets/{live['id']}", json={"notes": "x"}).status_code == 403
    assert admin.delete(f"/api/v1/lab/presets/{live['id']}").status_code == 403

    # run from the preset with unchanged params -> linked
    r = admin.post("/api/v1/lab/runs", json={**RUN, "params": live["params"], "preset_id": live["id"]}).json()
    assert r["preset_linked"] is True
    assert admin.get(f"/api/v1/lab/runs/{r['run_id']}").json()["preset"] == {"id": live["id"], "name": "4H-ETH-Basic"}
    # changed params -> not linked (the run is no longer "the preset")
    r2 = admin.post("/api/v1/lab/runs", json={**RUN, "params": {"swing_len": 9}, "preset_id": live["id"]}).json()
    assert r2["preset_linked"] is False
    assert admin.get(f"/api/v1/lab/runs/{r2['run_id']}").json()["preset"] is None
    assert admin.post("/api/v1/lab/runs", json={**RUN, "preset_id": 999}).status_code == 404

    # manual preset + patch + delete
    m = admin.post("/api/v1/lab/presets", json={"label": "Try1", "template_id": "rosyade_family",
                                                 "symbol": "btcusdt", "timeframe": "1h", "params": {"swing_len": 6}})
    assert m.status_code == 200, m.text
    m = m.json()
    assert m["name"] == "1H-BTC-Try1" and m["params"]["swing_len"] == 6 and m["verdict"] is None
    assert admin.post("/api/v1/lab/presets", json={"label": "Try1", "template_id": "rosyade_family",
                                                    "symbol": "BTCUSDT", "timeframe": "1h"}).status_code == 409
    assert admin.post("/api/v1/lab/presets", json={"label": "bad label", "template_id": "rosyade_family",
                                                    "symbol": "BTCUSDT", "timeframe": "1h"}).status_code == 422
    assert admin.post("/api/v1/lab/presets", json={"label": "X", "template_id": "rosyade_family",
                                                    "symbol": "BTCUSDT", "timeframe": "1h",
                                                    "params": {"swing_len": -5}}).status_code == 422
    pm = admin.patch(f"/api/v1/lab/presets/{m['id']}", json={"label": "Try2", "notes": "n"}).json()
    assert pm["name"] == "1H-BTC-Try2" and pm["notes"] == "n"
    assert admin.delete(f"/api/v1/lab/presets/{m['id']}").json() == {"id": m["id"], "deleted": True}
    assert admin.get(f"/api/v1/lab/presets/{m['id']}").status_code == 404

    # save from a finished run
    c = db.connect()
    try:
        rid = _done_run(c, tf="1h", symbol="BTCUSDT")
    finally:
        c.close()
    sp = admin.post(f"/api/v1/lab/runs/{rid}/preset", json={"label": "Opt1"}).json()
    assert sp["name"] == "1H-BTC-Opt1" and sp["verdict"] == "PASS" and sp["holdout"]["profit_factor"] == 1.5
    assert admin.post(f"/api/v1/lab/runs/{r['run_id']}/preset", json={"label": "Q"}).status_code == 409
    lb = admin.get("/api/v1/lab/leaderboard").json()
    assert lb["rows"][0]["saved_as"] == ["1H-BTC-Opt1"]
    assert [p["name"] for p in admin.get("/api/v1/lab/presets?symbol=btcusdt").json()] == ["1H-BTC-Opt1"]


def test_api_scan_with_presets(admin, lab_env):
    c = db.connect()
    try:
        rid = _done_run(c, tf="1h", symbol="BTCUSDT")
        c.execute("UPDATE lab_runs SET params_json=? WHERE id=?", (json.dumps({"swing_len": 8}), rid))
        c.commit()
    finally:
        c.close()
    p = admin.post(f"/api/v1/lab/runs/{rid}/preset", json={"label": "Opt1"}).json()
    best = admin.get("/api/v1/lab/presets/best?template_id=rosyade_family&symbols=BTCUSDT,ETHUSDT"
                     "&timeframes=1h,4h").json()["cells"]
    assert best["BTCUSDT|1h"]["name"] == "1H-BTC-Opt1" and best["ETHUSDT|4h"]["name"] == "4H-ETH-Basic"
    assert best["BTCUSDT|4h"] is None
    sc = admin.post("/api/v1/lab/scans", json={
        "template_id": "rosyade_family", "symbols": ["BTCUSDT", "ETHUSDT"], "timeframes": ["1h", "4h"],
        "mode": "validate", "use_best_presets": True, "params": {"swing_len": 4}}).json()
    rows = {(x["symbol"], x["timeframe"]): x for x in admin.get(f"/api/v1/lab/scans/{sc['scan_id']}").json()["rows"]}
    assert rows[("BTCUSDT", "1h")]["preset"]["name"] == "1H-BTC-Opt1"
    assert rows[("ETHUSDT", "4h")]["preset"]["name"] == "4H-ETH-Basic"
    assert rows[("BTCUSDT", "4h")]["preset"] is None
    params = lambda k: admin.get(f"/api/v1/lab/runs/{rows[k]['run_id']}").json()["params"]["swing_len"]  # noqa: E731
    assert params(("BTCUSDT", "1h")) == 8 and params(("BTCUSDT", "4h")) == 4
    fixed = admin.post("/api/v1/lab/scans", json={
        "template_id": "rosyade_family", "symbols": ["SOLUSDT"], "timeframes": ["1h"], "mode": "validate",
        "preset_id": p["id"]}).json()
    row = admin.get(f"/api/v1/lab/scans/{fixed['scan_id']}").json()["rows"][0]
    assert row["preset"]["name"] == "1H-BTC-Opt1"


def test_api_watch_from_preset_with_autopaper(admin):
    live = admin.get("/api/v1/lab/presets").json()[0]
    assert admin.post(f"/api/v1/lab/presets/{live['id']}/watch", json={"autopaper_account_id": 42}).status_code == 404
    acct = admin.post("/api/v1/lab/paper/accounts", json={"name": "p1"}).json()["id"]
    w = admin.post(f"/api/v1/lab/presets/{live['id']}/watch", json={"autopaper_account_id": acct}).json()
    assert w["autopaper"] == {"account_id": acct, "enabled": True}
    watches = admin.get("/api/v1/lab/watches").json()
    mine = next(x for x in watches if x["id"] == w["watch_id"])
    assert mine["symbol"] == "ETHUSDT" and mine["timeframe"] == "4h" and mine["autopaper"]["enabled"] is True
    plain = admin.post(f"/api/v1/lab/presets/{live['id']}/watch", json={}).json()
    assert plain["autopaper"] is None
    assert admin.get(f"/api/v1/lab/presets/{live['id']}").json()["usage"]["watches"] == 2


def test_preset_endpoints_admin_only(client_for):
    c = client_for("u-plain")
    for path in ("/api/v1/lab/presets", "/api/v1/lab/presets/1",
                 "/api/v1/lab/presets/best?template_id=x&symbols=A&timeframes=4h"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/v1/lab/presets/1/watch", json={}).status_code == 403
    assert c.post("/api/v1/lab/runs/1/preset", json={"label": "A"}).status_code == 403
    assert c.delete("/api/v1/lab/presets/1").status_code == 403
