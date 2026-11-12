"""Outlook Koin v2 + market regime: pure logic, calibration, storage, scheduling and API
(no engine, no network; the engine-backed replay checks live in test_outlook_replay.py)."""
import types

import pytest

from src.lab import regime as R
from src.lab.db import utcnow
from src.lab.outlook import JOB_KIND, CALIBRATE_KIND
from src.lab.outlook import calib as C
from src.lab.outlook import logic as L
from src.lab.outlook import mtf as M
from src.lab.outlook import schedule as OS
from src.lab.outlook import sources as SRC
from src.lab.outlook import store as S
from src.lab.outlook.evaluate import evaluate_call

from .test_lab_api import client_for  # noqa: F401  (pytest fixture)


# ── fixtures ─────────────────────────────────────────────────────────────

def _strategy(side="short", verdict="PASS", contaminated=False, preset=True, fresh=False, **kw):
    st = {"side": side, "entry_price": 2125.0, "entry_time": "2026-11-08T20:00:00Z", "entry_at": "2026-11-09T00:00:00Z",
          "sl": 2274.0, "tp": 1860.0, "tp1": 1912.5, "fresh": fresh, "open_pnl_pct": 2.4, "dist_sl_pct": 9.6,
          "dist_tp_pct": 10.4, "dist_sl_r": 1.34, "dist_tp_r": 1.44, "last_bar": "2026-11-11T12:00:00Z",
          "last_bar_close": "2026-11-11T16:00:00Z", "template_id": "rosyade_family", "timeframe": "4h",
          "name": "4H-ETH-v2_1x" if preset else "Rosyade default 4H"}
    if side is None:
        for k in ("entry_price", "entry_time", "entry_at", "sl", "tp", "tp1"):
            st[k] = None
        st["last_exit"] = {"time": "2026-10-30T00:00:00Z", "side": "short", "reason": "atr_trailing", "pnl_pct": -0.5}
    st["preset"] = {"id": 6, "name": "4H-ETH-v2_1x", "verdict": verdict, "contaminated": contaminated,
                    "failed_checks": [] if verdict == "PASS" else ["mc_dd_p95"]} if preset else None
    st.update(kw)
    return st


SCREENER = {"signal": "BEARISH", "tier": "B", "confidence_tier": "MEDIUM", "confidence_pct": 59.0,
            "funding_rate_signal": "BEARISH", "oi_signal": "NEUTRAL", "funding_rate": 0.03, "bar": "2026-11-11T15:00:00Z"}
STRENGTH = {"trend": "down", "ema_dist_pct": -12.8, "funding_7d_apr_pct": 25.0}
REGIME_DOWN = {"label": "turun", "label_text": "Pasar turun", "dist_ema_slow_pct": -8.0, "slope_pct": -2.0,
               "days_in_label": 5}
TRACK = {"komposit:-1": "terbukti", "funding:-1": "belum_terbukti"}
MTF_DOWN = {"tren_1d": {"direction": -1, "dist_pct": -6.0, "slope_pct": -1.2},
            "momentum_1h": {"direction": -1, "ret_24h_pct": -2.0}}


def _st(n_pos, mean, lo, **kw):
    d = {"n_cases": n_pos * 5, "n_pos": n_pos, "p_tp": 0.2, "p_sl": 0.3, "p_batal": 0.5, "p_expired": 0.0,
         "mean_r": mean, "lo95_r": lo, "se_r": 0.05, "median_r": -0.2, "ev_shrunk_r": mean * n_pos / (n_pos + 20),
         "win_rate": 0.33, "median_mfe_r": 1.1, "median_bars": 6.0}
    d.update(kw)
    return d


CALIB = {"computed_at": "2026-11-12T03:00:00Z", "buckets": {
    "lolos_uji|short|*|berjalan": _st(31, -0.025, -0.23),
    "lolos_uji|short|*|baru": _st(31, 0.145, -0.14),
    "pool|short|*|baru": _st(3466, 0.14, 0.08),
    "pool|short|*|berjalan": _st(2863, 0.026, -0.035),
    "belum_diuji|short|*|baru": _st(3435, 0.14, 0.08),
    "belum_diuji|short|*|berjalan": _st(2832, 0.026, -0.035),
}, "factor_lift": {"pool": {"tren_1d": {"verdict": "belum_terbukti", "searah": {"mean_r": 0.05, "n_pos": 4400},
                                        "berlawanan": {"mean_r": 0.06, "n_pos": 1400}}}},
    "per_coin": {}}


def _ctx(st, **kw):
    c = {"strategy": st, "mtf": MTF_DOWN, "regime": REGIME_DOWN, "regime_dir_at_call": -1,
         "lifts": CALIB["factor_lift"]["pool"], "screener": SCREENER, "track": TRACK, "strength": STRENGTH,
         "oi": {"change_24h_pct": 3.0}, "headlines": [{"title": "Ethereum x"}],
         "fear_greed": {"value": 29, "classification": "Fear"}}
    c.update(kw)
    return c


def _row(st, calib=CALIB, now="2026-11-11T16:05:00Z", **kw):
    ctx = _ctx(st, **kw)
    f = L.build_factors(ctx)
    b = L.combine(f, st, calib, now_iso=now, price=2074.25)
    bt = {"basis": "holdout", "basis_text": "periode holdout", "n": 51, "mean_pct": 1.0,
          "by_side": {"short": {"n": 31, "win_rate_pct": 35.0, "avg_win_pct": 6.4, "avg_loss_pct": -2.1,
                                "mean_pct": 0.9, "median_hold_hours": 56}, "long": {"n": 3, "mean_pct": -1.0}}}
    row = {"symbol": "ETHUSDT", "coin": "ETH", "price": 2074.25, "last_bar_close": st.get("last_bar_close"),
           "strategy": st, "factors": f, "bias": b, "backtest": bt,
           "strategies": [{"name": st.get("name"), "primary": True, "side": st.get("side"), "verdict": "PASS"},
                          {"name": "4H-ETH-v2_VT60", "primary": False, "side": st.get("side"), "verdict": "PASS"}]}
    row["plan"] = L.plan(st, row["price"], b, now_iso=now)
    row["peluang"] = L.peluang(row)
    row["explanation"] = L.narrate(row)
    return row


# ── formatting ───────────────────────────────────────────────────────────

