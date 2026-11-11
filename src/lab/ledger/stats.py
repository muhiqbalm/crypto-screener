"""Summary statistics for the ledger (stdlib only).

Signals are not independent: many coins react to the same market move on the same
day, and 3d/7d windows of consecutive signals overlap. So the 95 % intervals are
CLUSTER-ROBUST by UTC day (signals of one day count as one cluster, t with
days-1 degrees of freedom). The hit-rate interval is the wider of that and Wilson.
The verdict uses the clustered interval of the mean and needs >= MIN_N_ANY signals
on >= MIN_DAYS different days. Overlap across neighbouring days remains, so even
"positive" is a hint, not proof.
"""
from __future__ import annotations

import math
from statistics import mean, median
from typing import Iterable, Optional

Z95 = 1.959963984540054
# two-sided 95 % Student-t critical values by degrees of freedom (df >= 30 -> normal-ish)
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
        29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}

MIN_N_ANY = 10      # below: "terlalu sedikit" — no interval shown as meaningful
MIN_N_OK = 30       # below: "sampel kecil"
MIN_DAYS = 5        # verdict needs signals on at least this many days


def t95(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df in _T95:
        return _T95[df]
    for k in (40, 60, 120):
        if df < k:
            return _T95[k]
    return Z95


def wilson(k: int, n: int, z: float = Z95) -> tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def clustered_ci(xs: list[float], clusters: list[str]) -> tuple[Optional[float], Optional[float]]:
    """95 % CI of the mean with a cluster-robust (CR1) standard error."""
    n = len(xs)
    groups: dict[str, float] = {}
    if n < 2:
        return None, None
    m = mean(xs)
    for x, g in zip(xs, clusters):
        groups[g] = groups.get(g, 0.0) + (x - m)
    G = len(groups)
    if G < 2:
        return None, None
    se = math.sqrt(G / (G - 1) * sum(v * v for v in groups.values())) / n
    h = t95(G - 1) * se
    return m - h, m + h


def sample_flag(n: int) -> str:
    return "none" if n == 0 else "too_few" if n < MIN_N_ANY else "small" if n < MIN_N_OK else "ok"


def _avg(xs: list[float]) -> Optional[float]:
    return mean(xs) if xs else None


def horizon_stats(rows: Iterable[dict]) -> dict:
    """rows: outcome dicts (dir_ret_pct, rel_btc_pct, mfe_pct, mae_pct, hit, ts, symbol). NULL returns skipped."""
    rows = [r for r in rows if r.get("dir_ret_pct") is not None]
    n = len(rows)
    rets = [r["dir_ret_pct"] for r in rows]
    hits = [1.0 if r.get("hit") else 0.0 for r in rows]
    day = [str(r.get("ts") or "")[:10] for r in rows]
    rel = [r["rel_btc_pct"] for r in rows if r.get("rel_btc_pct") is not None]
    rel_day = [str(r.get("ts") or "")[:10] for r in rows if r.get("rel_btc_pct") is not None]
    days = len(set(day))
    coins = len({r.get("symbol") for r in rows if r.get("symbol")})
    w_lo, w_hi = wilson(int(sum(hits)), n)
    c_lo, c_hi = clustered_ci(hits, day)
    hit_ci = None
    if n:
        hit_ci = [max(0.0, min(w_lo, c_lo if c_lo is not None else w_lo)),
                  min(1.0, max(w_hi, c_hi if c_hi is not None else w_hi))]
    mlo, mhi = clustered_ci(rets, day)
    rlo, rhi = clustered_ci(rel, rel_day)
    def judge(lo, hi) -> str:
        if n < MIN_N_ANY or days < MIN_DAYS or lo is None:
            return "insufficient"
        return "positive" if lo > 0 else "negative" if hi < 0 else "inconclusive"
    return {
        "n": n,
        "hit_rate": sum(hits) / n if n else None,
        "hit_ci": hit_ci,
        "mean_pct": _avg(rets),
        "mean_ci": [mlo, mhi] if mlo is not None else None,
        "median_pct": median(rets) if rets else None,
        "mean_rel_btc_pct": _avg(rel),
        "rel_btc_ci": [rlo, rhi] if rlo is not None else None,
        "hit_rel_btc": (sum(1 for x in rel if x > 0) / len(rel)) if rel else None,
        "mean_mfe_pct": _avg([r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]),
        "mean_mae_pct": _avg([r["mae_pct"] for r in rows if r.get("mae_pct") is not None]),
        "days": days,
        "coins": coins,
        "sample": sample_flag(n),
        # positive / negative = clustered 95 % CI of the mean excludes 0 (before costs)
        "verdict": judge(mlo, mhi),
        "verdict_rel_btc": judge(rlo, rhi),
    }
