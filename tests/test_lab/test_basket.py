"""Basket paper strategies (src/lab/basket): pre-registered rules, many watches -> one paper
account, sizing on the shared account, per-coin isolation, checkpoints, fidelity, API, seed."""
import importlib.util
import json
import math
import pathlib
from datetime import datetime, timezone

import pytest

from src.lab import market, paper, watch_eval
from src.lab.basket import report, rules, sizing, store
from src.lab.ledger.store import iso, to_epoch

ROOT = pathlib.Path(__file__).resolve().parents[2]
PREREG = json.loads((ROOT / "docs/research/basket/prereg-basket-2026-11-12.json").read_text())
MANIFEST_PATH = ROOT / "ops/lab_baskets_seed.json"
COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}
TEN = ["BTCUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT",
       "LTCUSDT"]


# ── helpers ─────────────────────────────────────────────────────────────────

def _spec(mode="risk", symbols=("BTCUSDT", "SOLUSDT", "XRPUSDT"), name=None, expect=None):
    from src.lab.templates import get_template
    symbols = list(symbols)
    if mode == "risk":
        tid, params = "donchian_breakout", get_template("donchian_breakout").validate_params({})
        sz = {"mode": "risk", "risk_pct": 0.25, "slots": None, "max_position_notional_x": 0.5, "gross_cap_x": 1.5,
              "max_open": len(symbols), "min_fill_frac": 0.1, "kill_dd_pct": 15.0}
        acct = {"starting_balance": 10000.0, "risk_pct": 0.25, "leverage_max": 0.5}
    else:
        tid = "rosyade_family"
        params = get_template(tid).validate_params({"sizing_mode": "vol_target", "vol_target_pct": 60.0,
                                                     "vol_lookback": 60, "max_notional_mult": 2.0})
        sz = {"mode": "slot_engine", "risk_pct": None, "slots": len(symbols), "max_position_notional_x": 0.25,
              "gross_cap_x": 2.0, "max_open": len(symbols), "min_fill_frac": 0.1, "kill_dd_pct": 15.0}
        acct = {"starting_balance": 10000.0, "risk_pct": 100.0, "leverage_max": 0.25}
    return {"name": name or ("4H-BASKET-TestRisk" if mode == "risk" else "4H-BASKET-TestSlot"), "label": "Test",
            "title": "Basket uji", "template_id": tid, "timeframe": "4h", "params": params, "costs": COSTS,
            "symbols": symbols, "sizing": sz, "account": acct,
            "expect": expect if expect is not None else {"trades": 100, "max_dd_pct": -10.0, "start": "2025-07-06T00:00:00Z",
                                                         "end": "2026-11-12T00:00:00Z", "trades_per_month": 50.0,
                                                         "win_rate_pct": 40.0, "per_trade_ret_pct": 0.01,
                                                         "mc_dd_p95_pct": -8.0}}


def _create(conn, **kw):
    from src.api import lab_routes
    return store.create(conn, _spec(**kw), insert_watch=lab_routes._insert_watch)


def _watch(conn, basket, symbol):
    wid = next(m["watch_id"] for m in store.members(conn, basket["id"]) if m["symbol"] == symbol)
    return dict(conn.execute("SELECT * FROM watches WHERE id=?", (wid,)).fetchone())


def _bar_after_start(basket):
    """Open time of a 4H signal bar that closes after the basket started (a NEW signal)."""
    s = to_epoch(basket["created_at"])
    return iso(s - s % 3600)


def _open_signal(conn, basket, symbol, side="long", sl=None, nm=None, bar=None, price=100.0):
    w = _watch(conn, basket, symbol)
    bar = bar or _bar_after_start(basket)
    pos = {"side": side, "entry_price": price, "entry_time": bar, "sl": sl or (price * 0.9 if side == "long" else price * 1.1),
           "tp": None}
    if nm is not None:
        pos["notional_mult"] = nm
    sig = {"time": bar, "action": "open", "side": side, "price": price}
    watch_eval._autopaper(conn, w, None, {"last_bar": bar, "position": pos, "last_signal": sig})
    return w


def _raw_open(conn, b, symbol, qty, price):
    """An open auto position of any size (paper.open_position would cap it at the account's leverage_max)."""
    pid = conn.execute(
        "INSERT INTO paper_positions (account_id, symbol, side, qty, entry_price, entry_time, sl, fees, funding, "
        "risk_amount, source, watch_id, status, mark_price, mark_time, created_at) "
        "VALUES (?, ?, 'long', ?, ?, ?, ?, 0, 0, ?, 'paper_auto', ?, 'open', ?, ?, ?)",
        (b["account_id"], symbol, qty, price, b["created_at"], price * 0.5, qty * price * 0.5,
         _watch(conn, b, symbol)["id"], price, b["created_at"], b["created_at"])).lastrowid
    conn.commit()
    return pid


