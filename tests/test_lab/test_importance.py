"""Parameter importance (research file -> finished runs -> template order) and the read-only
holdout-lock route. Uses an isolated lab.db; never touches bmtm_trading.db."""
import json

import pytest

from src.lab import db as labdb
from src.lab import honesty
from src.lab import importance as imp
from src.lab.templates import TEMPLATES
from src.lab.templates import donchian_breakout as D
from src.lab.templates import mean_reversion_range as M
from src.lab.templates import rosyade_family as R


# ── research snapshot ────────────────────────────────────────────────────

def test_snapshot_loads_and_covers_4h_1d_for_every_template():
    data = imp.load_research()
    assert data is not None
    for tid in TEMPLATES:
        for tf in ("4h", "1d"):
            assert (tid, tf) in data["entries"], (tid, tf)
    assert data["meta"]["date"] == "2026-11-12"
    assert data["meta"]["window"] == {"start": "2023-01-01", "end": "2026-11-09"}


def test_research_source_states_source_and_basis():
    out = imp.for_template(None, D, "4h")
    assert out["source"] == "research"
    assert out["basis"] == "riset 12 Nov 2026"
    assert out["n_trials"] == 4608 and out["n_coins"] == 24
    assert "4,608" in out["basis_detail"]
    assert out["note"] and "holdout" in out["note"]
    first = out["params"][0]
    assert first["key"] == "dc_atr_mult" and first["rank"] == 1
    assert first["label"] == imp.LABEL_STABLE and first["tunable"] is True
    assert first["recommended"]["range"] == [4.7, 9.9]
    assert first["score_ci"] is None          # combined_share has no CI of its own; none is invented
    assert [p["rank"] for p in out["params"]] == list(range(1, len(out["params"]) + 1))


def test_lab_keys_translate_composites():
    out = imp.for_template(None, D, "1d")
    rows = {p["key"]: p for p in out["params"]}
    assert rows["sides"]["lab_keys"] == ["enable_long", "enable_short"]
    assert rows["sides"]["label"] == imp.LABEL_STABLE
    assert rows["sides"]["recommended"]["values"] == ["long"]
    assert rows["sides"]["tunable"] is False             # the optimiser cannot search a composite
    assert rows["notional_mult"]["lab_keys"] == ["portfolio_risk", "leverage"]
    for p in out["params"]:
        assert all(k in D.PARAM_INDEX for k in p["lab_keys"])


@pytest.mark.parametrize("tm,tf,stable", [
    (R, "4h", {"long_sl_pct", "atr_mult_weak_long"}),
    (D, "4h", {"dc_atr_mult"}),
    (D, "1d", {"sides", "dc_entry_len"}),
    (M, "4h", {"mr_mult", "mr_regime", "mr_len"}),
])
def test_stable_params_match_the_research_summary(tm, tf, stable):
    out = imp.for_template(None, tm, tf)
    assert {p["key"] for p in out["params"] if p["label"] == imp.LABEL_STABLE} == stable
    assert out["labels"][imp.LABEL_STABLE] == len(stable)


def test_importance_never_changes_template_defaults():
    before = {tid: json.dumps(t.defaults(), sort_keys=True) for tid, t in TEMPLATES.items()}
    for tm in TEMPLATES.values():
        for tf in tm.TIMEFRAMES:
            imp.for_template(None, tm, tf)
    assert before == {tid: json.dumps(t.defaults(), sort_keys=True) for tid, t in TEMPLATES.items()}


# ── tolerant loader ──────────────────────────────────────────────────────

def test_loader_missing_and_broken_files(tmp_path):
    assert imp.load_research(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert imp.load_research(bad) is None
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"templates": [{"template_id": "x"}, 3, None], "rows": "nope"}))
    assert imp.load_research(empty) is None


def test_loader_rereads_a_replaced_file(tmp_path):
    p = tmp_path / "imp.json"
    p.write_text(json.dumps({"date": "2026-11-12", "rows": [
        {"template": "rosyade_family", "tf": "1h", "param": "long_sl_pct", "importance_mean": 0.3}]}))
    assert imp.load_research(p)["meta"]["date"] == "2026-11-12"
    p.write_text(json.dumps({"date": "2026-11-20", "rows": [
        {"template": "rosyade_family", "tf": "1h", "param": "short_sl_pct", "importance_mean": 0.5},
        {"template": "rosyade_family", "tf": "1h", "param": "swing_len", "importance_mean": 0.25}]}))
    assert imp.load_research(p)["meta"]["date"] == "2026-11-20"


