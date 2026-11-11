"""Dev-stage summary of every variant (no holdout data): python summarize.py [out_dir]"""
import glob
import json
import os
import sys

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ethv2/exp/out"


def f(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x))


for p in sorted(glob.glob(os.path.join(out, "wf_*.json"))):
    d = json.load(open(p))
    w = d["walk_forward"]
    print(f"\n=== {d['variant']}  warmup {d['warmup']}  {d['seconds']:.0f}s")
    print(f"WF16 OOS net {f(w['oos_compounded_net_pct'])}%  2x {f(w['oos_compounded_net_2x_pct'])}%  cons "
          f"{f(w['consistency'], 2)}  last8 cons {f(w['consistency_last8'], 2)} last8 net {f(w['oos_last8_net_pct'])}% "
          f"medPF {f(w['oos_median_pf'], 2)}  trades {w['oos_trades']}  worst {f(w['worst_fold_net_pct'])}%")
    print("drift cv:", {k: f(v["cv"], 2) for k, v in d["param_drift"].items()})
    for cn, c in sorted(d["candidates"].items(), key=lambda kv: -kv[1]["rank"]["score"]):
        m, m2 = c["m"], c["m2x"]
        s = c.get("sensitivity") or {}
        print(f"  {cn:10s} score {c['rank']['score']:.3f} pass {c['rank']['passes']!s:5s} n {m['trades']:3d} "
              f"PF {f(m['profit_factor'], 2)} sh {f(m['sharpe'], 2)} DD {f(m['max_dd_pct'])} 2x {f(m2['net_return_pct'], 0)}"
              f" sh2x {f(m2['sharpe'], 2)} posq {c['pos_q']:.2f} l8 {c['pos_q_last8']:.2f} l8net {f(c['last8_net_pct'], 0)}"
              f" l8net2x {f(c['last8_net_2x_pct'], 0)} worstq {f(c['worst_q'])} MC95 {f(c['mc']['dd_p95'])}"
              f" sens {s.get('unstable', '-')}/{f(s.get('mean_stability'), 2)} {c['params_changed']}")
