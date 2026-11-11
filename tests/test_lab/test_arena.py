"""Arena Paper: small-sample stats, drift check, leaderboard, snapshot job, schedule, API.

No network, no engine: presets / watches / paper rows are inserted directly.
"""
import json
import pathlib

import pytest

from src.lab import paper
from src.lab import presets as P
from src.lab import queue as q
from src.lab.arena import jobs, report, schedule, stats
from src.lab.arena.store import has_schema
from src.lab.ledger.store import iso, kv_get, to_epoch

NOW = to_epoch("2026-11-11T18:30:00Z")
HOLDOUT = {"net_return_pct": 82.94, "profit_factor": 1.62, "max_dd_pct": -31.08, "sharpe": 1.46, "trades": 51,
           "win_rate_pct": 37.25, "start": "2025-07-06T04:00:00Z", "end": "2026-11-09T00:00:00Z",
           "mc_dd_p95_pct": -37.58, "contaminated": True, "sizing_rule": "R1_fixed_1x"}


# ── stats ──────────────────────────────────────────────────────────────────

def test_poisson_range_exact_and_small_mu():
    assert stats.poisson_range(0) == (0, 0)
    lo, hi = stats.poisson_range(0.2)
    assert lo == 0 and hi == 1                       # tiny mu: 0 or 1 entries are both unremarkable
    lo, hi = stats.poisson_range(9.0)
    assert (lo, hi) == (4, 15)                       # textbook central 95 % range for Poisson(9)


def test_binom_range_and_wilson():
    assert stats.binom_range(10, 0.3) == (0, 6)
    assert stats.binom_range(0, 0.3) == (0, 0)
    lo, hi = stats.wilson(3, 10)
    assert 0.10 < lo < 0.11 and 0.60 < hi < 0.61
    assert stats.wilson(0, 0) is None


def test_mean_ci_dd_sharpe():
    assert stats.mean_ci([1.0]) is None
    ci = stats.mean_ci([1.0, 2.0, 3.0])
    assert ci["mean"] == 2.0 and ci["lo"] < 2.0 < ci["hi"] and abs(ci["hi"] - 2.0 - 4.303 / 3 ** 0.5) < 1e-9
    assert stats.t975(200) == pytest.approx(1.972, abs=2e-3)
    assert stats.max_drawdown_pct([100, 120, 90, 130]) == pytest.approx(-25.0)
    assert stats.max_drawdown_pct([]) is None
    assert stats.sharpe_daily([100 + i for i in range(10)]) is None          # < 30 daily returns
    assert stats.sharpe_daily([100 * (1.001 + 0.002 * (i % 2)) ** i for i in range(40)]) > 0


# ── identity / expectations ───────────────────────────────────────────────

def test_family_and_base():
    assert report.sizing_family("v2_VT60", None) == "VT60"
    assert report.sizing_family("Basic_1x", None) == "1x"
    assert report.sizing_family("Opt", None) == "2x"
    assert report.sizing_family("Whatever", {"sizing_rule": "R2_vol_target_60"}) == "VT60"
    assert report.base_label("v2_VT60") == "v2" and report.base_label("Basic") == "Basic"


def test_expectations_from_preset_and_live_reference_fallback():
    bt = report.backtest_expectations({"holdout": HOLDOUT, "name": "4H-ETH-v2_1x", "live_reference": False})
    assert bt["source"] == "preset" and bt["trades"] == 51
    assert 3.0 < bt["trades_per_month"] < 3.4
    assert bt["per_trade_ret_pct"] == pytest.approx(((1.8294) ** (1 / 51) - 1) * 100)
    live = report.backtest_expectations({"holdout": None, "name": "4H-ETH-Basic", "live_reference": True})
    assert live["source"] == "research_doc" and live["trades"] == 72 and live["contaminated"]
    assert report.backtest_expectations({"holdout": None, "name": "4H-ETH-Opt", "live_reference": False}) is None
    # the fallback is copied verbatim from the committed research file
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2] / "docs/research/eth-v2/holdout-results.json")
                     .read_text())["results"]["4H-ETH-Basic"]
    ref = report.LIVE_REFERENCE_BACKTEST
    for k in ("net_return_pct", "profit_factor", "max_dd_pct", "trades", "win_rate_pct", "sharpe", "start", "end"):
        assert ref[k] == doc["holdout"][k], k
    assert ref["mc_dd_p95_pct"] == doc["monte_carlo"]["dd_p95"]


# ── fixtures: a preset with an auto-paper watch ───────────────────────────

