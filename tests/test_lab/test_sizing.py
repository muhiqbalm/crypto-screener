"""Position-sizing params on the Rosyade family template (research; default = live sizing)."""
import os
import sys
from pathlib import Path

import pytest

from src.lab import engine_adapter as ea
from src.lab.templates import rosyade_family as T

VT = {"sizing_mode": "vol_target", "vol_target_pct": 60.0, "vol_lookback": 60, "max_notional_mult": 2.0}


def test_sizing_params_default_off_and_grouped():
    d = T.defaults()
    assert d["sizing_mode"] == "margin" and d["dd_derisk_pct"] == 0.0 and not T.is_sized(d)
    assert T.SIZING_KEYS == {"sizing_mode", "risk_per_trade_pct", "max_notional_mult", "vol_target_pct",
                             "vol_lookback", "dd_derisk_pct", "dd_derisk_mult"}
    assert not any(p["tunable"] for p in T.PARAMS if p["key"] in T.SIZING_KEYS)  # optimiser unchanged
    assert T.is_sized(T.validate_params(VT)) and T.is_sized(T.validate_params({"dd_derisk_pct": 20.0}))
    assert not T.is_sized(T.validate_params({"portfolio_risk": 25.0}))  # margin% is the live knob
    with pytest.raises(T.ParamError, match="expected one of"):
        T.validate_params({"sizing_mode": "kelly"})


def test_stored_params_without_sizing_keys_still_validate():
    old = {k: v for k, v in T.defaults().items() if k not in T.SIZING_KEYS}
    assert T.validate_params(old) == T.defaults()


def _engine_with_sizing():
    eng = Path(os.environ.get("LAB_ENGINE_PATH", "/root/bmtm-v2"))
    cfg_py = eng / "backtest_engine" / "config" / "strategy_config.py"
    if not cfg_py.exists() or "sizing_mode" not in cfg_py.read_text():
        pytest.skip("engine without sizing modes")
    pytest.importorskip("loguru")
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))


def test_build_configs_passes_sizing_only_when_set(lab_env):
    _engine_with_sizing()
    cfg, _ = ea.build_configs(VT, "4h", {})
    assert (cfg.sizing_mode, cfg.vol_target_pct, cfg.vol_lookback) == ("vol_target", 60.0, 60)
    plain, _ = ea.build_configs({"portfolio_risk": 25.0}, "4h", {})
    assert plain.sizing_mode == "margin" and plain.portfolio_risk == 25.0


def test_build_configs_default_omits_sizing_fields(lab_env, monkeypatch):
    """With live sizing the StrategyConfig kwargs are exactly the pre-sizing set (old engines work)."""
    seen = {}

    class Fake:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(ea, "_engine", lambda: {"StrategyConfig": Fake, "EngineConfig": lambda **kw: kw})
    ea.build_configs({}, "4h", {})
    assert not (set(seen) & T.SIZING_KEYS)
    ea.build_configs(VT, "4h", {})
    assert seen["sizing_mode"] == "vol_target"
