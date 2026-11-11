"""MTF entry grid on the DEVELOPMENT period only, per coin, on the coin's 4H baseline params."""
import sys, time
from common import *
sym = sys.argv[1]
base = T.defaults()
if sym != "ETHUSDT":
    base.update(json.load(open(f"{EXP}/out/opt_{sym}.json"))["best_params_changed"])
BPH = {"1h": 1, "30m": 2, "15m": 4}
grid = [("baseline", {})]
for etf in ("1h", "30m", "15m"):
    grid.append((f"close-{etf}", {"entry_mode": "ltf_close", "entry_tf": etf}))
for etf in ("1h", "15m"):
    for m in (0.25, 0.5, 1.0):
        for wh in (4, 8, 16):
            for to in ("skip", "market"):
                grid.append((f"pb-atr-{etf}-m{m}-w{wh}h-{to}", {"entry_mode": "ltf_pullback", "entry_tf": etf,
                             "entry_band": "atr", "entry_atr_mult": m, "entry_wait_bars": wh * BPH[etf], "entry_timeout": to}))
for m in (0.0, 0.25):
    for wh in (4, 8, 16):
        for to in ("skip", "market"):
            grid.append((f"pb-ema20-1h-m{m}-w{wh}h-{to}", {"entry_mode": "ltf_pullback", "entry_tf": "1h", "entry_band": "ema",
                         "entry_ema_len": 20, "entry_atr_mult": m, "entry_wait_bars": wh, "entry_timeout": to}))
for etf in ("1h", "15m"):
    for m in (0.0, 0.1, 0.25, 0.5, 1.0):
        for wh in (4, 8, 16):
            for to in ("skip", "market"):
                grid.append((f"lim-{etf}-m{m}-w{wh}h-{to}", {"entry_mode": "ltf_limit", "entry_tf": etf, "entry_atr_mult": m,
                             "entry_wait_bars": wh * BPH[etf], "entry_timeout": to}))
rows, t0 = [], time.time()
for label, mp in grid:
    r = dev_eval(sym, {**base, **mp})
    rows.append({"label": label, "mtf": mp, "dev": r})
    print(f"{time.time()-t0:6.0f}s {label:32s} net={r['net_return_pct']:.1f} pf={r['profit_factor']} dd={r['max_dd_pct']:.1f} "
          f"sh={r['sharpe']:.3f} n={r['trades']} 2x={r['stress2x_net_pct']:.1f} score={r['score']:.3f} "
          f"fill={(r['entry'] or {}).get('fill_rate')}", flush=True)
dump(f"{EXP}/out/mtf_{sym}.json", {"symbol": sym, "base_params": base, "rows": rows,
                                   "holdout_start": frames(sym, base)[3]})
