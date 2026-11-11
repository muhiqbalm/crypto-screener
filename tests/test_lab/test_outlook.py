"""Outlook Koin + market regime: pure logic, storage, scheduling and API (no engine, no network)."""
import types

import pytest

from src.lab import regime as R
from src.lab.db import utcnow
from src.lab.outlook import JOB_KIND
from src.lab.outlook import logic as L
from src.lab.outlook import schedule as OS
from src.lab.outlook import sources as SRC
from src.lab.outlook import store as S

from .test_lab_api import client_for  # noqa: F401  (pytest fixture)


# ── fixtures ─────────────────────────────────────────────────────────────

def _strategy(side="short", verdict="PASS", contaminated=False, preset=True, **kw):
    st = {"side": side, "entry_price": 2125.0, "entry_time": "2026-11-08T20:00:00Z", "entry_at": "2026-11-09T00:00:00Z",
          "sl": 2274.0, "tp": 1860.0, "tp1": 1912.5, "fresh": False, "open_pnl_pct": 2.4, "dist_sl_pct": 9.6,
          "dist_tp_pct": 10.4, "dist_sl_r": 1.34, "dist_tp_r": 1.44, "last_bar": "2026-11-11T12:00:00Z",
          "last_bar_close": "2026-11-11T16:00:00Z"}
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
STRENGTH = {"trend": "down", "ema_dist_pct": -12.8, "ret_7d_pct": -11.6, "ret_30d_pct": -19.2, "ret_90d_pct": 9.4,
            "funding_7d_apr_pct": 25.0}
REGIME_DOWN = {"label": "turun", "label_text": "Pasar turun", "dist_ema_slow_pct": -8.0, "slope_pct": -2.0,
               "days_in_label": 5}
TRACK = {"komposit:-1": "terbukti", "funding:-1": "belum_terbukti"}


def _ctx(st, **kw):
    c = {"strategy": st, "screener": SCREENER, "track": TRACK, "strength": STRENGTH, "oi": {"change_24h_pct": 3.0},
         "regime": REGIME_DOWN, "regime_perf": None, "headlines": [{"title": "Ethereum x"}],
         "fear_greed": {"value": 29, "classification": "Fear"}}
    c.update(kw)
    return c


def _row(st, **kw):
    ctx = _ctx(st, **kw)
    f = L.build_factors(ctx)
    b = L.combine(f, st, ctx["regime"], ctx["regime_perf"])
    bt = {"basis": "holdout", "basis_text": "periode holdout", "n": 51, "mean_pct": 1.0,
          "by_side": {"short": {"n": 31, "win_rate_pct": 35.0, "avg_win_pct": 6.4, "avg_loss_pct": -2.1,
                                "mean_pct": 0.9, "median_hold_hours": 56}, "long": {"n": 3, "mean_pct": -1.0}}}
    row = {"symbol": "ETHUSDT", "price": 2074.25, "last_bar_close": st.get("last_bar_close"), "strategy": st,
           "factors": f, "bias": b, "backtest": bt}
    row["explanation"] = L.narrate(row)
    return row


# ── formatting ───────────────────────────────────────────────────────────

def test_indonesian_number_formatting():
    assert L.fprice(2125.2) == "2.125"
    assert L.fprice(126.97) == "126,97"
    assert L.fprice(0.0049408) == "0,004941"
    assert L.fpct(-12.04) == "−12,0%"
    assert L.fpct(None) == "tidak tersedia"
    assert L.fusd(-98.4) == "−$98,40"
    assert L.fdate("2026-11-08T20:00:00Z", True) == "9 Nov 03:00 WIB"
    assert L.fdate("2025-07-06T04:00:00Z", False, True) == "6 Jul 2025"


# ── factors / bias ───────────────────────────────────────────────────────