def _open_rows(conn, account_id):
    return [dict(r) for r in conn.execute("SELECT * FROM paper_positions WHERE account_id=? AND status='open' "
                                          "ORDER BY id", (account_id,))]


# ── pre-registration ───────────────────────────────────────────────────────

def test_rules_equal_the_preregistration_json():
    cp = PREREG["checkpoints"]
    assert rules.CHECKPOINTS[1] == {k: cp["1"][k] for k in ("min_trades", "min_days", "min_coins", "min_entry_days")}
    assert {k: rules.CHECKPOINTS[2][k] for k in ("min_trades", "min_days")} == \
        {k: cp["2"][k] for k in ("min_trades", "min_days")}
    assert rules.DEADLINE_DAYS == cp["deadline_days"]
    c = PREREG["criteria"]
    assert rules.PF_FAIL == {1: c["checkpoint_1"]["fail_if_pf_below"], 2: c["checkpoint_2"]["fail_if_pf_below"]}
    assert rules.PF_PASS == c["checkpoint_1"]["pass_if_pf_at_least"] == c["checkpoint_2"]["pass_if_pf_at_least"]
    assert rules.KILL_DD_PCT == c["kill_switch_dd_pct"]
    assert rules.FIDELITY_COVERAGE_MIN == PREREG["fidelity"]["coverage_min"]
    assert rules.FIDELITY_MAX_MEDIAN_ABS_DIFF_PP == PREREG["fidelity"]["median_abs_return_diff_pp_max"]
    assert rules.PREREG_ID == PREREG["id"] and set(rules.OUTCOMES) == set(PREREG["outcomes"])
    for b in PREREG["baskets"]:
        assert b["sizing"]["kill_dd_pct"] == rules.KILL_DD_PCT


def test_preregistered_baskets_and_coin_rule():
    from src.lab.templates import get_template
    a, b = PREREG["baskets"]
    universe = list(PREREG["coin_rule"]["data_check"]["first_4h_bar"])
    assert len(universe) == 29 and a["symbols"] == universe
    assert b["symbols"] == [s for s in universe if s != "ETHUSDT"] and len(b["symbols"]) == 28
    assert all(n >= 1300 for n in PREREG["coin_rule"]["data_check"]["rows_4h"].values())
    da, rb = get_template("donchian_breakout"), get_template("rosyade_family")
    assert a["params"] == da.validate_params({}) == da.defaults()                  # untouched defaults
    assert rb.validate_params(b["params"]) == b["params"]
    assert {k: v for k, v in b["params"].items() if k not in rb.SIZING_KEYS} == \
        {k: v for k, v in rb.defaults().items() if k not in rb.SIZING_KEYS}        # Basic signal params
    assert (b["params"]["sizing_mode"], b["params"]["vol_target_pct"]) == ("vol_target", 60.0)
    assert not da.is_mtf(a["params"]) and not rb.is_mtf(b["params"])
    assert a["sizing"]["max_open"] == 29 and b["sizing"]["slots"] == b["sizing"]["max_open"] == 28