def _preset(conn, label="v2_1x", symbol="ETHUSDT", holdout=HOLDOUT, created="2026-11-11T15:00:00Z"):
    P.ensure_schema(conn)
    pid = conn.execute(
        "INSERT INTO lab_presets (name, label, template_id, symbol, timeframe, params_json, costs_json, verdict, "
        "holdout_json, created_at) VALUES (?, ?, 'rosyade_family', ?, '4h', '{}', '{}', 'PASS', ?, ?)",
        (P.make_name("4h", symbol, label), label, symbol, json.dumps(holdout) if holdout else None, created)
    ).lastrowid
    acct = paper.create_account(conn, f"Paper {label}", 10000.0, risk_pct=100.0, leverage_max=1.0)
    conn.execute("UPDATE paper_accounts SET created_at=? WHERE id=?", (created, acct))
    wid = conn.execute(
        "INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, autopaper_account_id, "
        "autopaper_enabled, created_at) VALUES ('rosyade_family', ?, '4h', '{}', '{}', ?, 1, ?)",
        (symbol, acct, created)).lastrowid
    P.link(conn, "watch", wid, pid)
    conn.commit()
    return pid, acct, wid


def _trade(conn, acct, wid, entry_t, exit_t, win: bool, side="long"):
    pos = paper.open_position(conn, account_id=acct, symbol="ETHUSDT", side=side, price=2000.0,
                              sl=1900.0 if side == "long" else 2100.0, qty=1.0, watch_id=wid, source="paper_auto",
                              when=entry_t)
    px = (2100.0 if win else 1950.0) if side == "long" else (1900.0 if win else 2050.0)
    return paper.close_position(conn, pos["id"], px, "signal", when=exit_t)


def test_build_fresh_presets_is_honest(conn):
    _preset(conn)
    b = report.build(conn, now=NOW)
    assert len(b["rows"]) == 1
    r = b["rows"][0]
    assert r["preset"]["family"] == "1x" and r["preset"]["base"] == "ETH-v2" and r["preset"]["coin"] == "ETH"
    assert r["stats"]["n_closed"] == 0 and r["stats"]["equity"] == 10000.0 and r["stats"]["sharpe"] is None
    assert r["stats"]["return_pct"] == 0.0 and r["open_position"] is None and r["last_action"] is None
    assert r["drift"]["status"] == "belum_cukup"
    assert {c["key"]: c["status"] for c in r["drift"]["checks"]} == {
        "frequency": "belum_cukup", "win_rate": "belum_cukup", "trade_return": "belum_cukup",
        "drawdown": "belum_cukup", "avg_r": "info"}


def test_build_open_position_last_action_and_curve(conn):
    _, acct, wid = _preset(conn)
    _trade(conn, acct, wid, "2026-11-11T16:00:00Z", "2026-11-11T17:00:00Z", win=False)
    pos = paper.open_position(conn, account_id=acct, symbol="ETHUSDT", side="short", price=2000.0, sl=2100.0,
                              qty=1.0, watch_id=wid, source="paper_auto", when="2026-11-11T18:00:00Z")
    conn.execute("UPDATE paper_positions SET mark_price=1990 WHERE id=?", (pos["id"],))
    conn.commit()
    jobs.snapshot(conn, now=NOW)
    r = report.build(conn, now=NOW)["rows"][0]
    st = r["stats"]
    assert st["n_closed"] == 1 and st["n_entries"] == 2 and st["wins"] == 0 and st["n_open"] == 1
    assert r["open_position"]["side"] == "short" and r["open_position"]["unrealized_pnl"] == pytest.approx(
        (pos["entry_price"] - 1990) - pos["fees"])
    assert r["last_action"]["kind"] == "open" and r["last_action"]["side"] == "short"
    assert st["max_dd_pct"] < 0 and st["avg_r"] < 0
    c = report.curves(conn, now=NOW)["series"][0]
    ts = [p["t"] for p in c["points"]]
    assert ts == sorted(ts) and len(ts) == len(set(ts)) and c["points"][0]["equity"] == 10000.0
    assert c["points"][-1]["equity"] == pytest.approx(st["equity"])


