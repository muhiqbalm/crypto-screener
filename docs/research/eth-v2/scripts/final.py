"""Final dev-only step before pre-registration (python final.py -> $EXP/out/final.json).

v2a = grid.py plateau pick: Basic + entry_vol_mult 2.0 + short_sl_pct 7.0 (4h EMA-194;
      the 1d EMA-32 cells were identical, so the simpler Basic trend filter is kept).
v2b = v2a + the template's existing volatility gate (use_atr_filter, variant E's lever).
      atr_min_pct is chosen on dev by the same rule as grid.py: highest MINIMUM robust
      score over the 1-D neighbourhood (+-1 step), all neighbours passing the gates.
Also reported: Basic + ATR gate alone. The Lab sensitivity grid (+-10/20%) is run for
Basic, v2a and v2b. No holdout data is read here.
"""
from common import *  # noqa: F401,F403
from wf import BASIC, fixed_eval, robust_rank, sensitivity

ATR = [0.6, 0.8, 1.0, 1.2, 1.4]
V2A = {"entry_vol_mult": 2.0, "short_sl_pct": 7.0}


def ev(dev, p):
    e = fixed_eval(dev, p)
    e["rank"] = robust_rank(e)
    return e


def main():
    full, dev = frame()
    rows = {}
    for tag, extra in (("basic_atr", {}), ("v2a_atr", V2A)):
        for a in ATR:
            p = T.validate_params({**BASIC, **extra, "use_atr_filter": True, "atr_min_pct": a})
            e = ev(dev, p)
            rows[(tag, a)] = e
            print(tag, a, "score", e["rank"]["score"], "pass", e["rank"]["passes"], "n", e["m"]["trades"],
                  "pf", fnum(e["m"]["profit_factor"], 2), "sh2x", fnum(e["m2x"]["sharpe"], 2), "worstq",
                  fnum(e["worst_q"], 1), "mc", fnum(e["mc"]["dd_p95"], 1), flush=True)
    pick = {}
    for tag in ("basic_atr", "v2a_atr"):
        best = None
        for i, a in enumerate(ATR):
            nb = [rows[(tag, ATR[k])] for k in (i - 1, i, i + 1) if 0 <= k < len(ATR)]
            if all(x["rank"]["passes"] for x in nb):
                s = min(x["rank"]["score"] for x in nb)
                if best is None or s > best[0]:
                    best = (s, a)
        pick[tag] = best
    print("atr picks", pick, flush=True)
    cands = {"4H-ETH-Basic": BASIC, "v2a": T.validate_params({**BASIC, **V2A})}
    if pick["v2a_atr"]:
        cands["v2b"] = T.validate_params({**BASIC, **V2A, "use_atr_filter": True, "atr_min_pct": pick["v2a_atr"][1]})
    out = {}
    for n, p in cands.items():
        e = ev(dev, p)
        e["sensitivity"] = sensitivity(dev, p)
        e["rank"] = robust_rank(e, e["sensitivity"]["unstable"])
        e["params_changed"] = {k: p[k] for k in p if p[k] != BASIC[k]}
        out[n] = {"params": p, **e}
        print(n, e["params_changed"], "score", e["rank"]["score"], "pass", e["rank"]["passes"], "n", e["m"]["trades"],
              "pf", fnum(e["m"]["profit_factor"], 2), "2x", fnum(e["m2x"]["net_return_pct"], 0), "sh2x",
              fnum(e["m2x"]["sharpe"], 2), "posq", e["pos_q"], "l8", e["pos_q_last8"], "worstq", fnum(e["worst_q"], 1),
              "mc", fnum(e["mc"]["dd_p95"], 1), "sens", e["sensitivity"]["unstable"],
              fnum(e["sensitivity"]["mean_stability"], 3), e["sensitivity"]["fragile"], flush=True)
    dump(f"{OUT}/final.json", {"atr_grid": [{"tag": k[0], "atr_min_pct": k[1], **{x: v[x] for x in (
        "m", "m2x", "pos_q", "pos_q_last8", "worst_q", "mc", "rank")}} for k, v in rows.items()],
        "atr_picks": pick, "candidates": out})


if __name__ == "__main__":
    main()
