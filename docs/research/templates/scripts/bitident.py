"""Rosyade results must be bit-identical between (base backend + production engine 20c5e29) and
(new backend + new engine). Full range, Lab costs, the paper presets incl. sized + an MTF variant.
    LAB_ENGINE_PATH=<engine> TPL_REPO=<backend> python bitident.py"""
import hashlib, json, os
from common import *  # noqa
from src.lab.templates import rosyade_family as T

def manifest(f):
    with open(os.path.join("/tmp/templates/be", "ops", f)) as fh:
        return {e["name"]: e for e in json.load(fh)["presets"]}

m = {**manifest("lab_presets_seed.json"), **manifest("lab_presets_sizing_vt_seed.json")}
cases = []
for name in ("4H-ETH-Basic", "4H-ETH-v2", "4H-BTC-Opt", "4H-SOL-Opt", "4H-ETH-Basic_VT60", "4H-SOL-Opt_VT60"):
    e = m[name]
    p = T.defaults() if e.get("live_reference") else dict(e["params"])
    cases.append((name, e["symbol"], "4h", p))
base = T.defaults()
cases.append(("4H-ETH-Basic+MTF-pullback", "ETHUSDT", "4h", {**base, "entry_mode": "ltf_pullback", "entry_tf": "1h"}))
cases.append(("4H-BTC-Basic+risk1%", "BTCUSDT", "4h", {**base, "sizing_mode": "risk", "risk_per_trade_pct": 1.0}))
cases.append(("1D-SOL-Basic", "SOLUSDT", "1d", base))
for name, sym, tf, p in cases:
    cfg, ecfg = ea.build_configs(p, tf, COSTS)
    ohlcv, fund = dc.ensure(sym, tf, funding=True, offline=True)
    if T.is_mtf(T.validate_params(p)):
        ltf, _ = dc.ensure(sym, cfg.entry_tf, funding=False, offline=True)
        ohlcv = ea.attach_entry_bars(ohlcv, ltf, tf, cfg.entry_tf)
    df, *_ = ea.prepare_frame(ohlcv, fund, tf, START, END, ecfg.warmup_period, True)
    res, _ = ea.run(df, cfg, ecfg)
    th, eh = hashlib.sha256(), hashlib.sha256()
    for t in res.trades:
        th.update(repr((str(t.entry_timestamp), t.entry_price, t.quantity, str(t.exit_timestamp), t.exit_price,
                        t.exit_reason, t.net_pnl, t.fees, t.funding)).encode())
    for ts, v in res.equity_curve:
        eh.update(repr((str(ts), v)).encode())
    mm = ea.metrics(res)
    print(f"{name:28s} trades={len(res.trades):4d} net={mm['net_return_pct']!r} dd={mm['max_dd_pct']!r} "
          f"trades_sha={th.hexdigest()[:16]} equity_sha={eh.hexdigest()[:16]}", flush=True)