def test_drift_flags_frequency_and_win_rate(conn):
    created = iso(NOW - 75 * 86400)                       # 75 days at ~3.2 trades/month: expect ~7.9 entries
    _, acct, wid = _preset(conn, created=created)
    r = report.build(conn, now=NOW)["rows"][0]
    chk = {c["key"]: c for c in r["drift"]["checks"]}
    assert chk["frequency"]["status"] == "menyimpang" and chk["frequency"]["observed"] == 0
    assert r["drift"]["status"] == "menyimpang"
    # 12 winners in a row against a 37 % backtest win rate: outside the binomial range
    for i in range(12):
        t0 = NOW - (70 - 5 * i) * 86400
        _trade(conn, acct, wid, iso(t0), iso(t0 + 86400), win=True)
    chk = {c["key"]: c for c in report.build(conn, now=NOW)["rows"][0]["drift"]["checks"]}
    assert chk["frequency"]["status"] == "sesuai"
    assert chk["win_rate"]["status"] == "menyimpang" and chk["win_rate"]["observed"] == 100.0
    assert chk["trade_return"]["status"] in ("sesuai", "menyimpang")      # judged, not "belum_cukup"
    assert chk["drawdown"]["status"] == "belum_cukup"                     # < 30 trades and no deep DD


def test_no_backtest_and_unlinked_accounts(conn):
    _preset(conn, label="Manual", holdout=None)
    paper.create_account(conn, "Paper manual, no preset")
    b = report.build(conn, now=NOW)
    assert len(b["rows"]) == 1
    assert b["rows"][0]["backtest"] is None and b["rows"][0]["drift"]["has_backtest"] is False


def test_build_on_empty_db_and_read_only(conn):
    assert report.build(conn, now=NOW)["rows"] == []
    assert not has_schema(conn)                            # the report never creates the snapshot table


# ── job / schedule / worker ───────────────────────────────────────────────

def test_snapshot_idempotent_per_hour(conn):
    _, acct, _ = _preset(conn)
    assert jobs.snapshot(conn, now=NOW) == 1
    assert jobs.snapshot(conn, now=NOW + 60) == 1
    rows = conn.execute("SELECT ts, equity FROM arena_equity_snapshots").fetchall()
    assert len(rows) == 1 and rows[0]["ts"] == "2026-11-11T18:00:00Z" and rows[0]["equity"] == 10000.0


def test_schedule_tick(conn):
    from src.lab.settings import get_lab_settings
    s = get_lab_settings()
    assert schedule.tick(conn, s, NOW) is None                         # no paper account yet
    _preset(conn)
    jid = schedule.tick(conn, s, NOW)
    assert jid and kv_get(conn, "arena_snapshot_hour") == "2026-11-11T18:00:00Z"
    assert schedule.tick(conn, s, NOW + 60) is None                    # same hour
    assert schedule.tick(conn, s, NOW + 3600) is None                  # previous job still queued
    conn.execute("UPDATE lab_jobs SET status='done'")
    conn.commit()
    assert schedule.tick(conn, s, NOW + 3600)


def test_worker_runner_and_scheduler_know_the_job(conn):
    from src.lab import runner
    from src.lab.worker import FAST_KINDS
    root = pathlib.Path(__file__).resolve().parents[2] / "src/lab"
    assert "arena_snapshot" in FAST_KINDS and "arena_snapshot" in (root / "runner.py").read_text()
    assert "arena.schedule" in (root / "scheduler.py").read_text()
    _preset(conn)
    jid = q.enqueue(conn, "arena_snapshot", None, {})
    conn.commit()
    assert runner.main([str(jid)]) == 0
    assert conn.execute("SELECT status FROM lab_jobs WHERE id=?", (jid,)).fetchone()[0] == "done"
    assert conn.execute("SELECT COUNT(*) FROM arena_equity_snapshots").fetchone()[0] == 1


def test_arena_never_imports_trading_or_places_orders():
    root = pathlib.Path(__file__).resolve().parents[2] / "src"
    files = [*(root / "lab" / "arena").glob("*.py"), root / "api" / "arena_routes.py"]
    for f in files:
        text = f.read_text()
        imports = [ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any("trading" in ln for ln in imports), f
        for bad in ("paper.open_position", "close_position(", "/fapi/v1/order", "telegram", "lab_alerts"):
            assert bad not in text.lower(), (f, bad)


# ── API ────────────────────────────────────────────────────────────────────

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


def test_api_admin_only_and_shape(api, conn):
    assert api("u-plain").get("/api/v1/lab/arena").status_code == 403
    assert api("u-plain").get("/api/v1/lab/arena/curves").status_code == 403
    _preset(conn)
    r = api("u-admin").get("/api/v1/lab/arena")
    assert r.status_code == 200
    body = r.json()
    assert body["review_min_trades"] == 30 and len(body["rows"]) == 1
    row = body["rows"][0]
    assert {"preset", "account", "watch", "stats", "open_position", "last_action", "backtest", "drift"} <= set(row)
    assert "curve" not in row and "trade_rets_pct" not in row["stats"]
    c = api("u-admin").get("/api/v1/lab/arena/curves").json()
    assert len(c["series"]) == 1 and c["series"][0]["points"][0]["equity"] == 10000.0
