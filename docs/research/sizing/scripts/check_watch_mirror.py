"""Check that watch_eval's notional_mult (engine notional / closed equity at entry) equals the
vol-target rule min(target / realised vol, cap) on real data, at every entry of a dev run."""
from common import *  # noqa: F401,F403

ea._engine()  # puts the engine on sys.path
from backtest_engine.engine.backtest_loop import realised_vol_pct  # noqa: E402

sym, p = presets()["4H-ETH-v2"]
_, dev = frame(sym)
rule = {"family": "vt", "level": 60}
cfg, ecfg = configs(p, rule)
sl, pre = ea.window(dev, dev["timestamp"].iloc[BIG_WARMUP], None, BIG_WARMUP)
res, ind = ea.run(sl, cfg, ecfg, warmup=pre)
rv = realised_vol_pct(ind["close"], cfg.vol_lookback, cfg.base_timeframe)
bad, prev_eq = 0, cfg.initial_capital
for t in res.trades:
    mult = t.quantity * t.entry_price / prev_eq          # == watch_eval: position_value / equity after last trade
    want = min(cfg.vol_target_pct / rv[t.entry_bar_index], cfg.max_notional_mult)
    bad += abs(mult - want) > 1e-9
    prev_eq = t.equity_at_exit
print("trades", len(res.trades), "mismatches", bad)
