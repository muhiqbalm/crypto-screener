"""Compact per-signal track record for the /screener page (stdlib only).

One row per screener signal type + direction, pooling the live screener source and
the causal reconstruction (``screener`` + ``screener_rekon``): both run the same
generator, and the live source alone is days old. The split is reported (n_live /
n_rekon) so the UI can say the record is partly reconstructed.

Headline horizon is 1 day (``HEADLINE``):
  * the stats cluster by UTC day; 1-day windows barely overlap across days, so the
    clustered interval is close to honest. 3-day windows overlap three neighbouring
    days and the same interval understates the uncertainty;
  * more signals have matured (a 3d outcome waits 3 days);
  * it matches how the screener is used (refreshed hourly, read daily).
3 days is returned as a secondary line because that is where the early effects show,
flagged as weaker evidence in the UI.

Verdicts reuse ``stats.horizon_stats`` (clustered 95 % CI of the mean, >= 10 signals
on >= 5 days), mapped to Indonesian codes for the screener.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from ..db import utcnow
from .stats import MIN_DAYS, MIN_N_ANY, horizon_stats

SOURCES = ("screener", "screener_rekon")
HEADLINE = "1d"
SECONDARY = "3d"
HORIZONS_OUT = (HEADLINE, SECONDARY)
# screener signal types (see screener.TYPE_RULES); tier_a is long-only, tier_c short-only
TYPES = ("komposit", "komposit_high", "tier_a", "tier_c", "momentum", "funding", "oi")
VERDICT_CODE = {
    "positive": "terbukti",
    "negative": "negatif",
    "inconclusive": "belum_terbukti",
    "insufficient": "belum_cukup_data",
}
CACHE_TTL_S = 600.0
ERROR_TTL_S = 60.0

_KEEP = ("n", "days", "coins", "hit_rate", "hit_ci", "mean_pct", "mean_ci", "median_pct", "mean_rel_btc_pct",
         "rel_btc_ci", "hit_rel_btc", "sample")


def _compact(s: dict) -> dict:
    out = {k: s.get(k) for k in _KEEP}
    out["verdict"] = VERDICT_CODE[s["verdict"]]
    out["verdict_rel_btc"] = VERDICT_CODE[s["verdict_rel_btc"]]
    return out


def compute(conn) -> dict:
    """Track record from the ledger tables. ``conn`` may be read-only; missing tables -> no items."""
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('ledger_signals','ledger_outcomes')").fetchone()[0]
    base = {"headline_horizon": HEADLINE, "secondary_horizon": SECONDARY, "sources": list(SOURCES),
            "thresholds": {"min_n": MIN_N_ANY, "min_days": MIN_DAYS}, "generated_at": utcnow()}
    if have < 2:
        return {**base, "items": [], "period": None}
    ph = ",".join("?" * len(SOURCES))
    groups: dict[tuple[str, int], dict] = {}
    for r in conn.execute(
            f"SELECT signal_type, direction, source, status, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts "
            f"FROM ledger_signals WHERE source IN ({ph}) GROUP BY signal_type, direction, source, status", SOURCES):
        g = groups.setdefault((r["signal_type"], r["direction"]), {
            "n_signals": 0, "n_live": 0, "n_rekon": 0, "n_pending": 0, "first_ts": None, "last_ts": None,
            "rows": {h: [] for h in HORIZONS_OUT}})
        g["n_signals"] += r["n"]
        g["n_live" if r["source"] == "screener" else "n_rekon"] += r["n"]
        if r["status"] == "pending":
            g["n_pending"] += r["n"]
        g["first_ts"] = min(filter(None, (g["first_ts"], r["first_ts"])), default=None)
        g["last_ts"] = max(filter(None, (g["last_ts"], r["last_ts"])), default=None)
    hp = ",".join("?" * len(HORIZONS_OUT))
    for r in conn.execute(
            "SELECT s.signal_type, s.direction, s.symbol, s.ts, o.horizon, o.dir_ret_pct, o.rel_btc_pct, o.hit "
            "FROM ledger_outcomes o JOIN ledger_signals s ON s.id = o.signal_id "
            f"WHERE s.source IN ({ph}) AND o.horizon IN ({hp})", (*SOURCES, *HORIZONS_OUT)):
        g = groups.get((r["signal_type"], r["direction"]))
        if g is not None:
            g["rows"][r["horizon"]].append({"dir_ret_pct": r["dir_ret_pct"], "rel_btc_pct": r["rel_btc_pct"],
                                            "hit": r["hit"], "ts": r["ts"], "symbol": r["symbol"]})
    items = []
    order = {t: i for i, t in enumerate(TYPES)}
    for (stype, d), g in sorted(groups.items(), key=lambda kv: (order.get(kv[0][0], 99), kv[0][0], -kv[0][1])):
        stats = {h: _compact(horizon_stats(g["rows"][h])) for h in HORIZONS_OUT}
        head = stats[HEADLINE]
        items.append({
            "signal_type": stype, "direction": d,
            "n_signals": g["n_signals"], "n_live": g["n_live"], "n_rekon": g["n_rekon"], "n_pending": g["n_pending"],
            "first_ts": g["first_ts"], "last_ts": g["last_ts"],
            "verdict": head["verdict"], "verdict_rel_btc": head["verdict_rel_btc"],
            "stats": stats,
        })
    firsts = [i["first_ts"] for i in items if i["first_ts"]]
    lasts = [i["last_ts"] for i in items if i["last_ts"]]
    period = {"from": min(firsts), "to": max(lasts)} if firsts else None
    return {**base, "items": items, "period": period}


class TTLCache:
    """Single-value cache: one computation at a time, errors cached briefly."""

    def __init__(self, ttl_s: float = CACHE_TTL_S, error_ttl_s: float = ERROR_TTL_S,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.error_ttl_s, self.clock = ttl_s, error_ttl_s, clock
        self._lock = threading.Lock()
        self._value: Optional[Any] = None
        self._expires = 0.0

    def get(self, fn: Callable[[], Any], on_error: Callable[[Exception], Any]) -> Any:
        with self._lock:
            now = self.clock()
            if self._value is not None and now < self._expires:
                return self._value
            try:
                value, ttl = fn(), self.ttl_s
            except Exception as e:  # noqa: BLE001
                value, ttl = on_error(e), self.error_ttl_s
            self._value, self._expires = value, now + ttl
            return value

    def clear(self) -> None:
        with self._lock:
            self._value, self._expires = None, 0.0
