"""Donchian breakout + mean reversion (range) templates: schema, validation, engine translation, API."""
import pytest

from src.lab import engine_adapter as ea
from src.lab.templates import TEMPLATES, donchian_breakout as D, mean_reversion_range as M
from src.lab.templates import rosyade_family as T

FAMS = [D, M]


@pytest.mark.parametrize("t", FAMS)
def test_registry_schema_shape(t):
    assert TEMPLATES[t.TEMPLATE_ID] is t
    s = t.public_schema()
    assert s["id"] == t.TEMPLATE_ID and s["timeframes"] == T.TIMEFRAMES and "development" in s["description"]
    keys = [p["key"] for p in s["params"]]
    assert len(keys) == len(set(keys))
    for p in s["params"]:
        assert set(p) >= {"key", "label", "type", "default", "min", "max", "step", "group", "tunable"}
        if p["type"] == "choice":
            assert p["default"] in p["choices"]
        if p["type"] in ("int", "float"):
            assert p["min"] <= p["default"] <= p["max"], p["key"]
    # shared keys keep the Rosyade spelling (adapter HTF warm-up, MTF data, sizing in watches)
    assert {"enable_long", "enable_short", "use_ema_htf", "ema_htf_len", "ema_htf_tf", "leverage",
            "portfolio_risk", "warmup_bars", "maintenance_margin_pct"} <= set(keys)
    assert t.SIZING_KEYS == T.SIZING_KEYS and t.MTF_KEYS == T.MTF_KEYS
    assert t.validate_params({}) == t.defaults() and not t.is_mtf(t.defaults())
    assert t.is_sized(t.defaults())          # paper mirror always copies the engine notional
    assert t.defaults()["leverage"] == 2.0    # liquidation (~-50%) beyond the ATR stops
    assert 3 <= len(t.tunable_params()) <= 8
    assert t.ParamError is T.ParamError


def test_dev_chosen_defaults():
    d, m = D.defaults(), M.defaults()
    assert (d["dc_entry_len"], d["dc_exit_len"], d["dc_atr_mult"], d["ema_htf_tf"], d["sizing_mode"]) == \
        (100, 50, 4.0, "1d", "risk")
    assert (m["mr_regime"], m["mr_band"], m["mr_trigger"], m["sizing_mode"]) == ("chop", "bb", "reenter", "margin")


def test_registry_order_keeps_rosyade_first():
    assert list(TEMPLATES)[:3] == ["rosyade_family", "donchian_breakout", "mean_reversion_range"]


@pytest.mark.parametrize("t,bad,msg", [
    (D, {"dc_entry_len": 1}, "min"),
    (D, {"long_sl_pct": 5.0}, "unknown params"),            # Rosyade-only key
    (D, {"enable_long": False, "enable_short": False}, "at least one side"),
    (M, {"mr_rsi_os": 50.0, "mr_rsi_ob": 50.0}, "mr_rsi_os"),
    (M, {"mr_band": "donchian"}, "expected one of"),
    (M, {"mr_max_bars": 1.5}, "expected int"),
    (D, {"entry_mode": "ltf_close", "entry_tf": "1h"}, None),   # MTF valid on 4h (checked per TF below)
])
def test_validation(t, bad, msg):
    if msg is None:
        p = t.validate_params(bad)
        t.validate_for_timeframe(p, "4h")
        with pytest.raises(T.ParamError, match="entry_tf"):
            t.validate_for_timeframe(p, "1h")
        return
    with pytest.raises(T.ParamError, match=msg):
        t.validate_params(bad)


def test_resolve_search_uses_own_tunables():
    specs = D.resolve_search({"params": ["dc_entry_len"], "ranges": {"dc_entry_len": [20, 100]}})
    assert [(s["key"], s["min"], s["max"]) for s in specs] == [("dc_entry_len", 20, 100)]
    with pytest.raises(T.ParamError, match="not tunable"):
        D.resolve_search({"params": ["dc_atr_len"]})
    assert [s["key"] for s in M.resolve_search(None)] == [p["key"] for p in M.tunable_params()]


@pytest.mark.parametrize("t,fam", [(D, "donchian"), (M, "mean_reversion")])
def test_engine_fields(t, fam):
    f = t.engine_fields(t.defaults())
    assert f["strategy_family"] == fam and f["use_cooldown"] is True
    rosyade_cfg_keys = {k for k in T.defaults() if k not in T.ENGINE_KEYS}
    assert rosyade_cfg_keys <= set(f)                       # every required StrategyConfig field present
    assert not (set(f) & t.ENGINE_KEYS)
    assert f["use_ob_trail"] is False and f["use_be_lock"] is False and f["use_tp_check"] is False
    own = {k for k in t.defaults() if k.startswith(("dc_", "mr_"))}
    assert own and own <= set(f)


class _Fake:
    seen: dict = {}

    def __init__(self, **kw):
        _Fake.seen = kw
        self.__dict__.update(kw)


