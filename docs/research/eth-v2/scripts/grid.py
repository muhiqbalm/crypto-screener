"""Plateau check around the two changes the walk-forward kept pointing at (dev only).

Motivation (from wf_*.json, dev only): in variants A and B the robust non-Basic trials
independently share a stricter volume filter (entry_vol_mult ~2.2) and a wider short
stop; fold winners of the last train windows (2023-10..2025-04) move the same way, and
entry_vol_mult is one of the few parameters whose fold winners agree (CV ~0.25).

Grid: entry_vol_mult x short_sl_pct x HTF trend filter {4h EMA-194 (Basic), 1d EMA-32},
everything else = 4H-ETH-Basic. Each cell is scored with wf.robust_rank on the common
window 2021-07-01 .. HS (fixed params, 1x and 2x costs, Monte Carlo).

Selection rule (declared before running): per HTF choice, the cell with the highest
MINIMUM robust score over its 3x3 neighbourhood (edges: available neighbours), among
cells whose whole neighbourhood passes the gates. Ties -> fewer changes from Basic.
    python grid.py   -> $EXP/out/grid.json
"""
import itertools

from common import *  # noqa: F401,F403
from wf import BASIC, fixed_eval, robust_rank

VOL = [1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8]
SSL = [3.0, 5.0, 7.0, 9.0, 12.0, 15.0]
HTF = {"4h_ema194": {}, "1d_ema32": {"ema_htf_tf": "1d", "ema_htf_len": 32}}


def main():
    full, dev = frame()
    cells = {}
    for h, (i, v), (j, s) in itertools.product(HTF, enumerate(VOL), enumerate(SSL)):
        p = T.validate_params({**BASIC, **HTF[h], "entry_vol_mult": v, "short_sl_pct": s})
        e = fixed_eval(dev, p)
        e["rank"] = robust_rank(e)
        cells[(h, i, j)] = {"htf": h, "entry_vol_mult": v, "short_sl_pct": s, "params": p, **e}
        print(h, v, s, "score", e["rank"]["score"], "pass", e["rank"]["passes"], "n", e["m"]["trades"],
              "pf", fnum(e["m"]["profit_factor"], 2), "sh2x", fnum(e["m2x"]["sharpe"], 2), "l8net2x",
              fnum(e["last8_net_2x_pct"], 0), "mc", fnum(e["mc"]["dd_p95"], 1), flush=True)
    best = {}
    for h in HTF:
        ranked = []
        for i, j in itertools.product(range(len(VOL)), range(len(SSL))):
            nb = [cells[(h, a, b)] for a in (i - 1, i, i + 1) for b in (j - 1, j, j + 1) if (h, a, b) in cells]
            if all(c["rank"]["passes"] for c in nb):
                n_changes = (VOL[i] != BASIC["entry_vol_mult"]) + (SSL[j] != BASIC["short_sl_pct"])
                ranked.append((min(c["rank"]["score"] for c in nb), -n_changes, i, j))
        ranked.sort(reverse=True)
        best[h] = [{"neigh_min_score": r[0], "entry_vol_mult": VOL[r[2]], "short_sl_pct": SSL[r[3]],
                    "cell_score": cells[(h, r[2], r[3])]["rank"]["score"]} for r in ranked[:5]]
        print(h, "plateau top5", best[h], flush=True)
    dump(f"{OUT}/grid.json", {"vol": VOL, "short_sl": SSL, "htf": HTF, "plateau_best": best,
                              "cells": [{k: v for k, v in c.items() if k != "params"} for c in cells.values()]})


if __name__ == "__main__":
    main()
