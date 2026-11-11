"""Build the sized paper-variant manifests from the research files (runs locally, stdlib only):

    python3 docs/research/sizing/scripts/make_manifest.py

  ops/lab_presets_sizing_1x_seed.json   R1 fixed 1x notional (portfolio_risk 25 at 4x). Only keys the
                                        CURRENT production template knows -> seedable with no deploy.
  ops/lab_presets_sizing_vt_seed.json   R2 vol target 60% (sizing_mode keys) -> needs the sizing engine
                                        + backend (template, watch_eval mirror) deployed first.

Variant params = the production preset's params (ops/lab_presets_seed.json; 4H-ETH-Basic =
template defaults) + the rule's override. Signals are identical to the parent preset.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
R = ROOT / "docs/research/sizing"
BASE_MANIFEST = ROOT / "ops/lab_presets_seed.json"
OUTS = {"R1_fixed_1x": ("1x", ROOT / "ops/lab_presets_sizing_1x_seed.json",
                         "notional 1x ekuitas (margin 25% x leverage 4) bukan 2x", "leverage_max 1.0"),
        "R2_vol_target_60": ("VT60", ROOT / "ops/lab_presets_sizing_vt_seed.json",
                             "notional = ekuitas x 60% / volatilitas tahunan 60 bar terakhir (maks. 2x) bukan 2x tetap",
                             "leverage_max 2.0, qty mengikuti kelipatan notional engine")}
VARIANTS = ["4H-ETH-Basic", "4H-ETH-v2", "4H-SOL-Opt"]   # 4H-BTC-Opt: MC DD95 already passes at 2x
HKEYS = ("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades", "win_rate_pct", "stress_net_return_pct",
         "start", "end")


def r(x, nd=4):
    return round(x, nd) if isinstance(x, float) else x


def basic_defaults():
    """Template defaults of the production template (rosyade_family.py, without the sizing group)."""
    import sys
    sys.path.insert(0, str(ROOT))
    from src.lab.templates import rosyade_family as T  # stdlib-only module
    return {k: v for k, v in T.defaults().items() if k not in T.SIZING_KEYS}


def build(RULE):
    SUFFIX, OUT, desc, acct = OUTS[RULE]
    pre = json.loads((R / "prereg.json").read_text())
    hold = json.loads((R / "holdout-results.json").read_text())["results"]
    base = {e["name"]: e for e in json.loads(BASE_MANIFEST.read_text())["presets"]}
    over = pre["rules"][RULE]["params_override"]
    entries = []
    for name in VARIANTS:
        e = base[name]
        params = basic_defaults() if e.get("live_reference") else dict(e["params"])
        if RULE == "R1_fixed_1x":
            assert not set(over) - set(params), "R1 must only touch keys the production template knows"
        params.update(over)
        h = hold[f"{name} | {RULE}"]
        ho = h["holdout"]
        label = f"{e['label']}_{SUFFIX}"
        dev = pre["rules"][RULE]["dev"][name]
        hb = {k: r(ho.get(k)) for k in HKEYS}
        hb.update(cost_drag_pct=r((ho.get("costs") or {}).get("cost_drag_pct")),
                  mc_dd_p95_pct=r((h.get("monte_carlo") or {}).get("dd_p95")), contaminated=True,
                  failed_checks=h["failed_checks"], sizing_rule=RULE, dev_mc_dd_p95_pct=dev["mc_dd95"],
                  dev_sharpe=dev["sharpe"])
        mc, n = hb["mc_dd_p95_pct"], hb["trades"]
        entries.append({
            "name": f"4H-{e['symbol'][:-4]}-{label}", "label": label, "template_id": "rosyade_family",
            "symbol": e["symbol"], "timeframe": "4h", "params": params,
            "costs": {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True},
            "source_mode": "research", "source_run_id": None, "verdict": h["verdict"],
            "paper": {"balance": 10000.0, "sizing": "mirror"},
            "holdout": hb,
            "snooping": {"runs": h["snooping"]["validated_runs_all_tf"], "timeframes": 1, "trials": 0,
                         "holdout_touches": h["snooping"]["holdout_touches_all_tf"],
                         "holdout_touches_is_lower_bound": True, "holdout_viewed": True,
                         "holdout_contaminated": True,
                         "counted_in": "research /tmp lab.db 2026-11-11 (bukan lab.db produksi)"},
            "notes": (
                f"Varian ukuran posisi dari {name} (riset sizing 2026-11-11, docs/research/sizing). Sinyal & param "
                f"SAMA PERSIS dengan {name}; hanya ukuran posisi: {desc}. "
                f"Dipilih di periode development saja (37 aturan sizing diuji; drawdown ternyata sifat ukuran "
                f"posisi, Sharpe tidak berubah), pra-registrasi di prereg.json sebelum holdout. Holdout "
                f"TERKONTAMINASI (sudah dilihat berkali-kali): net {hb['net_return_pct']:.1f}%, PF "
                f"{hb['profit_factor']:.2f}, DD {hb['max_dd_pct']:.1f}%, {n} trade, MC DD95 {mc:.1f}%, verdict "
                f"{h['verdict']}. Bukti lemah; uji sebenarnya paper forward di samping {name} (akun paper "
                f"{acct})."),
        })
    OUT.write_text(json.dumps({"version": 1, "generated_by": "docs/research/sizing/scripts/make_manifest.py",
                               "presets": entries}, indent=1, ensure_ascii=False) + "\n")
    print("wrote", OUT, [e["name"] for e in entries])


if __name__ == "__main__":
    for rule in OUTS:
        build(rule)
