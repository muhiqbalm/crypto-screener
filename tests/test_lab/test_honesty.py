import sqlite3

import pytest

from src.lab import db, honesty as h


def _inputs(**kw):
    base = dict(oos_profit_factor=1.5, oos_net_return_pct=20.0, oos_trades=40, mc_dd_p95_pct=-35.0,
                stress_net_return_pct=5.0, unstable_params=1, liquidations=0)
    base.update(kw)
    return h.HonestyInputs(**base)


def test_all_pass():
    checks = h.build_checks(_inputs())
    assert len(checks) == 7
    assert all(c["passed"] for c in checks)
    assert h.verdict(checks) == "PASS"
    for c in checks:
        assert set(c) == {"name", "label", "value", "threshold", "passed"}


@pytest.mark.parametrize("kw", [
    {"oos_profit_factor": 1.19},
    {"oos_net_return_pct": 0.0},
    {"oos_net_return_pct": -3.0},
    {"oos_trades": 29},
    {"mc_dd_p95_pct": -50.0},
    {"stress_net_return_pct": -0.1},
    {"unstable_params": 4},
    {"liquidations": 1},
    {"oos_profit_factor": None},
    {"oos_trades": None},
])
def test_any_failure_fails(kw):
    checks = h.build_checks(_inputs(**kw))
    assert h.verdict(checks) == "FAIL"
    assert sum(not c["passed"] for c in checks) == 1


def test_infinite_pf_is_pass_but_finite_value():
    checks = h.build_checks(_inputs(oos_profit_factor=float("inf")))
    pf = next(c for c in checks if c["name"] == "oos_profit_factor")
    assert pf["passed"] and pf["value"] == 999.0


def test_missing_checks_fail():
    checks = [c for c in h.build_checks(_inputs()) if c["name"] != "cost_stress"]
    assert h.verdict(checks) == "FAIL"


def test_thresholds_are_hard_coded():
    assert h.THRESHOLDS["oos_pf_min"] == 1.2
    assert h.THRESHOLDS["min_oos_trades"] == 30
    assert h.THRESHOLDS["cost_stress_mult"] == 2.0
    assert h.HOLDOUT_FRACTION == 0.2
    assert h.HONESTY_VERSION


def test_verdict_immutable(conn):
    rid = conn.execute(
        "INSERT INTO lab_runs (template_id, symbol, timeframe, mode, params_json, costs_json, created_at) "
        "VALUES ('rosyade_family','ETHUSDT','4h','validate','{}','{}',?)", (db.utcnow(),)).lastrowid
    conn.execute("UPDATE lab_runs SET verdict='FAIL', checks_json='[]' WHERE id=?", (rid,))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_runs SET verdict='PASS' WHERE id=?", (rid,))
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_runs SET checks_json='[{\"passed\":true}]' WHERE id=?", (rid,))
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM lab_runs WHERE id=?", (rid,))
    conn.rollback()
    # other columns stay writable
    conn.execute("UPDATE lab_runs SET status='done' WHERE id=?", (rid,))
    assert conn.execute("SELECT verdict FROM lab_runs WHERE id=?", (rid,)).fetchone()[0] == "FAIL"


# ── holdout lock ────────────────────────────────────────────────────────

def test_proposed_holdout_is_last_20pct_floored_to_bar():
    hs = h.proposed_holdout_start("2023-01-01", "2023-11-01", 14400)
    # 304 days * 0.8 = 243.2 days -> 2023-09-01T04:48 -> floored to 04:00
    assert hs == "2023-09-01T04:00:00Z"


def test_holdout_lock_persists_and_cannot_move(conn):
    hs1 = h.resolve_holdout(conn, "rosyade_family", "ETHUSDT", "4h", "2023-01-01", "2026-03-12", 14400)
    # a later run with a longer range must reuse the same boundary (no peeking by moving the end)
    hs2 = h.resolve_holdout(conn, "rosyade_family", "ETHUSDT", "4h", "2022-01-01", "2026-11-01", 14400)
    assert hs1 == hs2
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE holdout_locks SET holdout_start='2020-01-01T00:00:00Z'")
    conn.rollback()
    # other symbol / tf get their own lock
    hs3 = h.resolve_holdout(conn, "rosyade_family", "ETHUSDT", "1h", "2024-01-01", "2026-03-12", 3600)
    assert hs3 != hs1


def test_holdout_range_errors(conn):
    hs = h.resolve_holdout(conn, "rosyade_family", "BTCUSDT", "4h", "2023-01-01", "2026-01-01", 14400)
    with pytest.raises(h.HoldoutError):  # ends before the holdout
        h.resolve_holdout(conn, "rosyade_family", "BTCUSDT", "4h", "2023-01-01", hs, 14400)
    with pytest.raises(h.HoldoutError):  # starts inside the holdout
        h.resolve_holdout(conn, "rosyade_family", "BTCUSDT", "4h", "2025-12-01", "2026-06-01", 14400)


def test_holdout_touches_counted(conn):
    h.resolve_holdout(conn, "rosyade_family", "ETHUSDT", "4h", "2023-01-01", "2026-03-12", 14400)
    assert h.touch_holdout(conn, "rosyade_family", "ETHUSDT", "4h") == 1
    assert h.touch_holdout(conn, "rosyade_family", "ETHUSDT", "4h") == 2


def test_optimizer_guard_rejects_holdout_bars():
    h.assert_dev_only(["2025-01-01T00:00:00Z", "2025-06-30T20:00:00Z"], "2025-07-01T00:00:00Z")
    with pytest.raises(h.HoldoutError):
        h.assert_dev_only(["2025-07-01T00:00:00Z"], "2025-07-01T00:00:00Z")
