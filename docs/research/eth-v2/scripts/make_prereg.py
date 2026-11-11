"""Write docs/research/eth-v2/prereg.json from the dev outputs (stdlib only, no holdout data).

    python3 make_prereg.py <dev_dir>     (dev_dir holds wf_*.json, grid.json, final.json)
"""
import glob
import json
import os
import sys
from pathlib import Path

dev_dir = Path(sys.argv[1])
V2 = Path(__file__).resolve().parents[1]
final = json.load(open(dev_dir / "final.json"))
wf = {json.load(open(p))["variant"]: json.load(open(p)) for p in sorted(glob.glob(str(dev_dir / "wf_*.json")))}
trials = sum(d["walk_forward"]["folds"] * d["per_fold_trials"] + d["final_trials"] for d in wf.values())
fixed_evals = sum(len(d["candidates"]) for d in wf.values()) + len(json.load(open(dev_dir / "grid.json"))["cells"]) \
    + len(final["atr_grid"]) + len(final["candidates"])


def r(x, nd=3):
    return round(x, nd) if isinstance(x, float) else x


def dev_summary(c, source):
    w = wf[source]["walk_forward"]
    return {"common_window": "2021-07-01..2025-07-06 (fixed params)", "trades": c["m"]["trades"],
            "net_pct": r(c["m"]["net_return_pct"], 1), "profit_factor": r(c["m"]["profit_factor"]),
            "sharpe": r(c["m"]["sharpe"]), "max_dd_pct": r(c["m"]["max_dd_pct"], 1),
            "net_2x_pct": r(c["m2x"]["net_return_pct"], 1), "sharpe_2x": r(c["m2x"]["sharpe"]),
            "pos_quarters": r(c["pos_q"]), "pos_quarters_last8": r(c["pos_q_last8"]), "worst_quarter_pct": r(c["worst_q"], 1),
            "last8_net_2x_pct": r(c["last8_net_2x_pct"], 1), "mc_dd_p95_pct": r(c["mc"]["dd_p95"], 1),
            "fragile_params": c["sensitivity"]["unstable"], "mean_stability": r(c["sensitivity"]["mean_stability"]),
            "robust_score": c["rank"]["score"], "wf_source_variant": source,
            "wf_oos_net_pct": r(w["oos_compounded_net_pct"], 1), "wf_oos_net_2x_pct": r(w["oos_compounded_net_2x_pct"], 1),
            "wf_consistency": r(w["consistency"]), "wf_worst_fold_pct": r(w["worst_fold_net_pct"], 1),
            "trials_all_variants": trials}


C = final["candidates"]
cands = {
    "4H-ETH-v2": {"label": "v2", "params": C["v2a"]["params"], "params_changed": C["v2a"]["params_changed"],
                  "why_id": "Basic + filter volume lebih ketat (entry_vol_mult 1.6->2.0) + SL short lebih lebar (3%->7%): "
                            "pusat plateau yang stabil di grid dev, arah yang sama dengan pemenang walk-forward terbaru.",
                  "dev_summary": dev_summary(C["v2a"], "A_all_same")},
}
if "v2b" in C and C["v2b"]["m"] != C["v2a"]["m"]:  # identical behaviour -> not a separate candidate
    cands["4H-ETH-v2ATR"] = {
        "label": "v2ATR", "params": C["v2b"]["params"], "params_changed": C["v2b"]["params_changed"],
        "why_id": f"4H-ETH-v2 + filter volatilitas bawaan template (ATR% minimum {C['v2b']['params']['atr_min_pct']}): "
                  "tidak entry saat pasar terlalu sepi/sideways.",
        "dev_summary": dev_summary(C["v2b"], "E_lite_1d_atr")}
pre = {
    "title": "4H-ETH-v2: robust ETH 4H params, same Rosyade-family logic - pre-registration",
    "registered_at": "2026-11-11", "author": "andra (research agent)",
    "status": "PRE-REGISTERED before the (contaminated) holdout evaluation of these candidates",
    "template_id": "rosyade_family", "symbol": "ETHUSDT", "timeframe": "4h", "start": "2020-01-01",
    "end": "2026-11-09", "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True},
    "engine": "bmtm-lab-engine a259ceb (HTF EMA fix 4b144ce included)",
    "holdout": {"start": "2025-07-06T04:00:00Z", "end": "2026-11-09", "contaminated": True,
                "why": "the ETH 4h holdout has been viewed several times before (4H-ETH-Basic, MTF variants, "
                       "earlier Lab runs); any result on it is weak evidence"},
    "selection_rule": (
        "dev only (< 2025-07-06). 5 search variants (Lab tunables on 4h / on 1d HTF, 6-param lite on 4h / 1d, "
        "lite + ATR% gate), each with a 16-fold rolling walk-forward re-optimisation (12m train / 3m test, 30 "
        "TPE trials per fold) and a 120-trial final optimisation; fixed param sets scored by robust_rank (wf.py): "
        "gates trades>=110, no liquidation, net at 2x costs > 0, fragile params <= 3; score = mean share of "
        "positive quarters (all 16, last 8) x Sharpe at 2x costs x trade factor, halved if MC DD95 < -50%. "
        "Plateau rule (grid.py, final.py): the cell with the best MINIMUM score over its neighbourhood. "
        "The 1d HTF EMA was tested and gave identical results to 4h EMA-194, so it is not used."),
    "success_criteria": (
        "Holdout (contaminated, weak evidence): candidate is 'not worse' if holdout PF >= Basic PF, net at 2x "
        "costs >= Basic, and >= 30 trades. Lab honesty verdict reported as-is. The real test is forward paper "
        "next to 4H-ETH-Basic (same sizing), reviewed after >= 30 paper trades per preset."),
    "search_effort": {"optimizer_trials": trials, "fixed_param_evaluations": fixed_evals,
                      "variants": {k: {kk: r(vv, 2) for kk, vv in d["walk_forward"].items()} for k, d in wf.items()}},
    "not_registered": {
        "v2b_atr_gate": "final.py: Basic/v2 + ATR% gate does not form a plateau on dev (score dips at 0.8, collapses at "
                        "1.4); the neighbourhood rule picks atr_min_pct 0.6, which filters nothing (= v2), so no 2nd "
                        "candidate. One look at the contaminated holdout instead of two.",
        "stricter_volume": "entry_vol_mult >= 2.4 scores higher on dev (MC DD95 better than -50%) but gives < 110 trades "
                           "on the 4-year window (~24/yr): fails the pre-declared trade gate, not registered.",
        "htf_1d": "1d EMA-32 cells identical to 4h EMA-194 on ETH 4h (grid.py): no gain, not used."},
    "reference": {"4H-ETH-Basic": {"dev_summary": dev_summary(C["4H-ETH-Basic"], "A_all_same"),
                                   "note": "dev is in-sample for Basic (defaults were hand-tuned on this history)"}},
    "candidates": cands,
}
(V2 / "prereg.json").write_text(json.dumps(pre, indent=1) + "\n")
print(V2 / "prereg.json", list(cands), "trials", trials, "fixed evals", fixed_evals)
