"""Dev-only per-calendar-year return / max DD / Sharpe for the leading candidates (stability of the
family comparison). Output: $EXP/out/dev_years.json."""
from common import *  # noqa: F401,F403
from src.lab.engine_adapter import _engine

CANDS = [{"family": "fixed", "level": 2.0}, {"family": "fixed", "level": 1.0}, {"family": "vt", "level": 60},
         {"family": "vt", "level": 60, "lookback": 120}, {"family": "risk", "level": 4.0},
         {"family": "fixed", "level": 1.5, "dd": 20, "dd_mult": 0.5}]


def years(res):
    eq = pd.Series([e[1] for e in res.equity_curve], index=pd.to_datetime([e[0] for e in res.equity_curve], utc=True))
    out = {}
    for y, seg in eq.groupby(eq.index.year):
        prev = eq[eq.index < seg.index[0]]
        e0 = float(prev.iloc[-1]) if len(prev) else 100.0
        s = pd.concat([pd.Series([e0]), seg.reset_index(drop=True)])
        dd = float(((s - s.cummax()) / s.cummax()).min() * 100)
        r = s.pct_change().dropna()
        sh = float(r.mean() / r.std() * np.sqrt(6 * 365)) if r.std() > 0 else 0.0
        out[int(y)] = {"ret": round((float(seg.iloc[-1]) / e0 - 1) * 100, 1), "dd": round(dd, 1), "sh": round(sh, 2)}
    return out


def main():
    out = {}
    for name, (sym, p) in presets().items():
        _, dev = frame(sym)
        for rule in CANDS:
            y = years(run(dev, p, rule))
            out.setdefault(name, {})[rule_name(rule)] = y
            print(name, f"{rule_name(rule):22}", " ".join(f"{k}:{v['ret']:>6}/{v['dd']:>6}/{v['sh']:>5}" for k, v in y.items()),
                  flush=True)
    dump(f"{OUT}/dev_years.json", out)


if __name__ == "__main__":
    main()