def test_exchange_style_numbers_and_wib_times():
    """CEO decision 12 Nov: exchange-style digits (1,234.56) everywhere; WIB with Indonesian months."""
    assert L.fprice(2125.2) == "2,125"
    assert L.fprice(126.97) == "126.97"
    assert L.fprice(0.0049408) == "0.004941"
    assert L.fpct(-12.04) == "−12.0%"
    assert L.fpct(None) == "tidak tersedia"
    assert L.fusd(-98.4) == "−$98.40" and L.fusd(1234.5) == "+$1,234.50"
    assert L.fr(0.123) == "+0.12R" and L.fpp(0.578) == "58%"
    assert C.fr(-0.0248) == "−0.02R" and C.fint(6470) == "6,470"
    assert L.fdate("2026-11-08T20:00:00Z", True) == "9 Nov 03:00 WIB"
    assert L.fdate("2025-07-06T04:00:00Z", False, True) == "6 Jul 2025"


# ── MTF factors: same code live and in the replay, closed bars only ───────

def test_ema_matches_pandas_ewm_and_directions():
    import pandas as pd
    xs = [100 + (i % 7) - i * 0.3 for i in range(120)]
    ours = M.ema_series(xs, 20)
    ref = pd.Series(xs).ewm(span=20, adjust=False).mean().tolist()
    assert max(abs(a - b) for a, b in zip(ours, ref)) < 1e-9
    up = [100 * 1.01 ** i for i in range(120)]
    assert M.trend_now(up)["direction"] == 1 and M.momentum_now(up)["direction"] == 1
    down = [100 * 0.99 ** i for i in range(120)]
    assert M.trend_now(down)["direction"] == -1 and M.momentum_now(down)["direction"] == -1
    assert M.trend_now(up[:30]) is None          # warm-up: unavailable, not invented
    assert M.align_group(2) == "searah" and M.align_group(-2) == "berlawanan" and M.align_group(1) == "campuran"


def test_last_closed_never_sees_a_forming_bar():
    opens = [0, 3600, 7200]                       # 1H bars
    assert M.last_closed(opens, 3600, 7199) == 0  # bar 1 closes at 7200
    assert M.last_closed(opens, 3600, 7200) == 1
    assert M.last_closed(opens, 3600, 3599) == -1


# ── after-the-fact evaluation of one call ────────────────────────────────

def test_evaluate_call_outcomes():
    # short at 100, SL 103, TP 90 -> R unit 3
    tp = evaluate_call("short", 100, 103, 90, [(100, 101, 95, 96), (96, 97, 89, 90)], 10)
    assert tp["status"] == "tp" and tp["r_gross"] == pytest.approx(10 / 3) and tp["bars"] == 2
    assert tp["r_net"] == pytest.approx(10 / 3 - 0.2 / 3)            # 0.2% round trip in R
    sl = evaluate_call("short", 100, 103, 90, [(100, 103.5, 99, 103)], 10)
    assert sl["status"] == "sl" and sl["r_gross"] == pytest.approx(-1.0)
    both = evaluate_call("short", 100, 103, 90, [(100, 104, 89, 95)], 10)
    assert both["status"] == "sl" and both["ambiguous"] is True       # same bar: conservative
    gap = evaluate_call("long", 100, 97, 110, [(95, 96, 94, 95)], 10)
    assert gap["status"] == "sl" and gap["exit_price"] == 95 and gap["r_gross"] == pytest.approx(-5 / 3)
    batal = evaluate_call("long", 100, 97, 110, [(100, 102, 99, 101), (101, 103, 100, 102)], 10, invalid_at=2)
    assert batal["status"] == "batal" and batal["exit_price"] == 102 and batal["mfe_r"] == pytest.approx(1.0)
    exp = evaluate_call("long", 100, 97, 110, [(100, 101, 99, 100.5)] * 3, 3)
    assert exp["status"] == "expired" and exp["bars"] == 3
    still = evaluate_call("long", 100, 97, 110, [(100, 101, 99, 100.5)], 3)
    assert still["status"] == "open"
    assert evaluate_call("long", 100, 101, 110, [], 3)["status"] == "invalid"     # price already beyond SL
    assert evaluate_call("short", 100, 103, None, [(100, 101, 99, 100)], 1)["status"] == "expired"  # no TP


# ── calibration: statistics, keyakinan, factor lift ──────────────────────

def _case(pos, r, status="batal", cls="belum_diuji", side="short", fase="baru", t=0.0, dirs=(1, 1, 1, 0)):
    return C.Case("XUSDT", cls, side, "searah", fase, t, pos, status, r, 0.5, 3, 2.0, dirs, "default")


def test_stats_cluster_by_position_and_shrink():
    cases = [_case("a", 1.0), _case("a", 1.0), _case("b", -1.0), _case("c", 0.5, "tp"), _case("d", 0.1, "open")]
    st = C.stats(cases)
    assert st["n_cases"] == 4 and st["n_pos"] == 3                  # open calls are not counted
    assert st["mean_r"] == pytest.approx(0.375) and st["p_tp"] == pytest.approx(0.25)
    assert st["ev_shrunk_r"] == pytest.approx(0.375 * 3 / 23)
    assert st["se_r"] is not None and st["lo95_r"] < st["mean_r"]


def test_assess_keyakinan_from_similar_cases():
    b = CALIB["buckets"]
    # own bucket enough and negative -> rendah, even for a PASS preset
    a = C.assess(b, "lolos_uji", "short", "berjalan")
    assert a["level"] == "rendah" and a["key"] == "lolos_uji|short|*|berjalan"
    # own bucket enough but not significant -> pooled evidence decides -> sedang
    a = C.assess(b, "lolos_uji", "short", "baru", contaminated=True)
    assert a["level"] == "sedang" and a["key"] == "pool|short|*|baru"
    assert "Strategi ini sendiri baru 31 posisi" in a["reasons"][0]
    # untested default: pooled positive -> sedang (cap), running position -> rendah
    assert C.assess(b, "belum_diuji", "short", "baru")["level"] == "sedang"
    assert C.assess(b, "belum_diuji", "short", "berjalan")["level"] == "rendah"
    # FAIL preset is capped at rendah; tinggi needs the strategy's own strong bucket
    assert C.assess(b, "gagal_uji", "short", "baru")["level"] == "rendah"
    strong = {"lolos_uji|long|*|baru": _st(40, 0.3, 0.1)}
    assert C.assess(strong, "lolos_uji", "long", "baru")["level"] == "tinggi"
    assert C.assess(strong, "lolos_uji", "long", "baru", contaminated=True)["level"] == "sedang"
    assert C.assess({}, "lolos_uji", "long", "baru")["level"] == "rendah"


