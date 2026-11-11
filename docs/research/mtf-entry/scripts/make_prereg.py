import json, sys
sys.path.insert(0, "/tmp/mtf/crypto-screener")
from src.lab.templates import rosyade_family as T
EXP = "/tmp/mtf/exp"
sel = json.load(open(f"{EXP}/out/selection.json"))
D = T.defaults()
def diff(p): return {k: v for k, v in T.validate_params(p).items() if v != D[k]}
COIN = {"ETHUSDT": "ETH", "BTCUSDT": "BTC", "SOLUSDT": "SOL"}
TFN = {"1h": "1H", "30m": "30M", "15m": "15M"}
cfg, coins = {}, {}
for sym, s in sel.items():
    c = COIN[sym]
    opt = json.load(open(f"{EXP}/out/opt_{sym}.json")) if sym != "ETHUSDT" else None
    bname = "4H-ETH-Basic" if sym == "ETHUSDT" else f"4H-{c}-Opt"
    cfg[bname] = {"symbol": sym, "role": "baseline", "params": diff(s["base_params"]), "dev": s["baseline_dev"]}
    if opt:
        cfg[f"4H-{c}-Basic"] = {"symbol": sym, "role": "reference (ETH 4H-ETH-Basic params on this coin)",
                                "params": {}, "dev": opt["dev_eth_defaults"]}
    coins[sym] = {"holdout_start": json.load(open(f"{EXP}/out/mtf_{sym}.json"))["holdout_start"],
                  "baseline": bname, "mtf_configs_explored_on_dev": s["n_configs"],
                  "baseline_origin": "live preset defaults" if not opt else
                      {"method": "Lab optimize recipe on dev only: rolling WF re-opt (6 folds, 20 trials) + final 60-trial TPE, "
                                 "objective = Lab robust score, min_trades 30", "best_score": opt["best_score"],
                       "walk_forward": {k: opt["walk_forward"][k] for k in ("scheme", "oos_compounded_net_pct", "oos_avg_pf",
                                                                             "oos_trades", "consistency")}}}
    for fam, pk in s["picks"].items():
        etf = pk["mtf"]["entry_tf"]
        name = f"4H{TFN[etf]}-{c}-{fam}"
        cfg[name] = {"symbol": sym, "role": f"variant {fam}", "dev_label": pk["label"],
                     "params": diff({**s["base_params"], **pk["mtf"]}), "mtf_params": pk["mtf"], "dev": pk["dev"],
                     "family_configs": pk["family_size"], "family_eligible": pk["eligible"],
                     "family_beat_baseline_dev_sharpe": pk["beat_baseline_sharpe"]}
pre = {
 "title": "MTF entry timing (4H Rosyade signal, lower-TF entry) - pre-registration",
 "registered_at": "2026-11-11", "author": "andra (research agent)",
 "status": "PRE-REGISTERED before any holdout evaluation of these configs",
 "template_id": "rosyade_family", "timeframe": "4h", "start": "2020-01-01", "end": "2026-11-09",
 "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True},
 "maker_fee_pct_for_limit_entries": 0.02,
 "holdout_rule": "Lab rule: last 20% of the evaluated range, locked per (template, symbol, 4h); one validate run per config",
 "selection_rule": ("dev period only; per coin and family (Pullback = ltf_pullback, Limit = ltf_limit): eligible if dev trades >= 30, "
                    "dev net at 2x costs > 0, no liquidation; pick max Lab robust score (tie: Sharpe, then grid order). "
                    "At most 2 entry variants per coin: Pullback and Limit. Baseline + (BTC/SOL) ETH-params reference also get one look each."),
 "grid_per_coin": "3 ltf_close + 36 pullback/ATR + 12 pullback/EMA20 + 60 limit (entry TF 1h/15m(/30m), ATR mult, wait 4/8/16h, timeout skip/market)",
 "success_criteria": "variant beats its coin baseline on the holdout on Sharpe AND net, PF not lower, at 1x and 2x costs; Lab honesty verdict reported as-is",
 "coins": coins, "configs": cfg}
json.dump(pre, open(f"{EXP}/out/prereg.json", "w"), indent=1)
for n, x in cfg.items(): print(n, x.get("dev_label", ""), json.dumps(x.get("mtf_params", {})))
