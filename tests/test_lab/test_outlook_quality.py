"""Skor kualitas sinyal (src/lab/outlook/quality.py): the rule, the stored letter and the graded grade."""
import pytest

from src.lab.db import utcnow
from src.lab.outlook import quality as Q
from src.lab.outlook import store as S

from .test_lab_api import client_for  # noqa: F401  (pytest fixture)
from .test_outlook import CALIB, _call, _row, _st, _store_row, _strategy

MOM_TERUJI = {"momentum_1h": {"verdict": "teruji", "searah": {"mean_r": 0.054, "n_pos": 6387},
                              "berlawanan": {"mean_r": -0.112, "n_pos": 340}},
              "tren_1d": {"verdict": "belum_terbukti", "searah": {"mean_r": 0.05, "n_pos": 4400},
                          "berlawanan": {"mean_r": 0.06, "n_pos": 1400}}}
MTF_MOM_UP = {"tren_1d": {"direction": -1, "dist_pct": -6.0, "slope_pct": -1.2},
              "momentum_1h": {"direction": 1, "ret_24h_pct": 2.0}}
CAL_FRESH = {**CALIB, "buckets": {**CALIB["buckets"],
                                  "lolos_uji|short|*|baru": _st(120, 0.16, 0.07),
                                  "gagal_uji|short|*|baru": _st(300, 0.15, 0.08),
                                  "pool|short|*|baru": _st(3516, 0.1426, 0.0827)}}


# ── the rule ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n, mean, lo, want", [
    (3435, 0.14, 0.079, "A"),      # strong, wide sample
    (2941, 0.077, 0.048, "B"),     # positive range, but its lower end is under +0.05R
    (81, 0.252, 0.0043, "B"),      # positive range from few positions
    (60, 0.40, 0.12, "B"),         # a high lower bound still needs >= 100 positions for A
    (2832, 0.027, -0.035, "C"),    # average positive, range includes zero
    (12, 0.90, 0.30, "C"),         # 12 cases never grade like 3,000
    (74, -0.025, -0.23, "D"),      # no edge
])
def test_base_grade_uses_the_lower_end_of_the_range_and_the_sample_size(n, mean, lo, want):
    g, why = Q.base_grade(_st(n, mean, lo))
    assert g == want and why


def test_base_grade_without_data():
    assert Q.base_grade(None)[0] is None
    assert Q.base_grade({"n_pos": 0})[0] is None


def test_outcome_text_reads_like_the_ceo_example():
    ev = Q.evidence({"key": "belum_diuji|short|*|baru", "stats": {
        "n_cases": 3435, "n_pos": 3435, "p_tp": 0.1421, "p_sl": 0.4873, "p_batal": 0.368, "p_expired": 0.0026,
        "mean_r": 0.14, "lo95_r": 0.079, "win_rate": 0.33}})
    assert ev["scope"] == "strategi_ini" and ev["half_r"] == pytest.approx(0.061) and ev["hi95_r"] == pytest.approx(0.201)
    assert Q.outcome_text(ev) == ("Dari 3,435 kasus serupa: untung di target 14% · rugi di SL 49% · "
                                  "ditutup strategi 37% · rata-rata +0.14R (rentang ±0.06R).")
    run = Q.evidence({"key": "pool|short|*|berjalan", "stats": {
        "n_cases": 25205, "n_pos": 2906, "p_tp": 0.19, "p_sl": 0.26, "p_batal": 0.53, "p_expired": 0.02,
        "mean_r": 0.0294, "lo95_r": -0.0315}})
    assert run["scope"] == "semua_strategi"
    assert Q.outcome_text(run).startswith("Dari 25,205 kasus serupa (2,906 posisi berbeda): ")
    assert "habis waktu 2%" in Q.outcome_text(run) and "rata-rata +0.03R (rentang ±0.06R)" in Q.outcome_text(run)


# ── a row ────────────────────────────────────────────────────────────────

