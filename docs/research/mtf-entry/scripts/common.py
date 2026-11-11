"""Shared setup for the MTF-entry research (DEVELOPMENT data only unless stated)."""
import json
import os
import sys

EXP = "/tmp/mtf/exp"
os.environ.setdefault("LAB_ENGINE_PATH", "/tmp/mtf/Automate_Execution")
os.environ["LAB_DATA_DIR"] = f"{EXP}/data"
os.environ["LAB_DB_PATH"] = f"{EXP}/lab.db"
os.environ["LAB_ARTIFACTS_DIR"] = f"{EXP}/artifacts"
os.environ["LAB_DATA_OFFLINE"] = "1"
os.environ["LAB_TELEGRAM_ENABLED"] = "0"
sys.path.insert(0, "/tmp/mtf/crypto-screener")

import pandas as pd  # noqa: E402

from src.lab import data_cache as dc  # noqa: E402
from src.lab import engine_adapter as ea  # noqa: E402
from src.lab import honesty  # noqa: E402
from src.lab.templates import rosyade_family as T  # noqa: E402

START, END, TF = "2020-01-01", "2026-11-09", "4h"
COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}
COINS = ["ETHUSDT", "BTCUSDT", "SOLUSDT"]
_raw = {}


def raw(sym, tf, funding=False):
    k = (sym, tf)
    if k not in _raw:
        _raw[k] = dc.ensure(sym, tf, funding=True, offline=True) if tf == TF else \
            (dc.ensure(sym, tf, funding=False, offline=True)[0], None)
    return _raw[k]


_frames = {}


def frames(sym, params):
    """(full_df, dev_df, warmup, holdout_start) exactly as the Lab runner builds them."""
    p = T.validate_params(params)
    cfg, ecfg = ea.build_configs(p, TF, COSTS)
    etf = p["entry_tf"] if T.is_mtf(p) else None
    key = (sym, etf, ecfg.warmup_period)
    if key not in _frames:
        ohlcv, fund = raw(sym, TF)
        if etf:
            ohlcv = ea.attach_entry_bars(ohlcv, raw(sym, etf)[0], TF, etf)
        df, es, ee, _ = ea.prepare_frame(ohlcv, fund, TF, START, END, ecfg.warmup_period, True)
        hs = honesty.proposed_holdout_start(es, ee, ea.TF_SECONDS[TF])
        dev = df[df["timestamp"] < pd.Timestamp(hs)].reset_index(drop=True)
        honesty.assert_dev_only(dev["timestamp"].tail(1), hs)
        _frames[key] = (df, dev, ecfg.warmup_period, hs, honesty.iso(es), honesty.iso(ee))
    return _frames[key]


def dev_eval(sym, params):
    """Development-period metrics (never the holdout)."""
    df, dev, warm, hs, _, _ = frames(sym, params)
    cfg, ecfg = ea.build_configs(params, TF, COSTS)
    res, ind = ea.run(dev, cfg, ecfg, warmup=warm)
    m = ea.metrics(res)
    segs = ea.segment_returns(res)
    st, _ = ea.run(dev, cfg, ea.scaled_costs(ecfg, 2.0, warmup_period=warm), indicators=ind)
    out = {k: m.get(k) for k in ("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades",
                                 "win_rate_pct", "fees_paid", "liquidations")}
    out.update(segments=[round(x, 2) for x in segs], score=ea.robust_score(m, segs, 30),
               stress2x_net_pct=ea.metrics(st)["net_return_pct"], entry=m.get("entry"))
    return out


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)