def _fake_engine(monkeypatch):
    from dataclasses import dataclass

    @dataclass
    class ECfg:
        warmup_period: int
        commission_pct: float
        slippage_pct: float
        maintenance_margin_pct: float
        use_liquidation: bool
        maker_commission_pct: float = None

    monkeypatch.setattr(ea, "_engine", lambda: {"StrategyConfig": _Fake, "EngineConfig": ECfg})


def test_build_configs_family_and_warmup(lab_env, monkeypatch):
    _fake_engine(monkeypatch)
    cfg, ecfg = ea.build_configs({}, "4h", {}, "donchian_breakout")
    s = _Fake.seen
    assert s["strategy_family"] == "donchian" and s["ema_htf_tf"] == "1d" and s["base_timeframe"] == "4h"
    assert ecfg.warmup_period == int(-(-(50 * 1.25 + 1) * 6 // 1))      # EMA-50 on closed 1D bars
    _, e2 = ea.build_configs({"dc_entry_len": 300, "use_ema_htf": False}, "4h", {}, "donchian_breakout")
    assert e2.warmup_period == D.min_warmup(D.validate_params({"dc_entry_len": 300})) >= 375
    cfg, ecfg = ea.build_configs({"ema_htf_tf": "1h"}, "4h", {}, "donchian_breakout")
    assert _Fake.seen["ema_htf_tf"] == "4h"                              # <= run TF -> same
    ea.build_configs({"entry_mode": "ltf_limit", "entry_tf": "1h"}, "4h", {}, "mean_reversion_range")
    assert _Fake.seen["strategy_family"] == "mean_reversion" and _Fake.seen["entry_mode"] == "ltf_limit"
    with pytest.raises(T.ParamError):
        ea.build_configs({"dc_entry_len": 5}, "4h", {}, "mean_reversion_range")
    with pytest.raises(ValueError, match="unknown template_id"):
        ea.build_configs({}, "4h", {}, "nope")


def test_build_configs_rosyade_path_unchanged(lab_env, monkeypatch):
    _fake_engine(monkeypatch)
    ea.build_configs({}, "4h", {})
    a = dict(_Fake.seen)
    ea.build_configs({}, "4h", {}, "rosyade_family")
    assert _Fake.seen == a and "strategy_family" not in a and not (set(a) & T.SIZING_KEYS)


# ── API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def admin(client_for):
    return client_for("u-admin")


from tests.test_lab.test_lab_api import client_for, RUN  # noqa: E402,F401  (fixture reuse)


def test_api_templates_and_runs(admin):
    ts = admin.get("/api/v1/lab/templates").json()
    assert [t["id"] for t in ts] == ["rosyade_family", "donchian_breakout", "mean_reversion_range"]
    for tid, key in (("donchian_breakout", "dc_entry_len"), ("mean_reversion_range", "mr_len")):
        r = admin.post("/api/v1/lab/runs", json={**RUN, "template_id": tid, "params": {key: 30}})
        assert r.status_code == 200, r.text
        d = admin.get(f"/api/v1/lab/runs/{r.json()['run_id']}").json()
        assert d["template_id"] == tid and d["params"][key] == 30 and "long_sl_pct" not in d["params"]
        bad = admin.post("/api/v1/lab/runs", json={**RUN, "template_id": tid, "params": {"long_sl_pct": 3}})
        assert bad.status_code == 422
        opt = admin.post("/api/v1/lab/runs", json={**RUN, "template_id": tid, "mode": "optimize", "n_trials": 10,
                                                    "search": {"params": [key]}})
        assert opt.status_code == 200, opt.text
        bad = admin.post("/api/v1/lab/runs", json={**RUN, "template_id": tid, "mode": "optimize", "n_trials": 10,
                                                    "search": {"params": ["long_sl_pct"]}})
        assert bad.status_code == 422


def test_api_scan_preset_watch(admin):
    sc = admin.post("/api/v1/lab/scans", json={"template_id": "donchian_breakout", "mode": "validate",
                                                "symbols": ["ETHUSDT", "BTCUSDT"], "timeframes": ["4h", "1d"],
                                                "params": {}, "costs": RUN["costs"]})
    assert sc.status_code == 200, sc.text
    p = admin.post("/api/v1/lab/presets", json={"label": "Donchian", "template_id": "donchian_breakout",
                                                 "symbol": "ETHUSDT", "timeframe": "4h", "params": {},
                                                 "costs": RUN["costs"]})
    assert p.status_code == 200, p.text
    lst = admin.get("/api/v1/lab/presets?template_id=donchian_breakout").json()
    assert [x["name"] for x in lst] == ["4H-ETH-Donchian"]
    w = admin.post("/api/v1/lab/watches", json={"template_id": "mean_reversion_range", "symbol": "ETHUSDT",
                                                 "timeframe": "4h", "params": {}, "costs": RUN["costs"]})
    assert w.status_code == 200, w.text