def test_factor_lift_needs_both_halves():
    cases = []
    for i in range(60):
        t = 0.0 if i < 30 else 10.0
        cases.append(_case(f"s{i}", 0.5 + (i % 3) * 0.01, t=t, dirs=(1, 1, 1, 0)))
        cases.append(_case(f"o{i}", -0.5 - (i % 3) * 0.01, t=t, dirs=(-1, -1, -1, 0)))
    assert C.factor_lift(cases, 0, split_t=5.0)["verdict"] == "teruji"
    # the effect exists only in the first half -> not proven
    half = [c._replace(r_net=0.0) if c.t > 5 else c for c in cases]
    assert C.factor_lift(half, 0, split_t=5.0)["verdict"] == "belum_terbukti"


# ── factors / bias ───────────────────────────────────────────────────────

def test_factors_v2_groups_and_evidence():
    f = {x["key"]: x for x in L.build_factors(_ctx(_strategy()))}
    assert set(f) == {"strategi", "tren_1d", "momentum_1h", "regime", "funding", "oi", "screener", "berita"}
    assert f["strategi"]["group"] == "utama" and f["strategi"]["direction"] == -1 and f["strategi"]["in_keyakinan"]
    assert f["tren_1d"]["group"] == "mtf" and f["tren_1d"]["direction"] == -1
    assert f["tren_1d"]["evidence"] == "belum_terbukti_replay" and "belum terbukti" in f["tren_1d"]["detail"]
    assert f["screener"]["group"] == "konteks" and f["screener"]["evidence"] == "terbukti"
    assert all(not x["in_keyakinan"] and x["used_weight"] == 0 for k, x in f.items() if k != "strategi")
    assert f["berita"]["direction"] == 0 and f["berita"]["evidence"] == "konteks"


def test_missing_data_is_tidak_tersedia_not_invented():
    f = {x["key"]: x for x in L.build_factors(_ctx(_strategy(), mtf={}, screener=None, strength=None, oi=None,
                                                    regime=None, headlines=None, fear_greed=None))}
    for k in ("tren_1d", "momentum_1h", "regime", "screener", "funding", "oi", "berita"):
        assert f[k]["evidence"] == "tidak_tersedia" and f[k]["direction"] == 0 and not f[k]["available"], k
    assert "Fear & Greed tidak tersedia" in f["berita"]["detail"]


def test_combine_bias_follows_strategy_and_keyakinan_from_calibration():
    st = _strategy("short")
    b = L.combine(L.build_factors(_ctx(st)), st, CALIB, now_iso="2026-11-11T16:05:00Z", price=2074.25)
    assert b["bias"] == "SHORT" and b["basis"] == "kalibrasi" and b["fase"] == "berjalan"
    assert b["keyakinan"] == "rendah" and b["calib"]["key"] == "lolos_uji|short|*|berjalan"
    # factors all pointing the other way never flip the side
    st2 = _strategy("short", fresh=True)
    up = {"tren_1d": {"direction": 1}, "momentum_1h": {"direction": 1}}
    b2 = L.combine(L.build_factors(_ctx(st2, mtf=up, regime_dir_at_call=1)), st2, CALIB, price=2074.25)
    assert b2["bias"] == "SHORT" and b2["keyakinan"] == "sedang" and b2["align"] == "berlawanan"


def test_combine_fallback_stale_and_sl_crossed():
    st = _strategy("short")
    b = L.combine(L.build_factors(_ctx(st)), st, None, price=2074.25)
    assert b["basis"] == "aturan" and b["keyakinan"] == "sedang"          # PASS preset without calibration
    st_u = _strategy("short", preset=False)
    assert L.combine(L.build_factors(_ctx(st_u)), st_u, None)["keyakinan"] == "rendah"
    st_f = _strategy("short", fresh=True)
    stale = L.combine(L.build_factors(_ctx(st_f)), st_f, CALIB, now_iso="2026-11-12T08:00:00Z")
    assert stale["keyakinan"] == "rendah" and any("basi" in r for r in stale["reasons"])
    crossed = L.combine(L.build_factors(_ctx(st_f)), st_f, CALIB, price=2300.0)
    assert crossed["keyakinan"] == "rendah"


def test_flat_strategy_is_netral_with_condong():
    st = _strategy(None)
    b = L.combine(L.build_factors(_ctx(st)), st, CALIB)
    assert b["bias"] == "NETRAL" and b["keyakinan"] is None and b["condong"] == "turun"


# ── plan / changes / narrative ───────────────────────────────────────────

def test_plan_entry_zone_rr_invalidation_horizon():
    row = _row(_strategy("short", fresh=True))
    p = row["plan"]
    r = 2274.0 - 2074.25
    assert p["action"] == "masuk" and p["geometry_ok"] and p["r_unit"] == pytest.approx(r)
    assert p["entry_zone"] == [pytest.approx(2074.25 - 0.25 * r), pytest.approx(2074.25 + 0.25 * r)]
    assert p["rr"] == pytest.approx((2074.25 - 1860.0) / r)
    assert p["dont_chase"] == pytest.approx(2074.25 - 0.25 * r)          # short: lower entry = worse R:R
    assert p["horizon_bars"] == 42 and p["valid_until"] == "2026-11-18T16:00:00Z"
    assert p["target_typical"] == pytest.approx(2074.25 - 1.1 * r)
    assert "Batal kalau harga menyentuh SL 2,274" in p["batal_kalau"]
    assert _row(_strategy("short"))["plan"]["action"] == "menyusul"
    assert L.plan(_strategy("short"), 2300.0, {}, None)["action"] == "jangan_masuk"
    assert L.plan(_strategy(None), 2000.0, {}, None)["action"] == "tunggu"


def test_changes_since_previous_call():
    assert L.changes({"side": "short"}, None) == ["Panggilan pertama yang tercatat untuk koin ini."]
    prev = {"side": "short", "keyakinan": "rendah", "sl": 2274.0, "tp": 1860.0, "price": 2100.0, "fase": "baru",
            "strategy": "A", "strategy_entry_time": "t1", "call": {"dirs": {"tren_1d": -1, "momentum_1h": 1}}}
    cur = {"side": "short", "keyakinan": "sedang", "sl": 2230.0, "tp": 1860.0, "price": 2074.25, "fase": "berjalan",
           "strategy": "A", "strategy_entry_time": "t1", "call": {"dirs": {"tren_1d": -1, "momentum_1h": -1}}}
    ch = " | ".join(L.changes(cur, prev))
    assert "Keyakinan naik: rendah → sedang" in ch and "SL bergeser dari 2,274 ke 2,230" in ch
    assert "Momentum 1H berubah: naik → turun" in ch and "menyusul" in ch and "−1.2%" in ch
    flip = L.changes({**cur, "side": None}, prev)
    assert flip[0].startswith("Arah berubah: SHORT → FLAT")


