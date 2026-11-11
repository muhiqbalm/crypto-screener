"""Reproduce the 2026-11-11 dev statistics of 4H-ETH-Basic (dev only) and time the engine."""
import time

from common import *  # noqa: F401,F403

p = T.defaults()
cfg, ecfg = ea.build_configs(p, TF, COSTS)
ohlcv, fund = dc.ensure(SYM, TF, funding=True, offline=True)
df, es, ee, _ = ea.prepare_frame(ohlcv, fund, TF, START, END, ecfg.warmup_period, True)
hs = honesty.proposed_holdout_start(es, ee, ea.TF_SECONDS[TF])
dev = df[df["timestamp"] < pd.Timestamp(hs)].reset_index(drop=True)
t0 = time.time()
res, _ = ea.run(dev, cfg, ecfg, warmup=ecfg.warmup_period)
print("lab-style dev", "hs", hs, "eval_start", es, f"{time.time() - t0:.2f}s", mstat(res),
      "expected net 165256.66 trades 218")

full, devb = frame()
f = folds()
print("folds", len(f), f[0][1], f[-1][2], "big-frame first ts", devb["timestamp"].iloc[0],
      "rows", len(devb))
t0 = time.time()
r, *_ = run_window(devb, p, f[0][0], f[0][2])
print("15m window", f"{time.time() - t0:.2f}s", mstat(r))
p1d = dict(p, ema_htf_tf="1d", ema_htf_len=32)
print("1d warmup", warm(p1d), "same warmup", warm(p))
t0 = time.time()
r, *_ = run_window(devb, p1d, f[0][1], HS)
print("1d EMA32 dev from first test", f"{time.time() - t0:.2f}s", mstat(r))
r, *_ = run_window(devb, p, f[0][1], HS)
print("basic dev from first test", mstat(r), [round(x, 1) for x in quarter_returns(r, f[0][1], HS)])