def test_seed_manifest_equals_preregistration():
    spec = importlib.util.spec_from_file_location("lab_seed_baskets", ROOT / "ops/lab_seed_baskets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    m = json.loads(MANIFEST_PATH.read_text())
    assert [e["name"] for e in m["baskets"]] == ["4H-BASKET-DonchianDef", "4H-BASKET-RosyadeVT60"]
    for e in m["baskets"]:
        assert mod.prereg_diff(e, PREREG) == []
        x = e["expect"]
        assert x["trades"] > 0 and x["max_dd_pct"] < 0 and x["procedure_commit"] == rules.PREREG_COMMIT
        assert x["start"] == "2025-07-06T00:00:00Z" and x["gross_cap_binds"] == 0
        assert len(e["notes"]) <= 2000
    bad = dict(m["baskets"][0], symbols=m["baskets"][0]["symbols"][:-1])
    assert mod.prereg_diff(bad, PREREG) == ["symbols"]


def test_pure_rules():
    assert rules.profit_factor([]) is None and rules.profit_factor([1.0, 2.0]) == math.inf
    assert rules.profit_factor([3.0, -1.0, -1.0]) == 1.5
    assert [rules.pf_decision(x, 1) for x in (0.9, 1.0, 1.19, 1.2, math.inf)] == \
        ["GAGAL", "LANJUT", "LANJUT", "LULUS", "LULUS"]
    assert [rules.pf_decision(x, 2) for x in (1.19, 1.2)] == ["GAGAL", "LULUS"]
    assert rules.dd_limit_pct(None) is None and rules.dd_limit_pct(-2.0) == -5.0
    assert rules.dd_limit_pct(-10.394) == pytest.approx(-15.591)
    mon = to_epoch("2026-12-14T00:00:00Z")                      # a Monday
    assert rules.next_monday(mon) == mon
    assert rules.next_monday(to_epoch("2026-12-11T10:00:00Z")) == mon
    assert rules.next_monday(mon + 1) == mon + 7 * 86400


def test_checkpoint_due_needs_all_four_conditions():
    s = to_epoch("2026-11-13T09:00:00Z")
    pts = [{"id": i, "symbol": TEN[i % 10], "entry_s": s + i * 86400, "exit_s": s + i * 86400 + 3600}
           for i in range(30)]                                   # 30 trades, 10 coins, 30 entry days
    due = rules.checkpoint_due(pts, s, 1)
    assert due["n_at_met"] == 30 and iso(due["met_s"]) == "2026-12-12T10:00:00Z"   # the 30th exit (> 28 days)
    assert iso(due["due_s"]) == "2026-12-14T00:00:00Z"
    few_coins = [dict(p, symbol=TEN[i % 3]) for i, p in enumerate(pts)]
    assert rules.checkpoint_due(few_coins, s, 1) is None                           # 3 coins < 8
    one_day = [dict(p, entry_s=s) for p in pts]
    assert rules.checkpoint_due(one_day, s, 1) is None                            # 1 entry day < 10
    early = [dict(p, entry_s=s + i * 3600 * 9, exit_s=s + i * 3600 * 9 + 60) for i, p in enumerate(pts)]
    d2 = rules.checkpoint_due(early, s, 1)                                         # 30 trades in ~11 days
    assert iso(d2["met_s"]) == iso(s + 28 * 86400) and iso(d2["due_s"]) == "2026-12-14T00:00:00Z"


# ── create: one transaction, frozen definition ──────────────────────────────

def test_create_basket_is_one_transaction_and_frozen(conn):
    from src.api import lab_routes
    b = _create(conn, symbols=TEN)
    acct = paper.get_account(conn, b["account_id"])
    assert (acct["name"], acct["starting_balance"], acct["risk_pct"], acct["leverage_max"]) == \
        ("Paper 4H-BASKET-TestRisk", 10000.0, 0.25, 0.5)
    mem = store.members(conn, b["id"])
    assert [m["symbol"] for m in mem] == TEN
    for m in mem:
        w = conn.execute("SELECT * FROM watches WHERE id=?", (m["watch_id"],)).fetchone()
        assert (w["template_id"], w["timeframe"], w["autopaper_account_id"], w["autopaper_enabled"], w["active"]) == \
            ("donchian_breakout", "4h", b["account_id"], 1, 1)
        assert store.basket_of_watch(conn, m["watch_id"])["id"] == b["id"]
    jobs = conn.execute("SELECT COUNT(*) FROM lab_jobs WHERE kind='watch_eval' AND status='queued'").fetchone()[0]
    assert jobs == len(TEN)                                        # initial evaluation per watch, same as the API
    with pytest.raises(Exception, match="pre-registered"):
        conn.execute("UPDATE lab_baskets SET symbols_json='[]' WHERE id=?", (b["id"],))
    conn.rollback()
    with pytest.raises(Exception, match="frozen"):
        conn.execute("UPDATE lab_baskets SET expect_json='{}' WHERE id=?", (b["id"],))
    conn.rollback()
    with pytest.raises(store.BasketError) as e:
        _create(conn, symbols=TEN)
    assert e.value.status == 409

    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("paper_accounts", "watches", "lab_baskets", "lab_basket_members", "lab_jobs")}
    calls = []

    def flaky(conn_, *a):
        calls.append(a)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return lab_routes._insert_watch(conn_, *a)
    with pytest.raises(RuntimeError):
        store.create(conn, _spec(name="4H-BASKET-Other"), insert_watch=flaky)
    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert after == before                                         # nothing written on failure


def test_create_refuses_bad_sizing_and_mtf(conn):
    from fastapi import HTTPException
    bad = _spec()
    bad["sizing"] = dict(bad["sizing"], max_open=2)                # a queue between coins is not allowed
    from src.api import lab_routes
    with pytest.raises(store.BasketError):
        store.create(conn, bad, insert_watch=lab_routes._insert_watch)
    mtf = _spec(name="4H-BASKET-Mtf")
    mtf["params"] = dict(mtf["params"], entry_mode="ltf_close", entry_tf="1h")
    with pytest.raises(HTTPException):
        store.create(conn, mtf, insert_watch=lab_routes._insert_watch)
    assert conn.execute("SELECT COUNT(*) FROM lab_baskets").fetchone()[0] == 0


# ── many watches -> one account ─────────────────────────────────────────────

