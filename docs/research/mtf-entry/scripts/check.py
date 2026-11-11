"""Timing + bar_close equivalence of the new engine vs the production engine copy."""
import sys, time
from common import *
p = T.defaults()
for sym in COINS:
    df, dev, warm, hs, es, ee = frames(sym, p)
    cfg, ecfg = ea.build_configs(p, TF, COSTS)
    t0 = time.time(); res, _ = ea.run(df, cfg, ecfg); dt = time.time() - t0
    m = ea.metrics(res)
    print(os.environ["LAB_ENGINE_PATH"], sym, "hs", hs, "eval", es, ee, "bars", len(df), f"{dt:.1f}s",
          {k: round(m[k], 4) if isinstance(m[k], float) else m[k] for k in ("net_return_pct", "profit_factor", "max_dd_pct", "trades")},
          "sumpnl", round(sum(t.net_pnl for t in res.trades), 8))