def test_narrative_leads_with_decision_and_is_deterministic():
    row = _row(_strategy("short", fresh=True, contaminated=True))
    e = row["explanation"]
    assert e["narrator"] == "template" and e["ai_summary"] is None
    p = e["paragraphs"]
    assert p[0].startswith("Keputusan: ETH cenderung SHORT, keyakinan sedang. Rencana: entry ")
    assert p[1].startswith("Kenapa: Strategi 4H-ETH-v2_1x (Rosyade 4H, LOLOS uji)")
    assert "1 strategi lain juga SHORT" in p[1] and "belum terbukti" in p[1]
    assert p[2].startswith("Bukti: Kasus serupa — posisi baru") and "Kesimpulan: keyakinan sedang" in p[2]
    assert any(x.startswith("Risiko:") and "Batal kalau" in x for x in p)
    assert p[-1] == "Ini informasi, bukan jaminan atau saran investasi."
    assert e["summary"].startswith("SHORT · keyakinan sedang · posisi baru")
    assert L.narrate(row) == L.narrate(row)
    late = _row(_strategy("short"))["explanation"]["paragraphs"][0]
    assert "menyusul posisi yang sudah berjalan" in late


def test_narrative_flat_says_tunggu():
    row = _row(_strategy(None, preset=False))
    assert row["explanation"]["paragraphs"][0].startswith("Keputusan: ETH tidak ada sinyal (strategi FLAT) — tunggu.")
    assert row["explanation"]["summary"].startswith("Tidak ada sinyal")


# ── money projection ─────────────────────────────────────────────────────

def test_projection_notional_1x_includes_fees_rr_and_calibrated_ev():
    row = _row(_strategy("short", fresh=True))
    p = L.project(row, 1000.0, 1.0)
    assert p["available"] and p["notional"] == 1000.0
    qty = 1000.0 / 2074.25
    gross_tp = qty * (2074.25 - 1860.0)
    fees_tp = 1000.0 * 0.001 + qty * 1860.0 * 0.001
    assert p["at_tp"]["net"] == pytest.approx(gross_tp - fees_tp)
    assert p["rr"] == pytest.approx(p["at_tp"]["net"] / -p["at_sl"]["net"]) and p["rr_text"].endswith(": 1")
    cal = p["calibrated"]
    assert cal["key"] == "pool|short|*|baru" and cal["ev_usd"] == pytest.approx(0.14 * qty * (2274.0 - 2074.25))
    assert p["at_typical"]["price"] == pytest.approx(row["plan"]["target_typical"])
    assert p["expected"]["subset"] == "trade short" and "Bukan jaminan" in p["expected"]["caveat"]


def test_projection_leverage_risk_sizing_and_flat():
    row = _row(_strategy("short"))
    p2 = L.project(row, 1000.0, 2.0)
    assert p2["notional"] == 2000.0
    pr = L.project(row, 1000.0, 3.0, sizing="risk", risk_pct=1.0)
    assert pr["at_sl"]["net"] == pytest.approx(-10.0, rel=1e-6)
    assert any("likuidasi" in w for w in L.project(row, 1000.0, 15.0)["warnings"])
    flat = L.project(_row(_strategy(None)), 1000.0, 1.0)
    assert flat["available"] is False and "FLAT" in flat["reason"]


# ── "Peluang terbaik" ordering ───────────────────────────────────────────

def test_peluang_ranking_by_evidence_weighted_ev():
    fresh = {**_row(_strategy("short", fresh=True)), "symbol": "AUSDT"}
    late = {**_row(_strategy("short")), "symbol": "BUSDT"}
    flat = {**_row(_strategy(None)), "symbol": "CUSDT"}
    nocal = _row(_strategy("short", fresh=True), calib=None)
    nocal["symbol"] = "DUSDT"
    stale = {**_row(_strategy("short", fresh=True)), "symbol": "EUSDT", "stale": True}
    stale["peluang"] = L.peluang(stale)
    assert fresh["peluang"]["label"] == "positif" and late["peluang"]["label"] == "negatif"
    assert flat["peluang"]["eligible"] is False and stale["peluang"]["eligible"] is False
    ranked = L.rank_rows([flat, late, stale, nocal, fresh])
    assert [r["symbol"] for r in ranked] == ["AUSDT", "BUSDT", "DUSDT", "EUSDT", "CUSDT"]   # stale call before FLAT
    assert ranked[0]["peluang"]["rank"] == 1 and "rank" not in ranked[-1]["peluang"]


# ── strategy selection ───────────────────────────────────────────────────

def _p(i, name, verdict, pf, live=False, sym="ETHUSDT", tid="rosyade_family", tf="4h", trades=50, params=None):
    return {"id": i, "name": name, "symbol": sym, "timeframe": tf, "template_id": tid, "verdict": verdict,
            "live_reference": live, "holdout": {"profit_factor": pf, "trades": trades},
            "params": params if params is not None else {"k": i}, "costs": None}


def test_strategies_for_any_template_pass_first_then_honest_fallback():
    ps = [_p(1, "4H-ETH-Basic", None, None, live=True, params={}), _p(4, "4H-ETH-v2", "FAIL", 1.3),
          _p(6, "4H-ETH-v2_1x", "PASS", 1.61), _p(9, "4H-ETH-v2_VT60", "PASS", 1.60),
          _p(11, "1H-ETH-Don1", "PASS", 1.75, tid="donchian_breakout", tf="1h"),
          _p(2, "4H-BTC-Opt", "FAIL", 1.4, sym="BTCUSDT")]
    eth = S.strategies_for(ps, "ETHUSDT", default_params={})
    assert [d["name"] for d in eth][:3] == ["1H-ETH-Don1", "4H-ETH-v2_1x", "4H-ETH-v2_VT60"]
    assert eth[0]["primary"] and eth[0]["template_id"] == "donchian_breakout" and eth[0]["timeframe"] == "1h"
    assert "4H-ETH-Basic" in [d["name"] for d in eth] and "4H-ETH-v2" in [d["name"] for d in eth]
    btc = S.strategies_for(ps, "BTCUSDT", default_params={"a": 1})
    assert btc[0]["name"] == S.DEFAULT_NAME and btc[0]["kind"] == "default" and btc[1]["name"] == "4H-BTC-Opt"
    sol = S.strategies_for(ps, "SOLUSDT", default_params={"a": 1})
    assert [d["name"] for d in sol] == [S.DEFAULT_NAME]
    many = [_p(100 + i, f"4H-ETH-P{i}", "PASS", 1.2 + i / 100) for i in range(10)]
    capped = S.strategies_for(many, "ETHUSDT", default_params={})
    assert len(capped) == S.MAX_PASS + 1 and capped[0]["name"] == "4H-ETH-P9" and capped[-1]["kind"] == "default"
    dup = [_p(6, "4H-ETH-v2_1x", "PASS", 1.61, params={"x": 1}), _p(7, "4H-ETH-copy", "PASS", 1.5, params={"x": 1})]
    assert [d["name"] for d in S.strategies_for(dup, "ETHUSDT", default_params={})] == ["4H-ETH-v2_1x", S.DEFAULT_NAME]
    assert L.agreement([{"side": "short", "verdict": "PASS"}, {"side": None}, {"side": "long", "verdict": "FAIL"}]) == {
        "all": {"long": 1, "short": 1, "flat": 1, "error": 0, "n": 3},
        "lolos_uji": {"long": 0, "short": 1, "flat": 0, "error": 0, "n": 1}}