def test_factors_have_direction_and_evidence():
    f = {x["key"]: x for x in L.build_factors(_ctx(_strategy()))}
    assert set(f) == {"strategi", "screener", "tren", "momentum", "funding", "oi", "regime", "berita"}
    assert f["strategi"]["direction"] == -1 and f["strategi"]["evidence"] == "lolos_uji"
    assert f["screener"]["direction"] == -1 and f["screener"]["evidence"] == "terbukti"
    assert f["screener"]["used_weight"] == 1.0
    assert f["funding"]["evidence"] == "belum_terbukti" and f["funding"]["used_weight"] == 0.25
    assert f["tren"]["direction"] == -1 and f["momentum"]["direction"] == -1
    assert f["regime"]["direction"] == -1
    assert f["berita"]["direction"] == 0 and f["berita"]["evidence"] == "konteks" and f["berita"]["used_weight"] == 0


def test_missing_data_is_tidak_tersedia_not_invented():
    f = {x["key"]: x for x in L.build_factors(_ctx(_strategy(), screener=None, strength=None, oi=None, regime=None,
                                                    headlines=[], fear_greed=None))}
    for k in ("screener", "tren", "momentum", "funding", "oi", "regime"):
        assert f[k]["evidence"] == "tidak_tersedia" and f[k]["used_weight"] == 0 and f[k]["direction"] == 0, k
    assert "Fear & Greed tidak tersedia" in f["berita"]["detail"]


def test_negative_track_record_is_not_counted():
    f = {x["key"]: x for x in L.build_factors(_ctx(_strategy(), track={"komposit:-1": "negatif"}))}
    assert f["screener"]["used_weight"] == 0.0


def test_pass_preset_with_support_is_tinggi_and_never_flips_side():
    st = _strategy("short")
    f = L.build_factors(_ctx(st))
    b = L.combine(f, st, REGIME_DOWN, None)
    assert b["bias"] == "SHORT" and b["keyakinan"] == "tinggi" and b["support"] >= L.SUPPORT_HIGH
    # every secondary factor against the short: still SHORT, keyakinan drops to rendah
    st_long_market = _ctx(st, screener={**SCREENER, "signal": "BULLISH", "funding_rate_signal": "BULLISH"},
                          track={"komposit:1": "terbukti"}, strength={**STRENGTH, "trend": "up", "ret_30d_pct": 20.0},
                          regime={**REGIME_DOWN, "label": "naik"})
    b2 = L.combine(L.build_factors(st_long_market), st, {"label": "naik"}, None)
    assert b2["bias"] == "SHORT" and b2["keyakinan"] == "rendah"


def test_contaminated_holdout_caps_at_sedang():
    st = _strategy("short", contaminated=True)
    b = L.combine(L.build_factors(_ctx(st)), st, REGIME_DOWN, None)
    assert b["keyakinan"] == "sedang" and any("tercemar" in r for r in b["reasons"])


@pytest.mark.parametrize("verdict,preset", [("FAIL", True), (None, False)])
def test_failed_or_untested_preset_is_always_rendah(verdict, preset):
    st = _strategy("short", verdict=verdict, preset=preset)
    b = L.combine(L.build_factors(_ctx(st)), st, REGIME_DOWN, None)
    assert b["bias"] == "SHORT" and b["keyakinan"] == "rendah"


def test_regime_history_loss_downgrades_one_level():
    st = _strategy("short")
    perf = {"short": {"turun": {"n": 12, "mean_pct": -1.2, "win_rate_pct": 30.0, "enough": True}}}
    b = L.combine(L.build_factors(_ctx(st, regime_perf=perf)), st, REGIME_DOWN, perf)
    assert b["keyakinan"] == "sedang" and any("rugi saat pasar turun" in r for r in b["reasons"])


def test_stale_strategy_data_is_rendah():
    st = _strategy("short")
    b = L.combine(L.build_factors(_ctx(st)), st, REGIME_DOWN, None, now_iso="2026-11-12T08:00:00Z")
    assert b["keyakinan"] == "rendah"


def test_flat_strategy_is_netral_with_condong():
    st = _strategy(None)
    b = L.combine(L.build_factors(_ctx(st)), st, REGIME_DOWN, None)
    assert b["bias"] == "NETRAL" and b["keyakinan"] is None and b["condong"] == "turun"


