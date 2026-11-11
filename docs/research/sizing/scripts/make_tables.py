"""Print the README result tables (markdown) from dev/dev_grid.json and holdout-results.json:
    python3 make_tables.py > ../tables.md"""
import json
from pathlib import Path

R = Path(__file__).resolve().parents[1]
g = json.loads((R / "dev/dev_grid.json").read_text())["rows"]
h = json.loads((R / "holdout-results.json").read_text())["results"]
PRESETS = ["4H-ETH-Basic", "4H-ETH-v2", "4H-BTC-Opt", "4H-SOL-Opt"]
SHOW = ([("fixed", x, None) for x in (0.5, 1.0, 1.5, 2.0)] + [("risk", x, None) for x in (1.0, 2.0, 4.0, 6.0)]
        + [("vt", x, None) for x in (30, 60, 80)] + [("fixed", 1.5, 20), ("fixed", 2.0, 20)])
# 2x reference holdout (engine a259ceb, same pipeline): eth-v2/holdout-results.json, mtf-entry holdout-results
REF = {"4H-ETH-Basic": (18.8, 1.03, -73.8, 0.52, -9.6, 72, -68.1, 0.587, "FAIL (PF, MC DD, 2x cost)"),
       "4H-ETH-v2": (153.7, 1.32, -52.9, 1.36, 109.1, 50, -62.7, 0.382, "FAIL (MC DD)"),
       "4H-BTC-Opt": (15.4, 1.49, -12.7, 0.69, 8.1, 17, -34.5, 0.0, "FAIL (trades < 30)"),
       "4H-SOL-Opt": (58.5, 1.77, -25.7, 1.24, 53.0, 10, -66.7, 0.444, "FAIL (MC DD, trades < 30)")}
NAMES = {"oos_profit_factor": "PF", "oos_net_return": "net", "mc_dd_p95": "MC DD", "min_oos_trades": "trades < 30",
         "cost_stress": "2x cost", "sensitivity": "sensitivity", "no_liquidation": "liquidation"}


def f(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}"


def row(p, fam, lvl, dd):
    for r in g:
        ru = r["rule"]
        if r["preset"] == p and ru["family"] == fam and ru["level"] == lvl and ru.get("dd") == dd \
                and ru.get("lookback", 60) == 60:
            return r


print("### Development period (before the holdout), per preset x sizing rule\n")
print("Costs 0.05% + 0.05% per side, funding on. CAGR and Sharpe from the mark-to-market equity curve. "
      "MC DD95 = 5th percentile of 1,000 trade-order reshuffles (rule-aware for the DD rule). "
      "P(DD≥50%) = share of reshuffles that ever fall 50% (risk of ruin proxy). "
      "CAGR/|MC DD95| = return per unit of tail drawdown. **Bold** = the two pre-registered rules.\n")
for p in PRESETS:
    print(f"#### {p}\n")
    print("| Sizing rule | Avg notional | CAGR % | Max DD % | MC DD95 % | P(DD≥50%) | Sharpe | Sharpe 2× cost "
          "| Calmar | CAGR/\\|MC DD95\\| |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for fam, lvl, dd in SHOW:
        r = row(p, fam, lvl, dd)
        name = r["rule_name"]
        if (fam, lvl, dd) in (("fixed", 1.0, None), ("vt", 60, None)):
            name = f"**{name}**"
        if (fam, lvl, dd) == ("fixed", 2.0, None):
            name += " (current)"
        print(f"| {name} | {r['avg_notional_x']:.2f}× | {f(r['cagr_pct'])} | {f(r['max_dd_pct'])} | {f(r['mc_dd95'])} "
              f"| {r['p_dd50'] * 100:.1f}% | {r['sharpe']:.2f} | {r['sharpe2x']:.2f} | {r['calmar']:.2f} "
              f"| {r['mc_calmar']:.2f} |")
    print()

print("### Holdout (contaminated, one Lab `validate` run per preset x rule)\n")
print("Holdout 2025-07-06 → 2026-11-09 (SOL from 2025-08-26). MC DD95 and P(DD≥50%) are the Lab's full-range "
      "numbers (dev + holdout), i.e. what the verdict checks.\n")
print("| Preset | Sizing | Net % | PF | Max DD % | Sharpe | Net 2× cost % | Trades | MC DD95 % | P(DD≥50%) | Lab verdict |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for p in PRESETS:
    a = REF[p]
    print(f"| {p} | 2× (current) | {a[0]:.1f} | {a[1]:.2f} | {a[2]:.1f} | {a[3]:.2f} | {a[4]:.1f} | {a[5]} | {a[6]:.1f} "
          f"| {a[7] * 100:.1f}% | {a[8]} |")
    for key, lab in (("R1_fixed_1x", "**R1** fixed 1×"), ("R2_vol_target_60", "**R2** VT 60%")):
        x = h[f"{p} | {key}"]
        o, mc = x["holdout"], x["monte_carlo"]
        fails = ", ".join(NAMES.get(c, c) for c in x["failed_checks"])
        v = x["verdict"] + (f" ({fails})" if fails else "")
        print(f"| {p} | {lab} | {o['net_return_pct']:.1f} | {o['profit_factor']:.2f} | {o['max_dd_pct']:.1f} "
              f"| {o['sharpe']:.2f} | {o['stress_net_return_pct']:.1f} | {o['trades']} | {mc['dd_p95']:.1f} "
              f"| {mc['prob_dd_beyond_50pct'] * 100:.1f}% | {v} |")