def test_pick_preset_v1_rule_kept():
    ps = [_p(1, "4H-ETH-Basic", None, None, live=True), _p(4, "4H-ETH-v2", "FAIL", 1.3),
          _p(6, "4H-ETH-v2_1x", "PASS", 1.61), _p(2, "4H-BTC-Opt", "FAIL", 1.4, sym="BTCUSDT")]
    assert S.pick_preset(ps, "ETHUSDT")["name"] == "4H-ETH-v2_1x"
    assert S.pick_preset(ps, "BTCUSDT")["name"] == "4H-BTC-Opt" and S.pick_preset(ps, "SOLUSDT") is None


# ── sources ──────────────────────────────────────────────────────────────

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Bitcoin slides as ETF outflows grow</title><link>https://cointelegraph.com/a</link>
<pubDate>Tue, 11 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Traders near the edge as markets link up</title><link>javascript:alert(1)</link></item>
<item><title>NEAR Protocol and Chainlink team up; $ETH holds</title><link>https://cointelegraph.com/b</link>
<pubDate>Tue, 11 Nov 2026 12:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_headlines_matching_is_conservative():
    items = SRC.parse_rss(RSS)
    assert items[1]["url"] is None and items[0]["published_at"] == "2026-11-11T10:00:00Z"
    assert [h["title"][:7] for h in SRC.headlines_for(items, "BTCUSDT")] == ["Bitcoin"]
    assert len(SRC.headlines_for(items, "NEARUSDT")) == 1     # "near the edge" does not match
    assert len(SRC.headlines_for(items, "LINKUSDT")) == 1
    assert SRC.headlines_for(items, "SOLUSDT") == []


# ── store: rows, call history, additive schema ───────────────────────────

def _call(sym="ETHUSDT", bar="2026-11-11T12:00:00Z", side="short", **kw):
    c = {"symbol": sym, "bar": bar, "bar_close": "2026-11-11T16:00:00Z", "computed_at": utcnow(), "side": side,
         "keyakinan": "rendah", "keyakinan_basis": "kalibrasi", "cls": "lolos_uji", "align": "searah",
         "fase": "berjalan", "strategy": "4H-ETH-v2_1x", "template_id": "rosyade_family", "timeframe": "4h",
         "strategy_entry_time": "2026-11-08T20:00:00Z", "price": 100.0, "sl": 103.0, "tp": 90.0, "horizon_bars": 42,
         "rr": 3.3, "ev_r": -0.01, "call_json": {"dirs": {"tren_1d": -1}}}
    c.update(kw)
    return c


def _store_row(conn, sym="ETHUSDT", **kw):
    row = _row(_strategy("short"))
    row.update({"symbol": sym, "last_bar": "2026-11-11T12:00:00Z", **kw})
    S.save_row(conn, sym, row, {"candles": [[1, 1, 2, 0.5, 1.5]], "headlines": [], "recent_trades": []})
    conn.commit()
    return row


def test_store_roundtrip_keeps_last_good_row_on_error(conn):
    _store_row(conn)
    S.save_row(conn, "ETHUSDT", None, None, "boom")
    got = S.read_one(conn, "ETHUSDT")
    assert got["row"]["symbol"] == "ETHUSDT" and got["error"] == "boom" and got["detail"]["candles"]


def test_schema_is_additive_on_a_v1_database(conn):
    conn.executescript("CREATE TABLE lab_outlook (symbol TEXT PRIMARY KEY, computed_at TEXT NOT NULL, last_bar TEXT, "
                       "row_json TEXT, detail_json TEXT, error TEXT);"
                       "INSERT INTO lab_outlook (symbol, computed_at, row_json) VALUES ('ETHUSDT', 'x', '{\"symbol\": \"ETHUSDT\"}');")
    S.ensure_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM lab_outlook").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM lab_outlook_calls").fetchone()[0] == 0
    S.ensure_schema(conn)   # idempotent


def test_call_history_upsert_prev_and_track_record(conn):
    S.save_call(conn, _call(bar="2026-11-11T08:00:00Z", keyakinan="sedang"))
    S.save_call(conn, _call())
    S.save_call(conn, _call(side=None, bar="2026-11-11T16:00:00Z"))
    S.save_call(conn, _call(keyakinan="rendah"))          # same bar again: upsert, not a duplicate
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM lab_outlook_calls").fetchone()[0] == 3
    prev = S.prev_call(conn, "ETHUSDT", "2026-11-11T12:00:00Z")
    assert prev["keyakinan"] == "sedang" and prev["call"]["dirs"] == {"tren_1d": -1}
    opens = S.open_calls(conn)
    assert len(opens) == 2 and all(c["status"] == "open" for c in opens)
    S.set_outcome(conn, opens[0]["id"], {"status": "tp", "r_net": 2.0, "bars": 3, "resolved_at": "2026-11-12T00:00:00Z"})
    S.set_outcome(conn, opens[1]["id"], {"status": "sl", "r_net": -1.0, "bars": 1})
    conn.commit()
    tr = S.track_record(conn)
    g = tr["groups"]["short|*"]
    assert g["n_calls"] == 2 and g["n_done"] == 2 and g["tp"] == 0.5 and g["mean_r"] == pytest.approx(0.5)
    assert tr["groups"]["*|sedang"]["n_done"] == 1 and len(tr["recent"]) == 2