# ── narrative ────────────────────────────────────────────────────────────

def test_narrative_is_deterministic_indonesian():
    row = _row(_strategy("short", contaminated=True))
    e = row["explanation"]
    assert e["narrator"] == "template" and e["ai_summary"] is None
    assert e["summary"].startswith("Strategi 4H-ETH-v2_1x (LOLOS uji) sedang SHORT sejak 9 Nov 07:00 WIB di 2.125")
    assert "mendukung short" in e["summary"]
    text = " ".join(e["paragraphs"])
    assert "tren di bawah EMA" in text and "funding positif (long ramai)" in text
    assert "bukan jaminan" in text
    assert L.narrate(row) == L.narrate(row)


def test_narrative_flat_and_untested():
    row = _row(_strategy(None, preset=False))
    assert "Strategi Rosyade default (belum diuji untuk koin ini) sedang FLAT" in row["explanation"]["summary"]
    assert "Bias NETRAL" in " ".join(row["explanation"]["paragraphs"])


# ── money projection ─────────────────────────────────────────────────────

def test_projection_notional_1x_includes_fees():
    row = _row(_strategy("short"))
    p = L.project(row, 1000.0, 1.0)
    assert p["available"] and p["notional"] == 1000.0
    qty = 1000.0 / 2074.25
    gross_tp = qty * (2074.25 - 1860.0)
    fees_tp = 1000.0 * 0.001 + qty * 1860.0 * 0.001
    assert p["at_tp"]["net"] == pytest.approx(gross_tp - fees_tp)
    assert p["at_sl"]["net"] < 0 and p["at_sl"]["net"] == pytest.approx(-qty * (2274.0 - 2074.25)
                                                                        - 1.0 - qty * 2274.0 * 0.001)
    assert p["rr"] == pytest.approx(p["at_tp"]["net"] / -p["at_sl"]["net"])
    assert p["at_tp1"]["price"] == 1912.5
    ev = p["expected"]
    assert ev["subset"] == "trade short" and ev["n"] == 31 and ev["ev_usd"] == pytest.approx(9.0)
    assert "Bukan jaminan" in ev["caveat"]


def test_projection_leverage_and_risk_sizing():
    row = _row(_strategy("short"))
    p2 = L.project(row, 1000.0, 2.0)
    assert p2["notional"] == 2000.0 and p2["at_tp"]["net"] == pytest.approx(2 * L.project(row, 1000.0, 1.0)["at_tp"]["net"])
    pr = L.project(row, 1000.0, 3.0, sizing="risk", risk_pct=1.0)
    assert pr["at_sl"]["net"] == pytest.approx(-10.0, rel=1e-6)
    # few long trades -> EV falls back to all trades and says so
    st = _strategy("long", sl=1900.0, tp=2500.0, tp1=None)
    pl = L.project({**row, "strategy": st}, 1000.0, 1.0)
    assert pl["expected"]["subset"].startswith("semua trade")
    # high leverage + wide SL -> liquidation warning
    assert any("likuidasi" in w for w in L.project(row, 1000.0, 15.0)["warnings"])


def test_projection_unavailable_when_flat():
    p = L.project(_row(_strategy(None)), 1000.0, 1.0)
    assert p["available"] is False and "FLAT" in p["reason"]


# ── regime ───────────────────────────────────────────────────────────────

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
    assert R.classify(10, 9, 11, 1.0) == "datar"
    idx = R.RegimeIndex(s2)
    last = s2[-1]
    # the label of day D is not visible before D's close
    assert idx.label_at(last["t"]) == s2[-2]["label"]
    assert idx.label_at(last["valid_from"]) == last["label"]
    assert idx.label_at("2023-01-01T00:00:00Z") is None
    cur = R.current(s2, "BTCUSDT")
    assert cur["label"] == "turun" and cur["days_in_label"] >= 1 and cur["inputs"]["close_above_ema_slow"] is False


