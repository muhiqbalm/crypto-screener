"""Small-sample statistics for the drift check. Pure stdlib maths, no I/O.

All ranges are two-sided 95 % "acceptance" ranges under the backtest's number:
an observation outside the range would happen less than ~5 % of the time if
paper really behaved like the backtest. Discrete ranges are exact (Poisson /
binomial sums), so they stay honest at n = 3 where a normal approximation lies.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

ALPHA = 0.05
Z95 = 1.959963984540054

# two-sided 97.5 % Student t quantiles, df 1..30
_T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145,
         2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048,
         2.045, 2.042]


def _range_from_pmf(pmf, k_max: int, alpha: float = ALPHA) -> tuple[int, int]:
    """Central acceptance range [lo, hi]: P(X < lo) <= alpha/2 and P(X > hi) <= alpha/2."""
    cdf, lo, hi = 0.0, None, k_max
    for k in range(k_max + 1):
        cdf += pmf(k)
        if lo is None and cdf > alpha / 2:
            lo = k
        if cdf >= 1 - alpha / 2:
            hi = k
            break
    return (lo or 0), hi


def poisson_range(mu: float, alpha: float = ALPHA) -> tuple[int, int]:
    """Expected count range for a Poisson process with mean mu."""
    if mu <= 0:
        return 0, 0
    k_max = int(mu + 10 * math.sqrt(mu) + 20)

    def pmf(k: int) -> float:
        return math.exp(k * math.log(mu) - mu - math.lgamma(k + 1))
    return _range_from_pmf(pmf, k_max, alpha)


def binom_range(n: int, p: float, alpha: float = ALPHA) -> tuple[int, int]:
    """Range of successes out of n expected at success probability p."""
    if n <= 0:
        return 0, 0
    p = min(max(p, 0.0), 1.0)
    if p in (0.0, 1.0):
        k = int(round(n * p))
        return k, k

    def pmf(k: int) -> float:
        return math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                        + k * math.log(p) + (n - k) * math.log(1 - p))
    return _range_from_pmf(pmf, n, alpha)


def wilson(k: int, n: int, z: float = Z95) -> Optional[tuple[float, float]]:
    """Wilson score interval for a proportion (fractions 0..1)."""
    if n <= 0:
        return None
    ph = k / n
    den = 1 + z * z / n
    centre = (ph + z * z / (2 * n)) / den
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def t975(df: int) -> float:
    if df < 1:
        return float("inf")
    if df <= len(_T975):
        return _T975[df - 1]
    z = Z95                                   # Cornish-Fisher expansion, good to 1e-3 for df > 30
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df * df)


def mean_ci(xs: Sequence[float]) -> Optional[dict]:
    """Mean with a 95 % t interval (needs n >= 2)."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    half = t975(n - 1) * sd / math.sqrt(n)
    return {"mean": m, "sd": sd, "lo": m - half, "hi": m + half, "n": n}


def max_drawdown_pct(values: Sequence[float]) -> Optional[float]:
    """Deepest peak-to-trough fall in % (<= 0)."""
    peak, worst = None, 0.0
    for v in values:
        if v is None:
            continue
        peak = v if peak is None or v > peak else peak
        if peak and peak > 0:
            worst = min(worst, (v - peak) / peak * 100.0)
    return worst if peak is not None else None


def sharpe_daily(daily_equity: Sequence[float], min_days: int = 30) -> Optional[float]:
    """Annualised Sharpe (rf = 0, sqrt(365)) of daily equity returns; None below min_days returns."""
    rets = [(b - a) / a for a, b in zip(daily_equity, daily_equity[1:]) if a and a > 0]
    if len(rets) < min_days:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    if sd == 0:
        return None
    return m / sd * math.sqrt(365)