def test_evaluate_open_calls_detects_batal_from_later_calls(conn):
    from src.lab.outlook import job as J

    class Runner:
        def bars4(self, sym):
            t0 = int(J.labdb_epoch("2026-11-11T12:00:00Z"))
            return [(t0 + k * 14400, 100.0, 101.0, 99.0, 100.0 - k * 0.1) for k in range(6)]

    S.save_call(conn, _call())
    S.save_call(conn, _call(bar="2026-11-11T16:00:00Z"))                         # same position
    S.save_call(conn, _call(bar="2026-11-11T20:00:00Z", side=None))               # strategy went FLAT
    conn.commit()
    out = J.evaluate_open_calls(conn, Runner())
    rows = {r["bar"]: dict(r) for r in conn.execute("SELECT * FROM lab_outlook_calls")}
    first = rows["2026-11-11T12:00:00Z"]
    assert first["status"] == "batal" and first["bars_to_resolve"] == 2 and first["r_net"] > -0.1
    assert out["evaluated"] == 2 and out["resolved"] == 2


def test_open_positions_paper_and_live(conn, tmp_path):
    import sqlite3
    db = tmp_path / "trading.db"
    t = sqlite3.connect(db)
    t.execute("CREATE TABLE positions (id INTEGER, symbol TEXT, side TEXT, entry_price REAL, created_at TEXT, status TEXT)")
    t.execute("INSERT INTO positions VALUES (1, 'ETH/USDT:USDT', 'sell', 2000.0, '2026-11-09', 'open')")
    t.execute("INSERT INTO positions VALUES (2, 'BTC/USDT:USDT', 'buy', 90000.0, '2026-11-01', 'closed')")
    t.commit()
    t.close()
    live = S.live_positions(str(db))
    assert live == {"ETHUSDT": [{"source": "live", "side": "short", "entry_price": 2000.0, "entry_time": "2026-11-09"}]}
    assert S.live_positions(str(tmp_path / "missing.db")) is None
    assert S.paper_positions(conn) == {}


# ── scheduling ───────────────────────────────────────────────────────────

def test_schedule_waits_for_universe_refresh_then_once_per_bar(conn, lab_env):
    from src.lab.settings import get_lab_settings
    from src.lab import queue as q
    s = get_lab_settings()
    now = 1762876800 + 3600
    assert OS.tick(conn, s, now) is None
    from src.lab.scheduler import last_closed_bar_open
    bar = last_closed_bar_open("4h", now, s.watch_delay_s)
    conn.execute("INSERT INTO lab_kv (key, value) VALUES ('universe_refresh_bar', ?)", (bar,))
    uj = q.enqueue(conn, "universe_refresh", None, {"bar": bar})
    conn.commit()
    assert OS.tick(conn, s, now) is None
    q.finish(conn, uj, "done")
    jid = OS.tick(conn, s, now)
    assert jid is not None and q.get_job(conn, jid)["kind"] == JOB_KIND
    q.finish(conn, jid, "done")
    assert OS.tick(conn, s, now) is None


def test_schedule_can_be_disabled(conn, lab_env, monkeypatch):
    from src.lab.settings import get_lab_settings
    monkeypatch.setenv("LAB_OUTLOOK_REFRESH", "0")
    assert OS.tick(conn, get_lab_settings(), 1762880400) is None


def test_calibrate_tick_quiet_window_weekly_and_backoff(conn, lab_env, monkeypatch):
    from src.lab import queue as q
    from src.lab.outlook import replay as RP
    import calendar
    import time as _t
    at = lambda s: calendar.timegm(_t.strptime(s, "%Y-%m-%dT%H:%M:%S"))  # noqa: E731
    assert OS.calibrate_tick(conn, None, at("2026-11-12T03:55:00")) is None      # near a 4H close
    assert OS.calibrate_tick(conn, None, at("2026-11-12T04:20:00")) is None      # hour % 4 == 0
    jid = OS.calibrate_tick(conn, None, at("2026-11-12T05:20:00"))
    assert jid is not None and q.get_job(conn, jid)["kind"] == CALIBRATE_KIND
    assert OS.calibrate_tick(conn, None, at("2026-11-12T06:20:00")) is None      # still queued
    q.finish(conn, jid, "error", "boom")
    assert OS.calibrate_tick(conn, None, at("2026-11-12T06:20:00")) is None      # one attempt per day
    RP.save(conn, {"computed_at": "2026-11-12T06:00:00Z"})
    assert OS.calibrate_tick(conn, None, at("2026-11-15T05:20:00")) is None      # fresh enough
    assert OS.calibrate_tick(conn, None, at("2026-11-20T05:20:00")) is not None  # > 7 days old
    monkeypatch.setenv("LAB_OUTLOOK_CALIBRATE", "0")
    assert OS.calibrate_tick(conn, None, at("2026-11-27T05:20:00")) is None


def test_job_kinds_lanes_and_dispatch():
    from src.lab import worker
    assert JOB_KIND in worker.FAST_KINDS and JOB_KIND not in worker.SCREENER_VENV_KINDS
    assert CALIBRATE_KIND not in worker.FAST_KINDS                  # heavy: never takes the fast lane
    import inspect
    from src.lab import runner
    src = inspect.getsource(runner.main)
    assert '"outlook_refresh"' in src and '"outlook_calibrate"' in src


# ── job helpers (fake engine result) ─────────────────────────────────────

def test_position_from_run_and_backtest_block():
    import pandas as pd
    from src.lab.outlook import job as J
    from src.lab.templates import rosyade_family as T
    ts = pd.date_range("2026-11-08T12:00:00Z", periods=5, freq="4h")
    df = pd.DataFrame({"timestamp": ts, "close": [2100.0, 2110.0, 2125.0, 2090.0, 2074.25]})
    op = {"direction": "short", "entry_price": 2125.0, "entry_timestamp": ts[2], "entry_bar_index": 2,
          "sl": 2188.75, "tp": 1859.375, "breakeven_locked": False}
    trades = [{"entry_time": "2026-11-01T00:00:00Z", "exit_time": "2026-11-02T00:00:00Z", "side": "long",
               "entry_price": 2000.0, "exit_price": 2100.0, "pnl_pct": 4.8, "exit_reason": "atr_trailing", "bars_held": 6},
              {"entry_time": "2025-01-01T00:00:00Z", "exit_time": "2025-01-02T00:00:00Z", "side": "short",
               "entry_price": 3000.0, "exit_price": 3100.0, "pnl_pct": -3.5, "exit_reason": "hard_sl", "bars_held": 3}]
    run = {"df": df, "res": types.SimpleNamespace(open_position=op), "trades": trades, "params": T.defaults(),
           "template_id": "rosyade_family", "timeframe": "4h",
           "last_state": ("short", 2125.0, 2, None, 2188.75, 1859.375, 2125.0 * 1.03)}
    st, price = J.position_from_run(run)
    assert price == 2074.25 and st["side"] == "short" and st["entry_at"] == "2026-11-09T00:00:00Z"
    assert st["base_sl"] == pytest.approx(2125.0 * 1.03) and st["bars_in_trade"] == 2 and st["fresh"] is False
    assert st["dist_sl_r"] == pytest.approx((2188.75 - 2074.25) / (2125.0 * 0.03))
    assert st["tp1"] == pytest.approx(2125.0 * 0.9)
    fam = {**run, "template_id": "donchian_breakout", "last_state": ("short", 2125.0, 2, None, 2200.0, None, 2210.0)}
    st_f, _ = J.position_from_run(fam)
    assert st_f["base_sl"] == 2210.0 and st_f["tp1"] is None and st_f["template_id"] == "donchian_breakout"
    run["res"] = types.SimpleNamespace(open_position=None)
    st2, _ = J.position_from_run(run)
    assert st2["side"] is None and st2["last_exit"]["reason"] == "hard_sl"
    idx = R.RegimeIndex([])
    bt = J.backtest_block(trades, {"holdout_start": "2026-01-01T00:00:00Z", "holdout_end": "2026-11-09T00:00:00Z"}, idx)
    assert bt["basis"] == "holdout" and bt["n"] == 1 and bt["full"]["n"] == 2
    assert J.backtest_block(trades, None, idx, "1h")["median_hold_hours"] == pytest.approx(4.5)