def test_perf_by_regime():
    s = R.label_series(_daily([100 * 1.01 ** i for i in range(260)]))
    idx = R.RegimeIndex(s)
    t_in = s[-5]["valid_from"]
    trades = [{"side": "long", "entry_time": t_in, "pnl_pct": 2.0}, {"side": "long", "entry_time": t_in, "pnl_pct": -1.0},
              {"side": "short", "entry_time": "2020-01-01T00:00:00Z", "pnl_pct": 5.0}]
    p = R.perf_by_regime(trades, idx)
    assert p["long"]["naik"]["n"] == 2 and p["long"]["naik"]["mean_pct"] == 0.5 and p["long"]["naik"]["enough"] is False
    assert p["short"]["naik"]["n"] == 0  # entry before any label -> not classified


# ── presets / sources / store ────────────────────────────────────────────

def _p(i, name, verdict, pf, live=False, sym="ETHUSDT"):
    return {"id": i, "name": name, "symbol": sym, "timeframe": "4h", "template_id": "rosyade_family",
            "verdict": verdict, "live_reference": live, "holdout": {"profit_factor": pf}}


def test_pick_preset_prefers_pass_then_live_then_own():
    ps = [_p(1, "4H-ETH-Basic", None, None, live=True), _p(4, "4H-ETH-v2", "FAIL", 1.3),
          _p(6, "4H-ETH-v2_1x", "PASS", 1.61), _p(9, "4H-ETH-v2_VT60", "PASS", 1.60), _p(2, "4H-BTC-Opt", "FAIL", 1.4, sym="BTCUSDT")]
    assert S.pick_preset(ps, "ETHUSDT")["name"] == "4H-ETH-v2_1x"
    assert S.pick_preset([ps[0], ps[1]], "ETHUSDT")["name"] == "4H-ETH-Basic"
    assert S.pick_preset(ps, "BTCUSDT")["name"] == "4H-BTC-Opt"
    assert S.pick_preset(ps, "SOLUSDT") is None


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
    assert len(SRC.headlines_for(items, "ETHUSDT")) == 1
    assert SRC.headlines_for(items, "SOLUSDT") == []


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


# ── scheduling ───────────────────────────────────────────────────────────

def test_schedule_waits_for_universe_refresh_then_once_per_bar(conn, lab_env):
    from src.lab.settings import get_lab_settings
    from src.lab import queue as q
    s = get_lab_settings()
    now = 1762876800 + 3600  # 2025-11-11T16:00Z + 1h -> last closed 4h bar opened 12:00
    assert OS.tick(conn, s, now) is None             # universe refresh for this bar not queued yet
    from src.lab.scheduler import last_closed_bar_open
    bar = last_closed_bar_open("4h", now, s.watch_delay_s)
    conn.execute("INSERT INTO lab_kv (key, value) VALUES ('universe_refresh_bar', ?)", (bar,))
    uj = q.enqueue(conn, "universe_refresh", None, {"bar": bar})
    conn.commit()
    assert OS.tick(conn, s, now) is None             # still running
    q.finish(conn, uj, "done")
    jid = OS.tick(conn, s, now)
    assert jid is not None and q.get_job(conn, jid)["kind"] == JOB_KIND
    q.finish(conn, jid, "done")
    assert OS.tick(conn, s, now) is None             # once per bar


def test_schedule_can_be_disabled(conn, lab_env, monkeypatch):
    from src.lab.settings import get_lab_settings
    monkeypatch.setenv("LAB_OUTLOOK_REFRESH", "0")
    assert OS.tick(conn, get_lab_settings(), 1762880400) is None


