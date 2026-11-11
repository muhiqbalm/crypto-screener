"""Build ../prereg.json from the dev outputs (dev_grid.json). Run locally before any holdout look:
    python3 make_prereg.py ../dev/dev_grid.json > ../prereg.json"""
import json
import sys

g = json.load(open(sys.argv[1]))
R1 = {"family": "fixed", "level": 1.0}
R2 = {"family": "vt", "level": 60}
BASE = {"family": "fixed", "level": 2.0}


def pick(preset, rule):
    for r in g["rows"]:
        if r["preset"] == preset and r["rule"] == rule:
            return {k: r[k] for k in ("trades", "cagr_pct", "max_dd_pct", "mc_dd95", "p_dd50", "sharpe", "sharpe2x",
                                      "calmar", "mc_calmar", "cagr2x_pct", "avg_notional_x", "liquidations")}
    raise KeyError((preset, rule))


presets = sorted({r["preset"] for r in g["rows"]})
out = {
    "title": "Position sizing for the 4H Rosyade-family paper presets",
    "registered_at": "2026-11-11",
    "status": "registered BEFORE the holdout look; dev statistics only (all data before each symbol's holdout start)",
    "engine": "Automate_Execution feat/sizing-research (a259ceb + sizing_mode); default sizing bit-identical to a259ceb",
    "holdout_starts": g["dev_end"],
    "costs": g["costs"],
    "holdout_contamination": "The ETH/BTC/SOL 4h holdouts were viewed several times by earlier research "
                             "(eth-v2 README, MTF README). Any holdout result here is WEAK evidence.",
    "search_effort": {"rules_tried_on_dev": len({json.dumps(r['rule'], sort_keys=True) for r in g['rows']}),
                      "families": ["fixed notional", "fixed-fractional risk on hard SL", "vol target (lb 30/60/120)",
                                   "drawdown de-risk 20%/x0.5 on top"]},
    "selection_rule": (
        "Per family, the largest level whose WORST dev Monte Carlo DD95 over the four presets is >= -40% "
        "(10 pp buffer to the Lab's -50% limit: the Lab's MC runs on the full range incl. the holdout, which "
        "was worse for ETH). Families are compared at that level by dev Sharpe (1x and 2x costs) and "
        "CAGR / |MC DD95|. Rule-aware MC for the drawdown rule. Lookback for vol target fixed at 60 a priori "
        "(lb 120 looked better on ETH dev but is not selected on that basis)."),
    "dev_findings": [
        "Fixed notional: Sharpe is flat in the size (ETH-Basic 1.86-1.92) while MC DD95 scales ~linearly "
        "(2x -63%, 1.5x -52%, 1.25x -45%, 1x -38%). The drawdown is a sizing property; the signal sets the Sharpe.",
        "Fixed-fractional on the hard SL LOWERS Sharpe on ETH (1.64 vs 1.89) and SOL (1.24 vs 1.37): the long SL "
        "(13% ETH, 29% SOL) is far from the realised risk (trailing exits), so longs get under-sized.",
        "Vol target 60% (lb 60): same risk-adjusted return as fixed 1x within noise (ETH-Basic Sharpe 1.90 vs 1.89, "
        "v2 1.89 vs 1.80, SOL 1.40 vs 1.37, BTC 1.01 vs 1.05); per-year wins are split.",
        "DD de-risk (1.5x, halve below -20% closed-equity DD): best rule-aware MC DD95 per unit of CAGR, but on the "
        "real dev path it cut return (Sharpe 1.82 vs 1.91 at 1.5x) without lowering the realised max DD "
        "(-28.6 vs -28.8). Its benefit exists only under the iid reshuffle assumption; not registered.",
    ],
    "rules": {
        "R1_fixed_1x": {"rule": R1, "params_override": {"portfolio_risk": 25.0, "leverage": 4.0},
                        "paper": "risk_pct 100, leverage_max 1.0 (paper-native mirror)",
                        "dev": {p: pick(p, R1) for p in presets}},
        "R2_vol_target_60": {"rule": R2, "params_override": {"sizing_mode": "vol_target", "vol_target_pct": 60.0,
                                                             "vol_lookback": 60, "max_notional_mult": 2.0},
                             "paper": "not mirrorable by the paper engine today (sizes on SL distance / leverage cap)",
                             "dev": {p: pick(p, R2) for p in presets}},
        "reference_2x": {"rule": BASE, "dev": {p: pick(p, BASE) for p in presets}},
    },
    "holdout_procedure": (
        "ONE Lab validate run per preset x {R1, R2} (8 runs) through the normal Lab pipeline on a /tmp copy of "
        "production lab.db, holdout locks pinned to the starts above. No re-runs, no parameter changes after."),
    "decision_criteria": {
        "primary": "R1 is recommended if its full-range MC DD95 (Lab check) is > -50% for 4H-ETH-Basic and 4H-ETH-v2.",
        "R2_over_R1": "R2 replaces R1 only if, on the holdout, R2 has a higher Sharpe than R1 for BOTH ETH presets "
                      "AND passes the MC DD95 check for both; otherwise R1 (simpler, paper-native).",
        "expected_not_fixable_by_sizing": [
            "4H-ETH-Basic holdout PF 1.03 < 1.2 (PF is ~size-invariant) -> verdict stays FAIL",
            "4H-BTC-Opt and 4H-SOL-Opt holdout trades < 30 -> verdict stays FAIL"],
    },
}
json.dump(out, sys.stdout, indent=1)
print()