def test_risk_sizing_on_the_shared_account_per_symbol(conn, monkeypatch):
    prices = {"BTCUSDT": 50000.0, "SOLUSDT": 100.0, "XRPUSDT": 2.0}
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: prices[s])
    b = _create(conn)
    _open_signal(conn, b, "BTCUSDT", "long", sl=48000.0, price=50000.0)
    _open_signal(conn, b, "SOLUSDT", "short", sl=110.0, price=100.0)
    _open_signal(conn, b, "XRPUSDT", "long", sl=1.8, price=2.0)
    rows = _open_rows(conn, b["account_id"])
    assert [r["symbol"] for r in rows] == ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
    for r in rows:                                                  # 0.25% of the 10k balance at the stop
        assert r["risk_amount"] == pytest.approx(25.0, rel=1e-9)
        assert r["source"] == "paper_auto" and r["account_id"] == b["account_id"]
        assert r["watch_id"] == _watch(conn, b, r["symbol"])["id"]
    # a second signal on BTC while BTC is open does not duplicate; other coins are untouched
    w = _watch(conn, b, "BTCUSDT")
    pos = {"side": "long", "entry_price": 50000.0, "entry_time": _bar_after_start(b), "sl": 49000.0, "tp": None}
    watch_eval._autopaper(conn, w, None, {"last_bar": "2030-01-01T00:00:00Z", "position": pos, "last_signal": None})
    rows2 = _open_rows(conn, b["account_id"])
    assert len(rows2) == 3 and next(r for r in rows2 if r["symbol"] == "BTCUSDT")["sl"] == 49000.0
    assert next(r for r in rows2 if r["symbol"] == "SOLUSDT")["sl"] == 110.0
    assert store.events(conn, b["id"]) == []                       # full-size entries are not logged


def test_paper_check_is_per_symbol_on_a_shared_account(conn, monkeypatch):
    from src.lab import scheduler
    from src.lab.settings import get_lab_settings
    prices = {"BTCUSDT": 50000.0, "SOLUSDT": 100.0, "XRPUSDT": 2.0}
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: prices[s])
    b = _create(conn)
    for sym, side, sl in (("BTCUSDT", "long", 48000.0), ("SOLUSDT", "short", 110.0), ("XRPUSDT", "long", 1.8)):
        _open_signal(conn, b, sym, side, sl=sl, price=prices[sym])
    entry = to_epoch(_open_rows(conn, b["account_id"])[0]["entry_time"][:19] + "Z")
    t1 = entry - entry % 60 + 120
    t2 = t1 + 3600

    class FakeMarket:
        def __init__(self):
            self.limits = []

        def closed_klines(self, sym, tf, since_ms, limit=1500):
            self.limits.append(limit)
            px = prices[sym]
            low = 1.7 if sym == "XRPUSDT" else px * 0.999               # only XRP trades through its stop
            return [{"t": iso(t1), "ts": int(t1 * 1000), "o": px, "h": px * 1.001, "l": low, "c": px}]

        def funding_history(self, sym, since_ms):
            rate = {"BTCUSDT": 0.001, "SOLUSDT": 0.002, "XRPUSDT": 0.0}[sym]
            return [{"ts": int((t1 + 600) * 1000), "rate": rate, "mark": prices[sym]}]

    fm = FakeMarket()
    monkeypatch.setattr("time.time", lambda: t2)
    assert scheduler.check_paper(conn, get_lab_settings(), market=fm) == 1
    open_ = {r["symbol"]: r for r in _open_rows(conn, b["account_id"])}
    assert set(open_) == {"BTCUSDT", "SOLUSDT"}                    # XRP stopped, the others still open
    btc, sol = open_["BTCUSDT"], open_["SOLUSDT"]
    assert btc["funding"] == pytest.approx(btc["qty"] * 50000.0 * 0.001)     # long pays its own symbol's rate
    assert sol["funding"] == pytest.approx(-sol["qty"] * 100.0 * 0.002)      # short receives
    j = conn.execute("SELECT * FROM journal_entries WHERE account_id=?", (b["account_id"],)).fetchall()
    assert len(j) == 1 and j[0]["symbol"] == "XRPUSDT" and j[0]["exit_reason"] == "hard_sl"
    acct = paper.get_account(conn, b["account_id"])
    assert acct["balance"] == pytest.approx(10000.0 + j[0]["pnl"])
    assert fm.limits and all(x < 100 for x in fm.limits)          # small kline requests (weight 1, not 10)


def test_kline_limit():
    from src.lab.scheduler import kline_limit
    now = 1_800_000_000_000
    assert kline_limit(now - 60_000, now) == 5
    assert kline_limit(now - 30 * 60_000, now) == 32
    assert kline_limit(now - 10 * 86400_000, now) == 1500


def test_slot_sizing_caps_skips_and_logs(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 10.0)
    b = _create(conn, mode="slot", symbols=("BTCUSDT", "SOLUSDT", "XRPUSDT"))
    _open_signal(conn, b, "BTCUSDT", "long", nm=0.6, price=10.0)
    r = _open_rows(conn, b["account_id"])[0]
    assert r["qty"] * r["entry_price"] == pytest.approx(10000.0 / 3 * 0.6, rel=1e-3)   # slot x engine VT60
    _open_signal(conn, b, "SOLUSDT", "long", nm=None, price=10.0)                       # no engine size
    assert len(_open_rows(conn, b["account_id"])) == 1
    ev = store.events(conn, b["id"])
    assert ev[0]["reason"] == "ukuran_engine_tidak_ada" and ev[0]["symbol"] == "SOLUSDT" and ev[0]["bar"]
    # per-position cap 0.25x
    _open_signal(conn, b, "XRPUSDT", "long", nm=1.9, price=10.0)
    x = next(p for p in _open_rows(conn, b["account_id"]) if p["symbol"] == "XRPUSDT")
    assert x["qty"] * 10.0 == pytest.approx(2500.0, rel=1e-3)
    assert store.events(conn, b["id"])[0]["reason"] == "cap_posisi"