def test_job_kind_is_fast_lane_and_dispatched():
    from src.lab import worker
    assert JOB_KIND in worker.FAST_KINDS and JOB_KIND not in worker.SCREENER_VENV_KINDS
    import inspect
    from src.lab import runner
    assert '"outlook_refresh"' in inspect.getsource(runner.main)


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
    run = {"df": df, "res": types.SimpleNamespace(open_position=op), "trades": trades, "params": T.defaults()}
    st, price = J.position_from_run(run)
    assert price == 2074.25 and st["side"] == "short" and st["entry_at"] == "2026-11-09T00:00:00Z"
    assert st["base_sl"] == pytest.approx(2125.0 * 1.03) and st["bars_in_trade"] == 2 and st["fresh"] is False
    assert st["dist_sl_r"] == pytest.approx((2188.75 - 2074.25) / (2125.0 * 0.03))
    assert st["tp1"] == pytest.approx(2125.0 * 0.9)
    run["res"] = types.SimpleNamespace(open_position=None)
    st2, _ = J.position_from_run(run)
    assert st2["side"] is None and st2["last_exit"]["reason"] == "hard_sl"
    idx = R.RegimeIndex([])
    bt = J.backtest_block(trades, {"holdout_start": "2026-01-01T00:00:00Z", "holdout_end": "2026-11-09T00:00:00Z"}, idx)
    assert bt["basis"] == "holdout" and bt["n"] == 1 and bt["full"]["n"] == 2
    bt2 = J.backtest_block(trades, None, idx)
    assert bt2["basis"] == "full_in_sample" and bt2["by_side"]["short"]["avg_loss_pct"] == -3.5


# ── API ──────────────────────────────────────────────────────────────────

def test_outlook_api_admin_only_and_projection(client_for, conn):
    _store_row(conn)
    S.kv_set(conn, S.META_KEY, {"computed_at": utcnow()})
    conn.commit()
    assert client_for(None).get("/api/v1/lab/outlook").status_code == 401
    assert client_for("u-plain").get("/api/v1/lab/outlook").status_code == 403
    assert client_for("u-plain").get("/api/v1/lab/outlook/ETHUSDT").status_code == 403
    c = client_for("u-admin")
    r = c.get("/api/v1/lab/outlook?capital=1000&leverage=1")
    assert r.status_code == 200
    body = r.json()
    row = body["rows"][0]
    assert row["bias"]["bias"] == "SHORT" and row["projection"]["notional"] == 1000.0
    assert "paragraphs" not in row["explanation"] and body["method"]["weights"]["screener"] == 1.0
    assert "Bukan saran investasi" in body["disclaimer"]
    r2 = c.get("/api/v1/lab/outlook/eth?capital=500&leverage=2").json()
    assert r2["symbol"] == "ETHUSDT" and r2["projection"]["notional"] == 1000.0 and r2["explanation"]["paragraphs"]
    assert r2["detail"]["candles"]
    assert c.get("/api/v1/lab/outlook/XYZUSDT").status_code == 404
    assert c.get("/api/v1/lab/outlook?leverage=50").status_code == 422
    assert c.get("/api/v1/lab/outlook?capital=0").status_code == 422


def test_outlook_refresh_enqueues_once(client_for, conn):
    c = client_for("u-admin")
    a = c.post("/api/v1/lab/outlook/refresh").json()
    b = c.post("/api/v1/lab/outlook/refresh").json()
    assert a["already"] is False and b == {"job_id": a["job_id"], "already": True}
    assert client_for("u-plain").post("/api/v1/lab/outlook/refresh").status_code == 403


def test_regime_api_any_user_presets_admin_only(client_for, conn):
    assert client_for(None).get("/api/v1/lab/regime").status_code == 401
    assert client_for("u-plain").get("/api/v1/lab/regime").json()["available"] is False
    R.save(conn, {"computed_at": utcnow(), "rule": R.RULE, "btc": {"label": "turun"}, "eth": {"label": "datar"},
                  "presets": [{"name": "4H-ETH-v2_1x"}], "btc_history_share_pct": {"naik": 40.0}})
    plain = client_for("u-plain").get("/api/v1/lab/regime").json()
    assert plain["btc"]["label"] == "turun" and plain["presets"] is None and "btc_history_share_pct" not in plain
    admin = client_for("u-admin").get("/api/v1/lab/regime").json()
    assert admin["presets"][0]["name"] == "4H-ETH-v2_1x"


def test_outlook_api_empty_before_first_run(client_for):
    body = client_for("u-admin").get("/api/v1/lab/outlook").json()
    assert body["rows"] == [] and body["meta"] is None