def test_fresh_call_with_strong_evidence_is_A_and_shows_its_parts():
    row = _row(_strategy("short", fresh=True), calib=CAL_FRESH, lifts=MOM_TERUJI)
    q = Q.grade(row)
    assert q["grade"] == "A" and q["base"] == "A" and q["rank"] == 4 and q["label"] == "Bukti kuat"
    assert q["evidence"]["key"] == "lolos_uji|short|*|baru" and q["outcome_text"].startswith("Dari 600 kasus serupa")
    mom = next(c for c in q["checks"] if c["key"] == "momentum_1h")
    assert mom["agree"] == 1 and mom["proven"] and mom["effect"] == 0 and mom["source"] == "simulasi historis"
    tren = next(c for c in q["checks"] if c["key"] == "tren_1d")
    assert tren["proven"] is False and tren["effect"] == 0          # unproven factors never count
    assert q["live"] == {"key": "lolos_uji|short|baru", "n_done": 0, "n_pos": 0, "mean_r": None, "lo95_r": None,
                         "hi95_r": None, "win_rate": None, "enough": False, "need_pos": 20, "negative": False}
    assert q["adjustments"] == [] and q["summary"].startswith("A · Bukti kuat")


def test_proven_factor_against_the_call_lowers_one_step_unproven_never():
    up = _row(_strategy("short", fresh=True), calib=CAL_FRESH, lifts=MOM_TERUJI, mtf=MTF_MOM_UP)
    q = Q.grade(up)
    assert q["base"] == "A" and q["grade"] == "B"
    assert q["adjustments"][0]["kind"] == "faktor" and "Momentum 1H (simulasi historis)" in q["adjustments"][0]["text"]
    lifts_unproven = {**MOM_TERUJI, "momentum_1h": {**MOM_TERUJI["momentum_1h"], "verdict": "belum_terbukti"}}
    q2 = Q.grade(_row(_strategy("short", fresh=True), calib=CAL_FRESH, lifts=lifts_unproven, mtf=MTF_MOM_UP))
    assert q2["grade"] == "A" and q2["adjustments"] == []


def test_catatan_sinyal_terbukti_against_the_call_lowers_one_step():
    # screener BEARISH with a 'terbukti' track record against a LONG call
    cal = {**CAL_FRESH, "buckets": {**CAL_FRESH["buckets"], "lolos_uji|long|*|baru": _st(500, 0.12, 0.06)}}
    row = _row(_strategy("long", fresh=True, sl=1950.0, tp=2400.0), calib=cal,
               mtf={"tren_1d": {"direction": 1, "dist_pct": 2.0, "slope_pct": 0.4},
                    "momentum_1h": {"direction": 1, "ret_24h_pct": 1.0}}, lifts=MOM_TERUJI)
    q = Q.grade(row)
    scr = next(c for c in q["checks"] if c["key"] == "screener")
    assert scr["agree"] == -1 and scr["proven"] and scr["source"] == "Catatan Sinyal" and scr["effect"] == -1
    assert q["base"] == "A" and q["grade"] == "B"


def test_negative_live_record_lowers_and_steps_are_capped_at_two():
    row = _row(_strategy("short", fresh=True), calib=CAL_FRESH, lifts=MOM_TERUJI, mtf=MTF_MOM_UP)
    live = {"lolos_uji|short|baru": {"n_cases": 30, "n_pos": 25, "mean_r": -0.4, "lo95_r": -0.7, "hi95_r": -0.1}}
    q = Q.grade(row, live)
    assert [a["kind"] for a in q["adjustments"]] == ["faktor", "live"] and q["grade"] == "C"
    assert q["live"]["negative"] and q["live"]["enough"]
    few = {"lolos_uji|short|baru": {"n_cases": 30, "n_pos": 12, "mean_r": -0.9, "lo95_r": -1.5, "hi95_r": -0.3}}
    assert Q.grade(row, few)["grade"] == "B"                         # 12 live positions are not enough to count