def test_gross_cap_shrinks_then_skips(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 10.0)
    b = _create(conn, symbols=("BTCUSDT", "SOLUSDT", "XRPUSDT"))
    _raw_open(conn, b, "BTCUSDT", qty=1400.0, price=10.0)          # open notional 14,000 (1.4x of the 1.5x cap)
    w = _watch(conn, b, "SOLUSDT")
    pos = {"side": "long", "entry_price": 10.0, "entry_time": _bar_after_start(b), "sl": 9.95, "tp": None}
    plan = sizing.entry_plan(conn, store.get(conn, b["id"]), dict(w), pos, 10.0)   # wants ~4,545 notional
    assert plan["skip"] is None and plan["qty"] * 10.0 == pytest.approx(1000.0, rel=1e-3)
    assert store.events(conn, b["id"])[0]["reason"] == "cap_total"
    paper.open_position(conn, account_id=b["account_id"], symbol="SOLUSDT", side="long", price=10.0, sl=9.0,
                        qty=99.0, watch_id=w["id"], source="paper_auto")       # room left ~10 USDT
    w3 = _watch(conn, b, "XRPUSDT")
    plan = sizing.entry_plan(conn, store.get(conn, b["id"]), dict(w3), pos, 10.0)
    assert plan["skip"] == "cap_total" and plan["qty"] is None


def test_signal_from_before_the_start_is_not_mirrored(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn)
    old_bar = iso(to_epoch(b["created_at"]) - 5 * 3600)            # closed 1 h before the basket existed
    _open_signal(conn, b, "BTCUSDT", "long", sl=90.0, bar=old_bar)
    assert _open_rows(conn, b["account_id"]) == []
    assert store.events(conn, b["id"])[0]["reason"] == "sebelum_mulai"


def test_kill_switch_stops_the_basket_for_good(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn)
    pid = _raw_open(conn, b, "BTCUSDT", qty=200.0, price=100.0)
    paper.close_position(conn, pid, 90.0, "hard_sl")               # about -2,000 on 10,000 = -20%
    _open_signal(conn, b, "SOLUSDT", "long", sl=90.0)
    assert _open_rows(conn, b["account_id"]) == []
    bb = store.get(conn, b["id"])
    assert bb["active"] is False and store.events(conn, b["id"])[0]["kind"] == "kill"
    n = conn.execute("SELECT COUNT(*) FROM notifications WHERE dedupe_key=?", (f"basket:{b['id']}:kill",)).fetchone()[0]
    assert n == 1
    _open_signal(conn, b, "XRPUSDT", "long", sl=90.0)
    assert store.events(conn, b["id"])[0]["reason"] == "basket_berhenti"
    assert report.build(conn)["rows"][0]["evaluation"]["status"] == "GAGAL"


def test_kill_rule_also_reads_the_equity_curve(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn)
    pid = _raw_open(conn, b, "BTCUSDT", qty=200.0, price=100.0)
    s = to_epoch(b["created_at"])                                   # the equity curve keeps one point per second
    paper.close_position(conn, pid, 90.0, "hard_sl", when=iso(s + 3600))   # -20%, no new entry afterwards
    ev = report.build(conn, now=s + 7200)["rows"][0]["evaluation"]
    assert ev["status"] == "GAGAL" and ev["kill"]["source"] == "kurva" and ev["kill"]["dd_pct"] <= -15.0
    assert store.events(conn, b["id"]) == []                       # the report never writes


def test_normal_watches_keep_their_sizing(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 2000.0)
    _create(conn)                                                   # a basket exists, but this watch is not in it
    acct = paper.create_account(conn, "solo", 10000.0, 100.0, 2.0)
    wid = conn.execute(
        "INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, autopaper_account_id, "
        "autopaper_enabled, created_at) VALUES ('rosyade_family','ETHUSDT','4h','{}','{}',?,1,?)",
        (acct, "2026-11-01T00:00:00Z")).lastrowid
    conn.commit()
    w = dict(conn.execute("SELECT * FROM watches WHERE id=?", (wid,)).fetchone())
    sig = {"time": "2026-11-08T20:00:00Z", "action": "open", "side": "long", "price": 2000.0}
    pos = {"side": "long", "entry_price": 2000.0, "entry_time": sig["time"], "sl": 1740.0, "tp": None,
           "notional_mult": 0.8}
    watch_eval._autopaper(conn, w, None, {"last_bar": sig["time"], "position": pos, "last_signal": sig})
    row = conn.execute("SELECT * FROM paper_positions WHERE watch_id=?", (wid,)).fetchone()
    assert row["qty"] * 2000.0 == pytest.approx(8000.0)


