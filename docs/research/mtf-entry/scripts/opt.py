"""Per-coin 4H params on the DEVELOPMENT period only (Lab optimize recipe without the holdout step)."""
import sys, time
from common import *
from src.lab import runner
sym = sys.argv[1]
base = T.defaults()
df, dev, warm, hs, es, ee = frames(sym, base)
specs = T.tunable_params()
t0 = time.time()
wf = runner.walk_forward_reopt(ea, dev, warm, base, TF, COSTS, 20, hs, specs)
best = ea.optimize(dev, warm, base, TF, COSTS, 60, hs, specs=specs, min_trades=30)
out = {"symbol": sym, "holdout_start": hs, "eval_start": es, "eval_end": ee, "walk_forward": wf,
       "best_params_changed": {k: v for k, v in best["best_params"].items() if v != base[k]},
       "best_score": best["best_score"], "best_metrics": best["best_metrics"], "top_trials": best["top_trials"],
       "dev_eth_defaults": dev_eval(sym, base), "dev_opt": dev_eval(sym, best["best_params"]),
       "seconds": time.time() - t0}
dump(f"{EXP}/out/opt_{sym}.json", out)
print(json.dumps({k: out[k] for k in ("symbol", "holdout_start", "best_params_changed", "best_score")}))
print("WF", wf["oos_compounded_net_pct"], wf["oos_avg_pf"], wf["consistency"])
print("dev ETH-defaults", out["dev_eth_defaults"]); print("dev opt", out["dev_opt"])