# ── replay helpers (no engine) ───────────────────────────────────────────

def test_positions_by_bar_and_configs():
    from src.lab.outlook import replay as RP
    res = types.SimpleNamespace(trades=[types.SimpleNamespace(entry_bar_index=2, exit_bar_index=5)],
                                open_position={"entry_bar_index": 7})
    trace = {2: ("long", 10.0, 2, 9.0, 12.0, 9.0), 3: ("long", 10.0, 2, 9.5, 12.0, 9.0),
             7: ("short", 11.0, 7, 12.0, None, 12.0)}
    pos = RP.positions_by_bar(res, trace, 9)
    assert pos[1] is None and pos[2][4] == 9.0 and pos[3][4] == 9.5 and pos[4][4] == 9.5   # gap bar: carried
    assert pos[5] is None and pos[6] is None and pos[8][0] == "short" and pos[8][3] is None
    presets = [_p(6, "4H-ETH-v2_1x", "PASS", 1.6), _p(9, "4H-ETH-v2_VT60", "PASS", 1.6, params={"k": 6}),
               _p(4, "4H-ETH-v2", "FAIL", 1.3), _p(1, "4H-ETH-Basic", None, None, live=True)]
    for p in presets:
        p["holdout"]["start"] = "2025-07-06T04:00:00Z"
    cfgs = {(c.symbol, tuple(c.names)): c for c in RP.configs_for(presets, ["ETHUSDT", "SOLUSDT"])}
    assert cfgs[("SOLUSDT", ("default",))].cls == "belum_diuji"
    assert cfgs[("ETHUSDT", ("default",))].cls == "in_sample"        # defaults were designed on ETH 4H
    assert cfgs[("ETHUSDT", ("4H-ETH-v2_1x", "4H-ETH-v2_VT60"))].cls == "lolos_uji"   # identical params: one run
    fail = cfgs[("ETHUSDT", ("4H-ETH-v2",))]
    assert fail.cls == "gagal_uji" and fail.oos_start.startswith("2025-07-06")
    assert len(cfgs) == 4                                             # live reference has no verdict: not replayed


def test_summarise_reports_oos_checks_and_exclusions():
    from src.lab.outlook import replay as RP
    cases = []
    for i in range(80):
        t = RP._epoch("2023-01-01T00:00:00Z") if i < 40 else RP._epoch("2025-01-01T00:00:00Z")
        cases.append(C.Case("AUSDT", "belum_diuji", "short", "searah", "baru", t + i, f"p{i}", "tp", 1.0 if i % 2 else -0.5,
                            0.8, 4, 2.0, (1, 1, 0, 0), "default"))
        cases.append(C.Case("AUSDT", "belum_diuji", "short", "searah", "berjalan", t + i + 86400, f"p{i}", "batal", -0.1,
                            0.2, 4, 2.0, (1, -1, 0, 0), "default"))
    out = RP.summarise(cases, [{"names": ["default"], "contaminated": False}])
    assert out["counts"]["cases"] == 160 and out["counts"]["positions"] == 80
    assert out["buckets"]["pool|short|*|baru"]["n_pos"] == 80
    assert set(out["oos_check"]) >= {"v2", "apriori", "split"} and out["oos_check"]["test_cases"] == 80
    assert "sesudah" in out["fase_split"] and out["factor_lift"]["pool"]["momentum_1h"]["verdict"] in (
        "teruji", "belum_terbukti", "terbalik")
    assert {e["factor"] for e in RP.EXCLUDED} >= {"berita", "open interest", "screener komposit"}


# ── API ──────────────────────────────────────────────────────────────────

def test_outlook_api_v2_fields_filters_and_ranking(client_for, conn):
    _store_row(conn, "ETHUSDT")
    fresh = _row(_strategy("short", fresh=True))
    fresh.update({"symbol": "SOLUSDT", "coin": "SOL", "last_bar": "2026-11-11T12:00:00Z"})
    S.save_row(conn, "SOLUSDT", fresh, {"candles": []})
    flat = _row(_strategy(None, preset=False))
    flat.update({"symbol": "BTCUSDT", "coin": "BTC", "last_bar": "2026-11-11T12:00:00Z"})
    S.save_row(conn, "BTCUSDT", flat, {"candles": []})
    S.kv_set(conn, S.META_KEY, {"computed_at": utcnow()})
    conn.commit()
    assert client_for(None).get("/api/v1/lab/outlook").status_code == 401
    c = client_for("u-admin")
    body = c.get("/api/v1/lab/outlook?capital=1000&leverage=1").json()
    assert body["schema_version"] == 2 and body["counts"]["arah"] == {"long": 0, "short": 2, "netral": 1}
    assert body["can_refresh"] is True and body["positions_available"] == {"paper": True, "live": False}
    syms = [r["symbol"] for r in body["rows"]]
    assert syms[-1] == "BTCUSDT"                                    # FLAT rows sink to the bottom
    row = body["rows"][0]
    assert row["bias"]["bias"] == "SHORT" and row["projection"]["notional"] == 1000.0 and "plan" in row
    assert "paragraphs" not in row["explanation"] and row["positions"] == []
    assert body["calibration"] is None and body["track_record"]["groups"] == {}
    assert "Bukan saran investasi" in body["disclaimer"] and body["method"]["schema_version"] == 2
    only_short = c.get("/api/v1/lab/outlook?arah=short").json()
    assert {r["symbol"] for r in only_short["rows"]} == {"ETHUSDT", "SOLUSDT"}
    assert c.get("/api/v1/lab/outlook?keyakinan=sedang").json()["rows"][0]["symbol"] == "SOLUSDT"
    assert c.get("/api/v1/lab/outlook?posisi=ada").json()["rows"] == []
    az = c.get("/api/v1/lab/outlook?sort=symbol").json()
    assert [r["symbol"] for r in az["rows"]] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    r2 = c.get("/api/v1/lab/outlook/eth?capital=500&leverage=2").json()
    assert r2["symbol"] == "ETHUSDT" and r2["projection"]["notional"] == 1000.0 and r2["explanation"]["paragraphs"]
    assert r2["detail"]["candles"] and r2["calls"] == []
    assert c.get("/api/v1/lab/outlook/XYZUSDT").status_code == 404
    assert c.get("/api/v1/lab/outlook?leverage=50").status_code == 422
    assert c.get("/api/v1/lab/outlook?arah=up").status_code == 422


