"""Pre-declared dev-only selection: per coin and family, eligible = dev trades >= 30, dev 2x-cost net > 0,
no liquidation; pick max Lab robust score (tie: Sharpe). Prints the family-wide picture too."""
import json
EXP = "/tmp/mtf/exp"
FAM = {"Pullback": "pb-", "Limit": "lim-", "Close": "close-"}
out = {}
for sym in ("ETHUSDT", "BTCUSDT", "SOLUSDT"):
    d = json.load(open(f"{EXP}/out/mtf_{sym}.json"))
    rows = d["rows"]
    base = rows[0]["dev"]
    print(f"\n== {sym} baseline dev: net {base['net_return_pct']:.1f} pf {base['profit_factor']:.2f} dd {base['max_dd_pct']:.1f} "
          f"sh {base['sharpe']:.3f} n {base['trades']} 2x {base['stress2x_net_pct']:.1f} score {base['score']:.3f}")
    out[sym] = {"base_params": d["base_params"], "baseline_dev": base, "picks": {}, "n_configs": len(rows) - 1}
    for fam, pre in FAM.items():
        fr = [r for r in rows if r["label"].startswith(pre)]
        better_sh = sum(1 for r in fr if r["dev"]["sharpe"] > base["sharpe"])
        better_net = sum(1 for r in fr if r["dev"]["net_return_pct"] > base["net_return_pct"])
        el = [r for r in fr if r["dev"]["trades"] >= 30 and r["dev"]["stress2x_net_pct"] > 0 and not r["dev"]["liquidations"]]
        el.sort(key=lambda r: (r["dev"]["score"], r["dev"]["sharpe"]), reverse=True)
        print(f"  {fam}: {len(fr)} configs, {len(el)} eligible, beat baseline Sharpe {better_sh}, beat net {better_net}")
        for r in el[:3]:
            x = r["dev"]; e = x["entry"] or {}
            print(f"    {r['label']:32s} net {x['net_return_pct']:.1f} pf {x['profit_factor']:.2f} dd {x['max_dd_pct']:.1f} sh {x['sharpe']:.3f} "
                  f"n {x['trades']} 2x {x['stress2x_net_pct']:.1f} score {x['score']:.3f} fill {e.get('fill_rate') and round(e['fill_rate'],3)} "
                  f"impr {e.get('avg_improvement_bps') and round(e['avg_improvement_bps'],1)}bps")
        if el and fam != "Close":
            out[sym]["picks"][fam] = {"label": el[0]["label"], "mtf": el[0]["mtf"], "dev": el[0]["dev"],
                                      "family_size": len(fr), "eligible": len(el), "beat_baseline_sharpe": better_sh}
json.dump(out, open(f"{EXP}/out/selection.json", "w"), indent=1)
