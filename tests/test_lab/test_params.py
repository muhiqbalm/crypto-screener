import os
from pathlib import Path

import pytest

from src.lab.templates import TEMPLATES
from src.lab.templates import rosyade_family as T

ENGINE = Path(os.environ.get("LAB_ENGINE_PATH", "/root/bmtm-v2"))
PRESET = ENGINE / "backtest_engine/config/presets/eth_4h_rosyade.yaml"


def test_registry_and_schema_shape():
    assert "rosyade_family" in TEMPLATES
    s = T.public_schema()
    assert set(s) >= {"id", "name", "description", "timeframes", "params"}
    assert {"1h", "4h", "1d"} <= set(s["timeframes"])
    for p in s["params"]:
        assert set(p) >= {"key", "label", "type", "default", "min", "max", "step", "group"}
        assert p["type"] in ("int", "float", "bool", "choice")
        if p["type"] == "choice":
            assert p["default"] in p["choices"]
        if p["type"] in ("int", "float"):
            assert p["min"] <= p["default"] <= p["max"], p["key"]
    keys = [p["key"] for p in s["params"]]
    assert len(keys) == len(set(keys))


def test_defaults_validate():
    assert T.validate_params({}) == T.defaults()


@pytest.mark.skipif(not PRESET.exists(), reason="bmtm-v2 engine checkout not available")
def test_defaults_equal_live_eth_4h_preset():
    yaml = pytest.importorskip("yaml")
    preset = yaml.safe_load(PRESET.read_text())
    strat, eng = preset["strategy"], preset["engine"]
    d = T.defaults()
    for k, v in strat.items():
        if k in ("initial_capital", "base_timeframe"):
            continue
        if k in ("ema_htf_tf", "dcb_htf_input"):
            assert v == "240" and d[k] == "same"  # 4H HTF on a 4H chart == same timeframe
            continue
        assert k in d, k
        assert d[k] == v, (k, d[k], v)
    assert d["warmup_bars"] == eng["warmup_period"]
    strategy_keys = set(d) - T.ENGINE_KEYS - T.MTF_KEYS
    assert strategy_keys == set(strat) - {"initial_capital", "base_timeframe"}


@pytest.mark.parametrize("bad,msg", [
    ({"nope": 1}, "unknown"),
    ({"swing_len": 1.5}, "expected int"),
    ({"swing_len": True}, "expected int"),
    ({"enable_long": 1}, "expected bool"),
    ({"long_sl_pct": "13"}, "expected number"),
    ({"long_sl_pct": 99.0}, "max"),
    ({"cooldown_bars": -1}, "min"),
    ({"ema_htf_tf": "2h"}, "expected one of"),
    ({"macd_fast_len": 30, "macd_slow_len": 20}, "macd_fast_len"),
    ({"long_sl_pct": float("nan")}, "finite"),
])
def test_invalid_params(bad, msg):
    with pytest.raises(T.ParamError, match=msg):
        T.validate_params(bad)


def test_partial_override_and_int_from_float():
    p = T.validate_params({"swing_len": 3.0, "long_sl_pct": 10})
    assert p["swing_len"] == 3 and isinstance(p["swing_len"], int)
    assert p["long_sl_pct"] == 10.0 and isinstance(p["long_sl_pct"], float)
    assert p["short_sl_pct"] == 3.0


def test_tunable_subset():
    keys = {p["key"] for p in T.tunable_params()}
    assert {"long_sl_pct", "short_sl_pct", "ema_htf_len"} <= keys
    assert all(T.PARAM_INDEX[k]["type"] in ("int", "float") for k in keys)