def test_failed_preset_is_capped_at_C_and_no_letter_without_a_usable_call():
    q = Q.grade(_row(_strategy("short", fresh=True, verdict="FAIL"), calib=CAL_FRESH))
    assert q["base"] == "A" and q["grade"] == "C" and q["adjustments"][-1]["kind"] == "batas"
    seen = Q.grade(_row(_strategy("short", fresh=True, contaminated=True), calib=CAL_FRESH))   # holdout seen in research
    assert seen["base"] == "A" and seen["grade"] == "B" and "tercemar" in seen["adjustments"][-1]["text"]
    assert Q.grade(_row(_strategy(None, preset=False))) is None                       # FLAT: no call, no grade
    stale = Q.grade(_row(_strategy("short", fresh=True), calib=CAL_FRESH, now="2026-11-12T08:00:00Z"))
    assert stale["grade"] is None and "basi" in stale["why_none"] and stale["label"] == "Tidak dinilai"
    beyond = _row(_strategy("short", fresh=True, sl=2000.0), calib=CAL_FRESH)          # price 2074 > SL of a short
    assert Q.grade(beyond)["grade"] is None and "SL" in Q.grade(beyond)["why_none"]
    nocal = Q.grade(_row(_strategy("short", fresh=True), calib=None))
    assert nocal["grade"] is None and "kalibrasi" in nocal["why_none"]
    assert Q.letter(nocal) == "-" and Q.letter(None) is None and Q.letter(Q.grade(_row(
        _strategy("short", fresh=True), calib=CAL_FRESH))) == "A"


# ── stored calls ─────────────────────────────────────────────────────────

def test_old_calls_table_gets_the_columns_additively(conn):
    conn.executescript("""
        DROP TABLE IF EXISTS lab_outlook_calls;
        CREATE TABLE lab_outlook_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, bar TEXT NOT NULL,
          bar_close TEXT NOT NULL, computed_at TEXT NOT NULL, side TEXT, keyakinan TEXT, keyakinan_basis TEXT, cls TEXT,
          align TEXT, fase TEXT, strategy TEXT, template_id TEXT, timeframe TEXT, strategy_entry_time TEXT, price REAL,
          sl REAL, tp REAL, horizon_bars INTEGER, rr REAL, ev_r REAL, call_json TEXT, status TEXT, r_net REAL,
          r_gross REAL, mfe_r REAL, mae_r REAL, exit_price REAL, bars_to_resolve INTEGER, ambiguous INTEGER,
          resolved_at TEXT, evaluated_at TEXT, UNIQUE (symbol, bar));
        INSERT INTO lab_outlook_calls (symbol, bar, bar_close, computed_at, side, status) VALUES
          ('ETHUSDT', '2026-11-11T08:00:00Z', '2026-11-11T12:00:00Z', 'x', 'short', 'open');""")
    S._migrated.clear()
    S.ensure_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(lab_outlook_calls)")}
    assert {"kualitas", "kualitas_json"} <= cols
    assert conn.execute("SELECT COUNT(*) FROM lab_outlook_calls").fetchone()[0] == 1
    S.ensure_schema(conn)   # idempotent
    S.save_call(conn, _call(kualitas="B", kualitas_json={"grade": "B", "basis": "saat_panggilan"}))
    conn.commit()
    got = S.calls_for(conn, "ETHUSDT")
    assert got[0]["kualitas"] == "B" and got[0]["kualitas_info"] == {"grade": "B", "basis": "saat_panggilan"}


