"""MTF entry timing on the Rosyade family template (4H signal, lower-TF entry)."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from src.lab import engine_adapter as ea
from src.lab.templates import rosyade_family as T

from .test_lab_api import RUN, client_for  # noqa: F401  (fixture re-export)

MTF = {"entry_mode": "ltf_limit", "entry_tf": "1h", "entry_atr_mult": 0.25, "entry_wait_bars": 8}


def test_mtf_params_default_off_and_grouped():
    d = T.defaults()
    assert d["entry_mode"] == "bar_close" and not T.is_mtf(d)
    assert T.MTF_KEYS == {p["key"] for p in T.PARAMS if p["group"] == T.G_MTF}
    assert {"entry_mode", "entry_tf", "entry_wait_bars", "entry_atr_mult", "maker_fee_pct",
            "limit_through_ticks", "entry_timeout", "ltf_stop_check"} <= T.MTF_KEYS
    assert not any(p["tunable"] for p in T.PARAMS if p["key"] in T.MTF_KEYS)  # optimiser default unchanged
    assert "maker_fee_pct" in T.ENGINE_KEYS
    schema = {p["key"]: p for p in T.public_schema()["params"]}
    assert schema["entry_mode"]["choices"] == T.ENTRY_MODES


@pytest.mark.parametrize("tf,etf,ok", [
    ("4h", "1h", True), ("4h", "30m", True), ("4h", "15m", True), ("1h", "15m", True), ("1d", "1h", True),
    ("1h", "1h", False), ("30m", "1h", False), ("15m", "15m", False),
])
def test_entry_tf_must_be_lower(tf, etf, ok):
    p = T.validate_params({**MTF, "entry_tf": etf})
    if ok:
        T.validate_for_timeframe(p, tf)
    else:
        with pytest.raises(T.ParamError, match="entry_tf"):
            T.validate_for_timeframe(p, tf)
    T.validate_for_timeframe(T.validate_params({"entry_tf": etf}), tf)  # bar_close: entry_tf ignored


def test_scaled_costs_scales_maker_fee():
    @dataclass
    class E:
        commission_pct: float = 0.05
        slippage_pct: float = 0.05
        slippage_bps: Optional[float] = None
        warmup_period: int = 300
        maker_commission_pct: Optional[float] = None

    s = ea.scaled_costs(E(maker_commission_pct=0.02), 2.0, warmup_period=10)
    assert (s.commission_pct, s.slippage_pct, s.maker_commission_pct, s.warmup_period) == (0.1, 0.1, 0.04, 10)
    assert ea.scaled_costs(E(), 0.0).maker_commission_pct is None
    assert ea.scaled_costs(E(maker_commission_pct=0.02), 0.0).maker_commission_pct == 0.0


def _engine_with_mtf():
    eng = Path(os.environ.get("LAB_ENGINE_PATH", "/root/bmtm-v2"))
    if not (eng / "backtest_engine" / "strategy" / "mtf_entry.py").exists():
        pytest.skip("engine without MTF entry timing")
    pytest.importorskip("loguru")
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))


def test_build_configs_mtf(lab_env, monkeypatch):
    _engine_with_mtf()
    cfg, ecfg = ea.build_configs(MTF, "4h", {"commission_pct": 0.05, "slippage_pct": 0.05})
    assert (cfg.entry_mode, cfg.entry_tf, cfg.entry_wait_bars) == ("ltf_limit", "1h", 8)
    assert ecfg.maker_commission_pct == 0.02
    plain, pe = ea.build_configs({}, "4h", {})
    assert plain.entry_mode == "bar_close" and pe.maker_commission_pct is None
    with pytest.raises(T.ParamError):
        ea.build_configs({**MTF, "entry_tf": "1h"}, "1h", {})


def test_api_mtf_run_ok_bad_tf_and_no_watch(client_for):  # noqa: F811
    c = client_for("u-admin")
    r = c.post("/api/v1/lab/runs", json={**RUN, "timeframe": "4h", "mode": "validate", "params": MTF})
    assert r.status_code == 200, r.text
    bad = c.post("/api/v1/lab/runs", json={**RUN, "timeframe": "1h", "params": {**MTF, "entry_tf": "1h"}})
    assert bad.status_code == 422 and "entry_tf" in bad.text
    w = c.post("/api/v1/lab/watches", json={"template_id": "rosyade_family", "symbol": "ETHUSDT",
                                             "timeframe": "4h", "params": MTF})
    assert w.status_code == 422 and "MTF" in w.text