def test_peluang_koin_is_readable_by_every_logged_in_user(client_for, conn):
    """CEO decision 12 Nov: every team account can READ Outlook / coin page / Terkuat; mutations stay admin."""
    _store_row(conn, "ETHUSDT")
    S.save_call(conn, _call())
    conn.commit()
    plain = client_for("u-plain")
    body = plain.get("/api/v1/lab/outlook").json()
    assert body["rows"][0]["symbol"] == "ETHUSDT" and body["can_refresh"] is False
    assert "positions" not in body["rows"][0] and body["positions_available"] is None   # positions are admin-only
    assert plain.get("/api/v1/lab/outlook?posisi=ada").json()["rows"][0]["symbol"] == "ETHUSDT"  # filter ignored
    d = plain.get("/api/v1/lab/outlook/ETHUSDT").json()
    assert d["explanation"]["paragraphs"] and d["can_refresh"] is False and "positions" not in d
    assert d["calls"][0]["side"] == "short"
    assert plain.get("/api/v1/lab/outlook/track-record").status_code == 200
    assert plain.get("/api/v1/lab/outlook/calibration").json()["available"] is False
    assert plain.get("/api/v1/lab/strength").status_code == 200
    for path in ("/api/v1/lab/outlook/refresh", "/api/v1/lab/outlook/calibrate", "/api/v1/lab/strength/refresh"):
        assert plain.post(path).status_code == 403, path
    assert client_for(None).get("/api/v1/lab/strength").status_code == 401
    assert client_for(None).get("/api/v1/lab/outlook/ETHUSDT").status_code == 401


def test_track_record_and_calibration_endpoints(client_for, conn):
    from src.lab.outlook import replay as RP
    c = client_for("u-admin")
    assert c.get("/api/v1/lab/outlook/calibration").json()["available"] is False
    S.save_call(conn, _call())
    conn.commit()
    tr = c.get("/api/v1/lab/outlook/track-record").json()
    assert tr["groups"]["short|rendah"]["n_open"] == 1 and tr["recent"][0]["symbol"] == "ETHUSDT"
    RP.save(conn, {"computed_at": "2026-11-12T03:00:00Z", "version": 1, "counts": {"cases": 10},
                   "by_keyakinan": {"*|sedang": {"n_pos": 5}, "belum_diuji|short|sedang": {}},
                   "oos_check": {"v2": {"*|sedang": {}}, "apriori": {}}, "factor_lift": {"pool": {}},
                   "buckets": {"x": {}}, "per_coin": {"ETHUSDT": {"lolos_uji|short": {"n_pos": 3}}}})
    cal = c.get("/api/v1/lab/outlook/calibration").json()
    assert cal["available"] and cal["by_keyakinan"] == {"*|sedang": {"n_pos": 5}} and "buckets" not in cal
    assert "buckets" in c.get("/api/v1/lab/outlook/calibration?full=true").json()
    _store_row(conn)
    d = c.get("/api/v1/lab/outlook/ETHUSDT").json()
    assert d["coin_calibration_all"] == {"lolos_uji|short": {"n_pos": 3}} and d["calls"][0]["side"] == "short"


def test_refresh_and_calibrate_enqueue_once(client_for, conn):
    c = client_for("u-admin")
    a = c.post("/api/v1/lab/outlook/refresh").json()
    b = c.post("/api/v1/lab/outlook/refresh").json()
    assert a["already"] is False and b == {"job_id": a["job_id"], "already": True}
    x = c.post("/api/v1/lab/outlook/calibrate").json()
    y = c.post("/api/v1/lab/outlook/calibrate").json()
    assert x["already"] is False and y == {"job_id": x["job_id"], "already": True}
    assert client_for("u-plain").post("/api/v1/lab/outlook/calibrate").status_code == 403


def test_regime_api_any_user_presets_admin_only(client_for, conn):
    assert client_for(None).get("/api/v1/lab/regime").status_code == 401
    assert client_for("u-plain").get("/api/v1/lab/regime").json()["available"] is False
    R.save(conn, {"computed_at": utcnow(), "rule": R.RULE, "btc": {"label": "turun"}, "eth": {"label": "datar"},
                  "presets": [{"name": "4H-ETH-v2_1x"}], "btc_history_share_pct": {"naik": 40.0}})
    plain = client_for("u-plain").get("/api/v1/lab/regime").json()
    assert plain["btc"]["label"] == "turun" and plain["presets"] is None and "btc_history_share_pct" not in plain
    assert client_for("u-admin").get("/api/v1/lab/regime").json()["presets"][0]["name"] == "4H-ETH-v2_1x"


def test_outlook_api_empty_before_first_run(client_for):
    body = client_for("u-admin").get("/api/v1/lab/outlook").json()
    assert body["rows"] == [] and body["meta"] is None and body["ranking"] == []


# ── regime (unchanged) ───────────────────────────────────────────────────

def _daily(closes):
    import pandas as pd
    ts = pd.date_range("2024-01-01", periods=len(closes), freq="1D", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "close": closes})


def test_regime_labels_and_causality():
    up = [100 * 1.01 ** i for i in range(260)]
    s = R.label_series(_daily(up))
    assert s[0]["warmup"] and s[-1]["label"] == "naik"
    down = up + [up[-1] * 0.98 ** i for i in range(1, 200)]
    s2 = R.label_series(_daily(down))
    assert s2[-1]["label"] == "turun"
    idx = R.RegimeIndex(s2)
    last = s2[-1]
    assert idx.label_at(last["t"]) == s2[-2]["label"]
    assert idx.label_at(last["valid_from"]) == last["label"]
    assert idx.label_at("2023-01-01T00:00:00Z") is None