def test_migration_adds_only_what_is_missing_and_a_read_only_reader_never_breaks(conn, tmp_path):
    import sqlite3
    conn.executescript("DROP TABLE IF EXISTS lab_outlook_calls;")
    S._migrated.clear()
    S.ensure_schema(conn)
    conn.execute("ALTER TABLE lab_outlook_calls DROP COLUMN kualitas_json")     # half-migrated database
    conn.commit()
    S._migrated.clear()
    S.ensure_schema(conn)
    assert {"kualitas", "kualitas_json"} <= {r[1] for r in conn.execute("PRAGMA table_info(lab_outlook_calls)")}
    old = tmp_path / "old.db"
    w = sqlite3.connect(old)
    w.executescript("CREATE TABLE lab_outlook (symbol TEXT PRIMARY KEY, computed_at TEXT NOT NULL, last_bar TEXT, "
                    "row_json TEXT, detail_json TEXT, error TEXT);"
                    "CREATE TABLE lab_outlook_calls (id INTEGER PRIMARY KEY, symbol TEXT, bar TEXT, bar_close TEXT, "
                    "computed_at TEXT, side TEXT, cls TEXT, fase TEXT, strategy TEXT, strategy_entry_time TEXT, "
                    "status TEXT, r_net REAL, mfe_r REAL, bars_to_resolve INTEGER, price REAL, resolved_at TEXT, "
                    "call_json TEXT);"
                    "INSERT INTO lab_outlook_calls (symbol, bar, bar_close, side, status) "
                    "VALUES ('ETHUSDT', 'b', 'c', 'short', 'open');")
    w.commit()
    w.close()
    ro = sqlite3.connect(f"file:{old}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    S.ensure_schema(ro)                                                            # cannot ALTER: no crash
    sb = Q.scoreboard(ro)
    assert sb["n_calls"] == 1 and sb["n_ungraded"] == 1 and sb["by_grade"]["A"]["n_calls"] == 0
    ro.close()


def test_a_grading_bug_never_hides_the_coin_and_an_unmigrated_table_still_records_calls(conn, monkeypatch):
    def boom(*a, **k):
        raise ValueError("bug")
    monkeypatch.setattr(Q, "grade", boom)
    assert Q.safe_grade(_row(_strategy("short", fresh=True), calib=CAL_FRESH)) is None
    monkeypatch.setattr(Q, "live_groups", boom)
    assert Q.live_groups_safe(conn) == {}
    monkeypatch.undo()
    conn.executescript("DROP TABLE IF EXISTS lab_outlook_calls;")
    S._migrated.clear()
    S.ensure_schema(conn)
    conn.execute("ALTER TABLE lab_outlook_calls DROP COLUMN kualitas_json")
    conn.execute("ALTER TABLE lab_outlook_calls DROP COLUMN kualitas")
    conn.commit()
    S._migrated.add(conn.execute("PRAGMA database_list").fetchone()[2])          # migration "already done" (stale cache)
    S.save_call(conn, _call(kualitas="A", kualitas_json={"grade": "A"}))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM lab_outlook_calls").fetchone()[0] == 1


def _resolve(conn, sym, status, r, bar):
    cid = conn.execute("SELECT id FROM lab_outlook_calls WHERE symbol=? AND bar=?", (sym, bar)).fetchone()[0]
    S.set_outcome(conn, cid, {"status": status, "r_net": r, "bars": 3, "resolved_at": "2026-11-13T00:00:00Z"},
                  "2026-11-13T00:00:00Z")


def test_backfill_grades_old_calls_with_the_calibration_in_force_only(conn):
    cal = {**CAL_FRESH, "computed_at": "2026-11-12T09:00:00Z",
           "factor_lift": {"pool": {"momentum_1h": {"verdict": "teruji"}, "tren_1d": {"verdict": "belum_terbukti"}}}}
    common = dict(cls="belum_diuji", fase="baru", strategy="Rosyade default 4H")
    S.save_call(conn, _call(sym="ADAUSDT", bar="2026-11-12T08:00:00Z", computed_at="2026-11-12T12:01:00Z",
                            call_json={"dirs": {"tren_1d": -1, "momentum_1h": -1, "regime_btc": 0}}, **common))
    S.save_call(conn, _call(sym="OPUSDT", bar="2026-11-12T08:00:00Z", computed_at="2026-11-12T12:02:00Z",
                            call_json={"dirs": {"tren_1d": -1, "momentum_1h": 1, "regime_btc": 0}}, **common))
    S.save_call(conn, _call(sym="BTCUSDT", bar="2026-11-12T04:00:00Z", computed_at="2026-11-12T08:01:00Z",
                            call_json={"dirs": {}}, **common))                     # before the calibration
    S.save_call(conn, _call(sym="SOLUSDT", bar="2026-11-12T08:00:00Z", computed_at="2026-11-12T12:03:00Z",
                            status="invalid", call_json={}, **common))
    conn.commit()
    assert Q.backfill(conn, cal) == 3
    got = {r["symbol"]: dict(r) for r in conn.execute("SELECT symbol, kualitas, kualitas_json FROM lab_outlook_calls")}
    assert got["ADAUSDT"]["kualitas"] == "A" and got["OPUSDT"]["kualitas"] == "B"   # momentum 1H against: one step
    assert got["BTCUSDT"]["kualitas"] is None and got["SOLUSDT"]["kualitas"] == "-"
    info = S.loads(got["OPUSDT"]["kualitas_json"])
    assert info["basis"] == "dihitung_ulang" and info["against"] == ["momentum_1h"] and info["partial"]
    assert Q.backfill(conn, cal) == 0                                              # once only
    assert Q.backfill(conn, None) == 0


def test_scoreboard_counts_by_letter_says_when_data_is_too_thin_and_keeps_simulation_apart(conn):
    for k, (sym, g) in enumerate([("ADAUSDT", "A"), ("OPUSDT", "A"), ("BTCUSDT", "C"), ("ETHUSDT", "D")]):
        S.save_call(conn, _call(sym=sym, bar="2026-11-12T08:00:00Z", kualitas=g,
                                kualitas_json={"grade": g, "basis": "saat_panggilan"},
                                strategy_entry_time=f"2026-11-1{k}T00:00:00Z"))
    S.save_call(conn, _call(sym="SUIUSDT", bar="2026-11-12T08:00:00Z", kualitas="-", kualitas_json={"basis": "dihitung_ulang"}))
    S.save_call(conn, _call(sym="LTCUSDT", bar="2026-11-12T08:00:00Z"))            # stored before grading existed
    conn.commit()
    _resolve(conn, "ADAUSDT", "tp", 1.4, "2026-11-12T08:00:00Z")
    _resolve(conn, "BTCUSDT", "sl", -1.05, "2026-11-12T08:00:00Z")
    conn.commit()
    cal = {"split": "2024-07-01T00:00:00Z", "computed_at": "2026-11-12T09:00:00Z", "fase_split": {
        "sebelum": {"short|baru": _st(1529, 0.1608, 0.0702), "long|baru": _st(1655, 0.0606, 0.0201),
                    "short|berjalan": _st(1211, 0.062, -0.0305)},
        "sesudah": {"short|baru": _st(1987, 0.1286, 0.0488, n_cases=1987),
                    "long|baru": _st(1286, 0.0985, 0.0564, n_cases=1286),
                    "short|berjalan": _st(1695, 0.0021, -0.0787, n_cases=13727)}}}
    sb = Q.scoreboard(conn, cal)
    a = sb["by_grade"]["A"]
    assert a["n_calls"] == 2 and a["n_done"] == 1 and a["n_open"] == 1 and a["mean_r"] == pytest.approx(1.4)
    assert a["enough"] is False and a["verdict"] == "belum_cukup" and sb["need_pos"] == 20
    assert sb["by_grade"]["C"]["mean_r"] == pytest.approx(-1.05) and sb["by_grade"]["B"]["n_calls"] == 0
    assert sb["n_graded"] == 4 and sb["n_no_letter"] == 1 and sb["n_ungraded"] == 1 and sb["n_backfilled"] == 1
    assert sb["n_done"] == 2 and sb["n_pos_done"] == 2 and sb["enough_any"] is False
    assert sb["first_graded"] == "2026-11-11T16:00:00Z" and len(sb["recent"]) == 5     # bar close of the first call
    sim = sb["simulasi"]
    assert [g["grade"] for g in sim["groups"]] == ["A", "B", "C"] and "sebelum 1 Jul 2024" in sim["note"]
    assert sim["by_grade"]["A"]["mean_r"] == pytest.approx(0.1286)
    assert Q.sim_check(None) is None and Q.sim_check({"fase_split": {}}) is None


def test_scoreboard_verdicts_once_enough_positions():
    def v(n_pos, mean, lo, hi):
        return Q._verdict({"n_pos": n_pos, "mean_r": mean, "lo95_r": lo, "hi95_r": hi})
    assert v(19, 0.5, 0.2, 0.8) == "belum_cukup"
    assert v(20, 0.5, 0.2, 0.8) == "positif" and v(30, -0.5, -0.8, -0.2) == "negatif"
    assert v(30, 0.1, -0.2, 0.4) == "belum_jelas"


# ── API ──────────────────────────────────────────────────────────────────

def test_api_rows_carry_the_grade_filter_sort_and_scoreboard(client_for, conn):
    from src.lab.outlook import replay as RP
    RP.save(conn, {"computed_at": "2026-11-12T03:00:00Z", "version": 1, "counts": {"cases": 10},
                   "buckets": CAL_FRESH["buckets"], "factor_lift": {"pool": {}}, "fase_split": {}})
    _store_row(conn, "ETHUSDT")                                                        # berjalan: C
    fresh = _row(_strategy("short", fresh=True), calib=CAL_FRESH)
    fresh.update({"symbol": "SOLUSDT", "coin": "SOL", "last_bar": "2026-11-11T12:00:00Z"})
    S.save_row(conn, "SOLUSDT", fresh, {"candles": []})
    flat = _row(_strategy(None, preset=False))
    flat.update({"symbol": "BTCUSDT", "coin": "BTC", "last_bar": "2026-11-11T12:00:00Z"})
    S.save_row(conn, "BTCUSDT", flat, {"candles": []})
    S.kv_set(conn, S.META_KEY, {"computed_at": utcnow()})
    conn.commit()
    c = client_for("u-plain")
    # 'now' is far after the stored bar: rows are stale -> no letter; pin freshness by patching the rows' age
    body = c.get("/api/v1/lab/outlook").json()
    by = {r["symbol"]: r for r in body["rows"]}
    assert by["BTCUSDT"]["kualitas"] is None and by["SOLUSDT"]["kualitas"]["grade"] is None
    assert "basi" in by["SOLUSDT"]["kualitas"]["why_none"] and body["kualitas_rule"]
    assert body["counts"]["kualitas"] == {"A": 0, "B": 0, "C": 0, "D": 0}
    assert c.get("/api/v1/lab/outlook?kualitas=A,B").json()["rows"] == []
    assert c.get("/api/v1/lab/outlook?kualitas=E").status_code == 422
    assert c.get("/api/v1/lab/outlook?sort=kualitas").status_code == 200
    sb = c.get("/api/v1/lab/outlook/rekam-skor").json()
    assert sb["n_calls"] == 0 and set(sb["by_grade"]) == {"A", "B", "C", "D"} and sb["simulasi"] is None
    assert client_for(None).get("/api/v1/lab/outlook/rekam-skor").status_code == 401
    d = c.get("/api/v1/lab/outlook/SOLUSDT").json()
    assert "kualitas" in d and d["kualitas_rule"]


def test_api_grades_fresh_rows_and_sorts_by_letter(client_for, conn, monkeypatch):
    from src.api import outlook_routes as OR
    monkeypatch.setattr(OR, "_now_iso", lambda: "2026-11-11T16:05:00Z")
    _store_row(conn, "ETHUSDT")
    fresh = _row(_strategy("short", fresh=True), calib=CAL_FRESH)
    fresh.update({"symbol": "SOLUSDT", "coin": "SOL", "last_bar": "2026-11-11T12:00:00Z"})
    S.save_row(conn, "SOLUSDT", fresh, {"candles": []})
    conn.commit()
    c = client_for("u-admin")
    body = c.get("/api/v1/lab/outlook?sort=kualitas").json()
    grades = [(r["symbol"], (r.get("kualitas") or {}).get("grade")) for r in body["rows"]]
    assert grades[0] == ("SOLUSDT", "A") and dict(grades)["ETHUSDT"] == "D"
    assert body["counts"]["kualitas"]["A"] == 1 and body["counts"]["kualitas"]["D"] == 1
    only_a = c.get("/api/v1/lab/outlook?kualitas=A").json()["rows"]
    assert [r["symbol"] for r in only_a] == ["SOLUSDT"]
    d = c.get("/api/v1/lab/outlook/SOLUSDT").json()
    assert d["kualitas"]["grade"] == "A" and d["kualitas"]["outcome_text"].startswith("Dari 600 kasus serupa")
