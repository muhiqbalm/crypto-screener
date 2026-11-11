"""Dev-only sizing grid: every preset x every sizing rule, 1x and 2x costs, all before HS.
Output: $EXP/out/dev_grid.json. No holdout bar is read (frame() asserts it)."""
import multiprocessing as mp

from common import *  # noqa: F401,F403

RULES = (
    [{"family": "fixed", "level": k} for k in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    + [{"family": "risk", "level": r} for r in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)]
    + [{"family": "vt", "level": v} for v in (10, 15, 20, 30, 40, 50, 60, 80)]
    + [{"family": "vt", "level": v, "lookback": lb} for v in (20, 30, 40) for lb in (30, 120)]
    + [{"family": "fixed", "level": k, "dd": 20, "dd_mult": 0.5} for k in (1.0, 1.5, 2.0)]
    + [{"family": "risk", "level": r, "dd": 20, "dd_mult": 0.5} for r in (2.0, 3.0, 4.0)]
    + [{"family": "vt", "level": v, "dd": 20, "dd_mult": 0.5} for v in (30, 40, 50)]
)


def job(args):
    name, rule = args
    sym, p = presets()[name]
    _, dev = frame(sym)
    r1 = run(dev, p, rule)
    r2 = run(dev, p, rule, cost_mult=2.0)
    return name, rule, stats(r1, r2, rule)


def main():
    tasks = [(n, r) for n in presets() for r in RULES]
    out = []
    with mp.Pool(3) as pool:
        for name, rule, s in pool.imap_unordered(job, tasks):
            out.append({"preset": name, "rule": rule, "rule_name": rule_name(rule), **s})
            print(name, rule_name(rule), "cagr", s["cagr_pct"], "dd", s["max_dd_pct"], "mc95", s["mc_dd95"],
                  "sh", s["sharpe"], "sh2x", s["sharpe2x"], "liq", s["liquidations"], flush=True)
    out.sort(key=lambda x: (x["preset"], x["rule_name"]))
    dump(f"{OUT}/dev_grid.json", {"dev_end": HS, "start": START, "costs": COSTS, "rows": out})


if __name__ == "__main__":
    main()