def test_flat_rows_format_and_bad_entries_are_skipped():
    raw = {"date": "2026-11-20", "rows": [
        {"template": "rosyade_family", "tf": "1H", "param": "long_sl_pct", "importance_mean": 0.031,
         "importance_ci": [0.02, 0.04], "stability_label": "penting & stabil", "recommended_default": 13.0,
         "recommended_range": [6.5, 29.5]},
        {"template": "rosyade_family", "tf": "1h", "param": "swing_len", "importance_mean": "big",
         "stability_label": "very important"},                               # bad score + unknown label
        {"template": "rosyade_family", "tf": "1h", "param": "gone_param", "importance_mean": 0.9},
        {"template": "rosyade_family", "tf": "1h", "param": "ema_htf_len", "importance_mean": 0.01,
         "importance_ci": [0.05, 0.01]},                                      # inverted CI -> dropped
        {"tf": "1h", "param": "x"},                                           # no template
        "garbage",
    ]}
    data = imp.normalise_research(raw)
    out = imp.research_source(R, "1h", data)
    assert out["source"] == "research" and out["basis"] == "riset 20 Nov 2026"
    keys = [p["key"] for p in out["params"]]
    assert keys[0] == "long_sl_pct"            # gone_param (not in the template) is skipped
    assert "gone_param" not in keys
    lsl = out["params"][0]
    assert lsl["score_ci"] == [0.02, 0.04]
    assert lsl["recommended"] == {"range": [6.5, 29.5], "values": None, "default": 13.0, "current_inside": None}
    swing = next(p for p in out["params"] if p["key"] == "swing_len")
    assert swing["label"] is None and swing["score"] is None and swing["rank"] == len(keys)   # unscored last
    ema = next(p for p in out["params"] if p["key"] == "ema_htf_len")
    assert ema["score_ci"] is None


def test_lab_keys_partly_unknown_are_trimmed():
    raw = {"templates": [{"template_id": "donchian_breakout", "tf": "4h", "params": [
        {"param": "sides", "lab_keys": ["enable_long", "no_such_key"], "combined_share": 0.2},
        {"param": "ghost", "lab_keys": ["nope"], "combined_share": 0.9}]}]}
    out = imp.research_source(D, "4h", imp.normalise_research(raw))
    assert [p["lab_keys"] for p in out["params"]] == [["enable_long"]]


# ── runs source (sensitivity of finished runs) ───────────────────────────

def _sens(effects: dict) -> dict:
    """Stored sensitivity: param -> variations whose net % spread equals the given swing."""
    return {"params": [{"param": k, "base": 1, "stability": 0.8, "profitable_fraction": 1.0, "fragile": False,
                        "variations": [{"value": 1, "net_pct": 10.0, "pf": 1.5, "trades": 40},
                                       {"value": 2, "net_pct": 10.0 + v, "pf": 1.5, "trades": 40}]}
                       for k, v in effects.items()], "unstable": 0, "threshold": 0.5}


def _run(conn, tf="1h", effects=None, status="done", mode="validate", template="rosyade_family"):
    extra = {"sensitivity": _sens(effects or {"long_sl_pct": 30.0, "short_sl_pct": 10.0, "cooldown_bars": 1.0})}
    rid = conn.execute(
        "INSERT INTO lab_runs (template_id, symbol, timeframe, mode, status, params_json, costs_json, extra_json, "
        "created_at) VALUES (?, 'ETHUSDT', ?, ?, ?, '{}', '{}', ?, ?)",
        (template, tf, mode, status, json.dumps(extra), labdb.utcnow())).lastrowid
    conn.commit()
    return rid


def test_runs_source_needs_five_finished_runs(conn):
    for _ in range(4):
        _run(conn)
    _run(conn, status="error")
    _run(conn, mode="backtest")
    _run(conn, tf="4h")
    assert imp.runs_source(conn, R, "1h") is None
    assert imp.for_template(conn, R, "1h")["source"] == "template"
    _run(conn)
    out = imp.for_template(conn, R, "1h")
    assert out["source"] == "runs" and out["n_runs"] == 5 and out["basis"] == "dari 5 run"
    assert [p["key"] for p in out["params"]] == ["long_sl_pct", "short_sl_pct", "cooldown_bars"]
    top = out["params"][0]
    assert top["label"] == imp.LABEL_STABLE and top["runs"] == 5 and top["runs_frac_important"] == 1.0
    assert out["params"][-1]["label"] == imp.LABEL_NONE


