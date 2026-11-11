"""Build ops/lab_presets_seed.json from the research files (runs locally, stdlib only).

    python3 docs/research/eth-v2/scripts/make_manifest.py

Sources: docs/research/mtf-entry/{presets,holdout-results}-2026-11-11.json, dev/opt_*.json,
and (when present) docs/research/eth-v2/{prereg,holdout-results}.json for the v2 candidates.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MTF = ROOT / "docs/research/mtf-entry"
V2 = ROOT / "docs/research/eth-v2"
OUT = ROOT / "ops/lab_presets_seed.json"
HKEYS = ("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades", "win_rate_pct", "stress_net_return_pct",
         "start", "end")


def r(x, nd=4):
    return round(x, nd) if isinstance(x, float) else x


def holdout_block(h: dict, mc: dict, contaminated: bool, extra: dict) -> dict:
    out = {k: r(h.get(k)) for k in HKEYS}
    out["cost_drag_pct"] = r((h.get("costs") or {}).get("cost_drag_pct"))
    out["mc_dd_p95_pct"] = r(mc.get("dd_p95"))
    out["contaminated"] = contaminated
    out.update(extra)
    return out


def main():
    presets = json.loads((MTF / "presets-2026-11-11.json").read_text())["presets"]
    hold = json.loads((MTF / "holdout-results-2026-11-11.json").read_text())["results"]
    entries = [{
        "name": "4H-ETH-Basic", "label": "Basic", "template_id": "rosyade_family", "symbol": "ETHUSDT",
        "timeframe": "4h", "live_reference": True, "paper": {"balance": 10000.0, "sizing": "mirror"},
    }]
    for name, sym in (("4H-BTC-Opt", "BTCUSDT"), ("4H-SOL-Opt", "SOLUSDT")):
        h = hold[name]
        opt = json.loads((MTF / f"dev/opt_{sym}.json").read_text())
        wf = opt["walk_forward"]
        trials = wf["trials_done"] + 60  # walk-forward trials + final 60-trial TPE (scripts/opt.py)
        ho = h["holdout"]
        entries.append({
            "name": name, "label": "Opt", "template_id": "rosyade_family", "symbol": sym, "timeframe": "4h",
            "params": presets[name]["params"],
            "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True},
            "source_mode": "research", "source_run_id": None, "verdict": h["verdict"],
            "holdout": holdout_block(ho, h["monte_carlo"], False, {
                "failed_checks": h["failed_checks"],
                "dev_walk_forward_oos_net_pct": r(wf["oos_compounded_net_pct"], 2),
                "dev_walk_forward_consistency": r(wf["consistency"], 3),
            }),
            "snooping": {"runs": h["snooping"]["validated_runs_all_tf"], "timeframes": 1, "trials": trials,
                         "holdout_touches": h["snooping"]["holdout_touches_all_tf"], "holdout_viewed": True,
                         "counted_in": "research /tmp lab.db 2026-11-11 (bukan lab.db produksi)"},
            "notes": (
                f"Riset 2026-11-11 (docs/research/mtf-entry, presets-2026-11-11.json). Param dipilih di periode "
                f"development saja (walk-forward 6 fold x 20 trial + optimasi TPE 60 trial, objektif robust_score), "
                f"tanpa run Lab sumber (source_run_id kosong). Holdout {ho['start'][:10]}..{ho['end'][:10]} SUDAH "
                f"dilihat satu kali (validate di salinan lab.db): net {ho['net_return_pct']:.1f}%, PF "
                f"{ho['profit_factor']:.2f}, DD {ho['max_dd_pct']:.1f}%, {ho['trades']} trade, 2x biaya "
                f"{ho['stress_net_return_pct']:.1f}%. Verdict FAIL ({', '.join(h['failed_checks'])}); trade terlalu "
                f"sedikit untuk dipercaya. Walk-forward dev OOS {wf['oos_compounded_net_pct']:.1f}% "
                f"(konsistensi {wf['consistency']:.2f}). Uji sebenarnya: paper forward."),
            "paper": {"balance": 10000.0, "sizing": "mirror"},
        })
    pre_p, res_p = V2 / "prereg.json", V2 / "holdout-results.json"
    if pre_p.exists():
        pre = json.loads(pre_p.read_text())
        res = json.loads(res_p.read_text())["results"] if res_p.exists() else {}
        for name, c in pre["candidates"].items():
            h = res.get(name)
            e = {"name": name, "label": c["label"], "template_id": "rosyade_family", "symbol": "ETHUSDT",
                 "timeframe": "4h", "params": c["params"],
                 "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True},
                 "source_mode": "research", "source_run_id": None, "verdict": h and h["verdict"],
                 "paper": {"balance": 10000.0, "sizing": "mirror"}}
            dev = c["dev_summary"]
            if h:
                ho = h["holdout"]
                e["holdout"] = holdout_block(ho, h["monte_carlo"], True, {
                    "failed_checks": h["failed_checks"],
                    "dev_walk_forward_oos_net_pct": dev.get("wf_oos_net_pct"),
                    "dev_walk_forward_consistency": dev.get("wf_consistency")})
                e["snooping"] = {"runs": h["snooping"]["validated_runs_all_tf"], "timeframes": 1,
                                 "trials": dev.get("trials_all_variants"),
                                 # this look + the ETH 4h looks of the 2026-11-11 MTF research (lower bound:
                                 # earlier Lab/TradingView looks at this period are not counted)
                                 "holdout_touches": h["snooping"]["holdout_touches_all_tf"]
                                 + hold["4H-ETH-Basic"]["snooping"]["holdout_touches_all_tf"],
                                 "holdout_touches_is_lower_bound": True,
                                 "holdout_viewed": True, "holdout_contaminated": True,
                                 "counted_in": "research /tmp lab.db 2026-11-11 (bukan lab.db produksi)"}
                hold_txt = (f"Holdout {ho['start'][:10]}..{ho['end'][:10]} TERKONTAMINASI (holdout ETH 4h sudah "
                            f"dilihat berkali-kali sebelumnya): net {ho['net_return_pct']:.1f}%, PF "
                            f"{ho['profit_factor']:.2f}, DD {ho['max_dd_pct']:.1f}%, {ho['trades']} trade, 2x biaya "
                            f"{ho['stress_net_return_pct']:.1f}%, verdict {h['verdict']}. Bukti lemah.")
            else:
                hold_txt = "Holdout belum dievaluasi."
            e["notes"] = (f"Riset 4H-ETH-v2 2026-11-11 (docs/research/eth-v2). {c['why_id']} Dipilih di periode "
                          f"development saja dengan walk-forward re-optimasi (16 fold) dan skor robust, "
                          f"pra-registrasi di prereg.json sebelum holdout. Tanpa run Lab sumber. {hold_txt} "
                          f"Uji sebenarnya: paper forward di samping 4H-ETH-Basic.")
            entries.append(e)
    OUT.write_text(json.dumps({"version": 1, "generated_by": "docs/research/eth-v2/scripts/make_manifest.py",
                               "presets": entries}, indent=1) + "\n")
    print(OUT, [e["name"] for e in entries])


if __name__ == "__main__":
    main()