# ── report: progress, per coin, checkpoints, fidelity ──────────────────────

def _simulate(conn, b, n, win_ret=2.0, loss_ret=-1.0, wins_every=2, diff_pp=0.0, start_days=1.0, gap_h=22.0):
    """n closed basket trades (constant 1,000 notional) spread over coins and days, with the engine's own
    trades written to watch_state (pnl_pct = paper return + diff_pp)."""
    s = to_epoch(b["created_at"])
    eng: dict[int, list] = {}
    for i in range(n):
        sym = b["symbols"][i % len(b["symbols"])]
        w = _watch(conn, b, sym)
        sig_open = s - s % 14400 + 14400 * (1 + int((start_days * 86400 + i * gap_h * 3600) // 14400))
        close = sig_open + 14400
        ret = win_ret if i % wins_every == 0 else loss_ret
        p = paper.open_position(conn, account_id=b["account_id"], symbol=sym, side="long", price=100.0, sl=80.0,
                                qty=10.0, watch_id=w["id"], source="paper_auto", when=iso(close + 60))
        exit_s = close + 3 * 14400
        out = paper.close_position(conn, p["id"], 100.0 * (1 + ret / 100.0), "strategy_exit:x",
                                   when=iso(exit_s + 60), slipped=True)   # 1 min after the engine's bar close
        pret = out["pnl"] / (out["qty"] * out["entry_price"]) * 100.0
        eng.setdefault(w["id"], []).append({"entry_time": iso(sig_open), "exit_time": iso(exit_s - 14400),
                                            "side": "long", "pnl_pct": pret + diff_pp,
                                            "return_on_equity_pct": (pret + diff_pp) / 10.0})
    for wid, trades in eng.items():
        conn.execute("INSERT OR REPLACE INTO watch_state (watch_id, computed_at, last_bar, position_json, "
                     "recent_trades_json, last_signal_json, error) VALUES (?, ?, ?, NULL, ?, NULL, NULL)",
                     (wid, iso(s), iso(s), json.dumps(trades)))
    conn.commit()
    return s


def test_report_progress_per_coin_and_waiting_hint(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn, symbols=TEN)
    s = _simulate(conn, b, 4)
    # SOL's strategy holds a short from 8 Nov (before paper started): the coin waits for a NEW signal
    sol = _watch(conn, b, "SOLUSDT")
    conn.execute("UPDATE watch_state SET position_json=? WHERE watch_id=?",
                 (json.dumps({"side": "short", "entry_price": 150.0, "entry_time": iso(s - 4 * 86400), "sl": 160.0}),
                  sol["id"]))
    conn.commit()
    body = report.build(conn, now=s + 10 * 86400)
    row = body["rows"][0]
    assert row["progress"] == {"n": 4, "of": 30} and row["stats"]["n_closed"] == 4
    assert row["gate"]["coins"] == 4 and row["gate"]["need_trades"] == 30 and row["gate"]["need_days"] == 28
    c = {x["coin"]: x for x in row["coins"]}
    assert len(c) == 10 and c["BTC"]["trades"] == 1 and c["LTC"]["trades"] == 0
    assert c["SOL"]["status"] == "menunggu_sinyal_baru" and c["SOL"]["strategy_position"]["opened_before_paper"]
    assert row["waiting"] == {"n": 1, "coins": ["SOL"]}
    assert row["evaluation"]["status"] == "BELUM" and row["evaluation"]["next"]["checkpoint"] == 1
    assert row["fidelity"]["coverage"] == 1.0 and row["fidelity"]["median_abs_diff_pp"] == pytest.approx(0.0, abs=1e-9)
    assert "curve" not in row and len(row["spark"]) >= 2
    d = report.detail(conn, b["id"], now=s + 10 * 86400)
    assert len(d["trades"]) == 4 and d["curve"][0]["equity"] == 10000.0 and d["rules"]["review_min_trades"] == 30
    assert report.detail(conn, 999) is None
    json.dumps(body)                                               # JSON-safe (no inf / nan)


@pytest.mark.parametrize("win_ret,loss_ret,diff_pp,expected", [
    (2.0, -1.0, 0.0, "LULUS"),        # PF ~2
    (1.42, -1.0, 0.0, "LANJUT"),      # PF ~1.1 after fees
    (0.8, -1.0, 0.0, "GAGAL"),        # PF ~0.8
    (2.0, -1.0, 1.0, "TIDAK_SAH"),    # paper drifts 1 pp from the engine on every trade
])
def test_checkpoint_one_outcomes(conn, monkeypatch, win_ret, loss_ret, diff_pp, expected):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn, symbols=TEN)
    s = _simulate(conn, b, 32, win_ret=win_ret, loss_ret=loss_ret, diff_pp=diff_pp)
    row = report.build(conn, now=s + 45 * 86400)["rows"][0]
    ev = row["evaluation"]
    assert ev["status"] == expected, ev
    cp = ev["checkpoints"][0]
    assert cp["checkpoint"] == 1 and cp["trades"] >= 30 and datetime.fromisoformat(cp["at"][:-1]).weekday() == 0
    assert cp["dd_limit_pct"] == -15.0                               # min(-5, -1.5 x 10)
    if expected == "TIDAK_SAH":
        assert "selisih_hasil" in cp["invalid_reasons"]
    else:
        assert cp["fidelity"]["coverage"] == 1.0 and cp["engine_decision"] == cp["pf_decision"]


def test_checkpoint_waits_for_the_monday_and_the_deadline(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn, symbols=TEN)
    s = _simulate(conn, b, 32)
    ev = report.build(conn, now=s + 20 * 86400)["rows"][0]["evaluation"]
    assert ev["status"] == "BELUM" and ev["checkpoints"] == [] and ev["next"]["checkpoint"] == 1
    assert ev["next"]["due"] is None                               # < 30 closed trades by day 20
    pts = report._points(report._Ctx(conn, store.get(conn, b["id"]), s + 60 * 86400))
    due = rules.checkpoint_due(pts, s, 1)
    assert due["due_s"] > due["met_s"] >= s + 28 * 86400
    ev = report.build(conn, now=(due["met_s"] + due["due_s"]) / 2)["rows"][0]["evaluation"]
    assert ev["status"] == "BELUM" and ev["next"]["due"] == iso(due["due_s"])   # met, waiting for the Monday
    assert datetime.fromisoformat(ev["next"]["due"][:-1]).weekday() == 0
    b2 = _create(conn, symbols=TEN[:3], name="4H-BASKET-Slow")
    ev2 = report.detail(conn, b2["id"], now=to_epoch(b2["created_at"]) + 85 * 86400)["evaluation"]
    assert ev2["status"] == "TIDAK_CUKUP_DATA"


def test_missed_engine_entry_is_explained(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn, symbols=TEN)
    s = _simulate(conn, b, 3)
    w = _watch(conn, b, "LTCUSDT")
    bar = iso(s - s % 14400 + 14400 * 20)
    conn.execute("INSERT OR REPLACE INTO watch_state (watch_id, computed_at, last_bar, position_json, "
                 "recent_trades_json, last_signal_json, error) VALUES (?, ?, ?, NULL, ?, NULL, NULL)",
                 (w["id"], iso(s), iso(s), json.dumps([{"entry_time": bar, "exit_time": bar, "side": "long",
                                                         "pnl_pct": 1.0, "return_on_equity_pct": 0.1}])))
    conn.commit()
    store.log_event(conn, b["id"], "skip", "cap_total", watch_id=w["id"], symbol="LTCUSDT", bar=bar)
    d = report.detail(conn, b["id"], now=s + 30 * 86400)
    f = d["fidelity"]
    assert f["expected"] == 4 and f["matched"] == 3 and f["coverage"] == 0.75 and not f["coverage_ok"]
    assert f["missed"] == [{"symbol": "LTCUSDT", "coin": "LTC", "side": "long", "signal_time": bar,
                            "reason": "cap_total"}]


# ── side effects elsewhere ─────────────────────────────────────────────────

def test_only_milestone_notifications(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn, symbols=TEN)
    _simulate(conn, b, 11)
    rows = conn.execute("SELECT title, link, dedupe_key FROM notifications WHERE type='paper' ORDER BY id").fetchall()
    assert [r["dedupe_key"] for r in rows] == [f"basket:{b['id']}:n1", f"basket:{b['id']}:n10"]
    assert rows[1]["title"] == "Paper Basket uji: 10/30 transaksi" and rows[1]["link"] == f"/lab/arena?basket={b['id']}"


def test_ledger_leaves_basket_watches_out(conn, monkeypatch):
    from src.lab.ledger.collect import collect_lab_watches
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 100.0)
    b = _create(conn, symbols=TEN)
    _simulate(conn, b, 5)
    assert collect_lab_watches(conn) == 0