def test_runs_source_median_rank_and_unstable_label(conn):
    # long_sl_pct is the biggest mover in 3 of 5 runs only -> important on median, not stable
    for i in range(5):
        big = i < 3
        _run(conn, effects={"long_sl_pct": 40.0 if big else 0.5, "short_sl_pct": 10.0,
                            "chop_limit": 0.5 if big else 40.0})
    out = imp.runs_source(conn, R, "1h")
    rows = {p["key"]: p for p in out["params"]}
    assert [p["key"] for p in out["params"]] == ["long_sl_pct", "short_sl_pct", "chop_limit"]   # median rank
    assert rows["long_sl_pct"]["label"] == imp.LABEL_UNSTABLE
    assert rows["long_sl_pct"]["runs_frac_important"] == pytest.approx(0.6)
    assert rows["chop_limit"]["label"] == imp.LABEL_NONE and rows["short_sl_pct"]["label"] == imp.LABEL_NONE


def test_runs_source_ignores_unknown_params_and_broken_json(conn):
    for _ in range(5):
        _run(conn, effects={"long_sl_pct": 5.0, "made_up": 99.0, "short_sl_pct": 1.0})
    conn.execute("UPDATE lab_runs SET extra_json='{broken' WHERE id=(SELECT MIN(id) FROM lab_runs)")
    conn.commit()
    assert imp.runs_source(conn, R, "1h") is None          # 4 usable runs left
    _run(conn, effects={"long_sl_pct": 5.0, "short_sl_pct": 1.0})
    out = imp.runs_source(conn, R, "1h")
    assert [p["key"] for p in out["params"]] == ["long_sl_pct", "short_sl_pct"]


def test_research_wins_over_runs(conn):
    for _ in range(6):
        _run(conn, tf="4h")
    assert imp.for_template(conn, R, "4h")["source"] == "research"


# ── template fallback ────────────────────────────────────────────────────

def test_template_fallback_order(conn):
    out = imp.for_template(conn, R, "15m")
    assert out["source"] == "template" and out["basis"] == "urutan bawaan template"
    keys = [p["key"] for p in out["params"]]
    assert keys[:5] == imp.FALLBACK_ORDER["rosyade_family"]
    assert sorted(keys) == sorted(p["key"] for p in R.tunable_params())
    assert all(p["label"] is None and p["score"] is None for p in out["params"])
    donchian = [p["key"] for p in imp.for_template(conn, D, "1h")["params"]]
    assert donchian == [p["key"] for p in D.tunable_params()]


# ── API ──────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self.data = data


class FakeUsers:
    """Same fake users table as test_lab_api (admin by email from LAB_ADMIN_EMAILS)."""

    def __init__(self, emails):
        self.emails, self._id = emails, None

    def table(self, name):
        assert name == "users"
        return self

    def select(self, *_):
        return self

    def eq(self, _col, val):
        self._id = val
        return self

    def single(self):
        return self

    def execute(self):
        e = self.emails.get(self._id)
        return _Resp({"email": e} if e else None)


EMAILS = {"u-admin": "Boss@BMTM.io", "u-plain": "someone@x.io"}


@pytest.fixture
def api(lab_env):
    from fastapi.testclient import TestClient

    from src.api.app import create_app
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client

    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    return make


def test_importance_route(api):
    c = api("u-admin")
    r = c.get("/api/v1/lab/templates/donchian_breakout/importance?timeframe=4h")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "research" and body["params"][0]["key"] == "dc_atr_mult"
    assert c.get("/api/v1/lab/templates/rosyade_family/importance").json()["timeframe"] == "4h"
    assert c.get("/api/v1/lab/templates/rosyade_family/importance?timeframe=15m").json()["source"] == "template"
    assert c.get("/api/v1/lab/templates/nope/importance").status_code == 404
    assert c.get("/api/v1/lab/templates/rosyade_family/importance?timeframe=2h").status_code == 422
    assert api("u-plain").get("/api/v1/lab/templates/rosyade_family/importance").status_code == 403


def test_holdout_lock_route_is_read_only(api, conn):
    c = api("u-admin")
    q = "/api/v1/lab/holdout-lock?template_id=rosyade_family&symbol=ethusdt&timeframe=4h"
    body = c.get(q).json()
    assert body["locked"] is False and body["holdout_start"] is None and body["symbol"] == "ETHUSDT"
    assert conn.execute("SELECT COUNT(*) FROM holdout_locks").fetchone()[0] == 0   # a read never creates a lock
    hs = honesty.resolve_holdout(conn, "rosyade_family", "ETHUSDT", "4h", "2020-01-01", "2026-01-01", 14400)
    honesty.touch_holdout(conn, "rosyade_family", "ETHUSDT", "4h")
    body = c.get(q).json()
    assert body["locked"] is True and body["holdout_start"] == hs and body["touches"] == 1
    assert body["holdout_fraction"] == honesty.HOLDOUT_FRACTION
    assert c.get(q.replace("rosyade_family", "nope")).status_code == 404
    assert c.get(q.replace("ethusdt", "eth!")).status_code == 422
    assert api("u-plain").get(q).status_code == 403