def test_basket_code_never_imports_trading_or_places_orders():
    files = [*(ROOT / "src/lab/basket").glob("*.py"), ROOT / "src/api/basket_routes.py", ROOT / "ops/lab_seed_baskets.py"]
    for f in files:
        text = f.read_text()
        imports = [ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any("trading" in ln for ln in imports), f
        for bad in ("/fapi/v1/order", "create_order", "lab_alerts", "send_message"):
            assert bad not in text.lower(), (f, bad)
    for f in (ROOT / "src/lab/basket").glob("*.py"):
        assert "paper.open_position" not in f.read_text() and "close_position(" not in f.read_text(), f


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


def test_api_admin_only_read_only_and_watch_guard(api, conn):
    assert api("u-plain").get("/api/v1/lab/baskets").status_code == 403
    assert api("u-admin").get("/api/v1/lab/baskets").json()["rows"] == []
    b = _create(conn, symbols=TEN)
    r = api("u-admin").get("/api/v1/lab/baskets")
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert {"basket", "account", "stats", "progress", "gate", "evaluation", "coins", "waiting", "fidelity",
            "expect", "drift", "spark"} <= set(row)
    assert row["basket"]["n_coins"] == 10 and row["progress"] == {"n": 0, "of": 30}
    d = api("u-admin").get(f"/api/v1/lab/baskets/{b['id']}")
    assert d.status_code == 200 and {"curve", "trades", "events", "rules"} <= set(d.json())
    assert api("u-admin").get("/api/v1/lab/baskets/999").status_code == 404
    assert api("u-plain").get(f"/api/v1/lab/baskets/{b['id']}").status_code == 403
    wid = store.members(conn, b["id"])[0]["watch_id"]
    assert api("u-admin").delete(f"/api/v1/lab/watches/{wid}").status_code == 409
    assert api("u-admin").post(f"/api/v1/lab/watches/{wid}/autopaper", json={"enabled": False}).status_code == 409
    assert conn.execute("SELECT autopaper_enabled FROM watches WHERE id=?", (wid,)).fetchone()[0] == 1


# ── seed script ────────────────────────────────────────────────────────────

@pytest.fixture
def seed_mod(lab_env, monkeypatch):
    monkeypatch.setenv("LAB_TELEGRAM_ENABLED", "0")
    spec = importlib.util.spec_from_file_location("lab_seed_baskets", ROOT / "ops/lab_seed_baskets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_cache(lab_env, rows=5000, skip=()):
    d = lab_env / "cache"
    d.mkdir(parents=True, exist_ok=True)
    idx = {}
    for s in PREREG["baskets"][0]["symbols"]:
        if s in skip:
            continue
        (d / f"{s}_PERP_4h.parquet").write_bytes(b"")
        idx[f"{s}_4h"] = {"symbol": s, "timeframe": "4h", "first": "2020-01-01T00:00:00+00:00",
                          "last": "2026-11-12T08:00:00+00:00", "rows": rows}
    (d / "_index.json").write_text(json.dumps(idx))


def _counts(conn):
    store.ensure_schema(conn)
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("lab_baskets", "lab_basket_members", "paper_accounts", "watches")}


def test_seed_dry_run_apply_idempotent(seed_mod, conn, lab_env):
    _fake_cache(lab_env)
    before = _counts(conn)
    assert seed_mod.main(["--manifest", str(MANIFEST_PATH)]) == 0
    assert _counts(conn) == before
    assert seed_mod.main(["--manifest", str(MANIFEST_PATH), "--apply"]) == 0
    assert _counts(conn) == {"lab_baskets": 2, "lab_basket_members": 57, "paper_accounts": 2, "watches": 57}
    assert seed_mod.main(["--manifest", str(MANIFEST_PATH), "--apply"]) == 0
    assert _counts(conn)["watches"] == 57
    a, bb = store.list_baskets(conn)
    assert a["expect"]["trades"] > 0 and a["prereg"]["commit"] == rules.PREREG_COMMIT
    assert "ETHUSDT" not in bb["symbols"] and len(bb["symbols"]) == 28
    acct = paper.get_account(conn, bb["account_id"])
    assert (acct["name"], acct["risk_pct"], acct["leverage_max"]) == ("Paper 4H-BASKET-RosyadeVT60", 100.0, 0.25)


def test_seed_refuses_missing_data_and_a_changed_manifest(seed_mod, conn, lab_env, tmp_path):
    _fake_cache(lab_env, skip=("HYPEUSDT",))
    assert seed_mod.main(["--manifest", str(MANIFEST_PATH), "--apply"]) == 1
    assert _counts(conn)["lab_baskets"] == 0
    _fake_cache(lab_env, rows=1000)                                  # < 1300 bars everywhere
    assert seed_mod.main(["--manifest", str(MANIFEST_PATH), "--apply"]) == 1
    _fake_cache(lab_env)
    m = json.loads(MANIFEST_PATH.read_text())
    m["baskets"][0]["sizing"]["risk_pct"] = 0.5                      # not the pre-registered sizing
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m))
    assert seed_mod.main(["--manifest", str(p), "--apply", "--only", "4H-BASKET-DonchianDef"]) == 1
    assert _counts(conn)["lab_baskets"] == 0


def test_seed_respects_the_active_watch_cap(seed_mod, conn, lab_env, monkeypatch):
    from src.lab import settings as lab_settings
    _fake_cache(lab_env)
    monkeypatch.setenv("LAB_WATCH_MAX_ACTIVE", "40")
    lab_settings.get_lab_settings.cache_clear()
    assert seed_mod.main(["--manifest", str(MANIFEST_PATH), "--apply"]) == 1
    assert _counts(conn)["lab_baskets"] == 1                        # A (29) fits, B (+28) would not
