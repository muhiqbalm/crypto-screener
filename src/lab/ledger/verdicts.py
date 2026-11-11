"""Verdict per signal group, optionally for a time window (stdlib only).

Used by the weekly report (this week vs overall) and by the ledger-verdict
notification. One group = (source, signal_type, direction); the live screener and
its causal reconstruction are pooled as ``screener`` (same generator, like
``track_record``). Headline horizon 1 day, verdict from ``stats.horizon_stats``
(clustered 95 % CI of the mean, >= 10 signals on >= 5 days), mapped to the
Indonesian codes of the screener track record.
"""
from __future__ import annotations

from typing import Optional

from .stats import horizon_stats
from .track_record import VERDICT_CODE

HEADLINE = "1d"
POOL = {"screener_rekon": "screener"}


def _have_tables(conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('ledger_signals','ledger_outcomes')").fetchone()[0] == 2


def group_key(source: str, signal_type: str, direction: int) -> str:
    return f"{source}|{signal_type}|{'long' if direction > 0 else 'short'}"


def verdicts(conn, since: Optional[str] = None, until: Optional[str] = None, horizon: str = HEADLINE) -> list[dict]:
    """[{key, source, signal_type, direction, n_signals, n, days, hit_rate, mean_pct, mean_ci, verdict}]

    ``since`` / ``until`` filter the signal time (ISO, half-open). Signals whose 1d
    outcome has not matured yet count in ``n_signals`` but not in ``n``."""
    if not _have_tables(conn):
        return []
    where, args = ["1=1"], []
    if since:
        where.append("s.ts >= ?")
        args.append(since)
    if until:
        where.append("s.ts < ?")
        args.append(until)
    groups: dict[tuple, dict] = {}
    for r in conn.execute(
            "SELECT s.id, s.source, s.signal_type, s.direction, s.symbol, s.ts, o.dir_ret_pct, o.rel_btc_pct, o.hit "
            "FROM ledger_signals s LEFT JOIN ledger_outcomes o ON o.signal_id = s.id AND o.horizon = ? "
            f"WHERE {' AND '.join(where)}", [horizon, *args]):
        src = POOL.get(r["source"], r["source"])
        g = groups.setdefault((src, r["signal_type"], r["direction"]), {"ids": set(), "rows": []})
        g["ids"].add(r["id"])
        if r["dir_ret_pct"] is not None:
            g["rows"].append({"dir_ret_pct": r["dir_ret_pct"], "rel_btc_pct": r["rel_btc_pct"], "hit": r["hit"],
                              "ts": r["ts"], "symbol": r["symbol"]})
    out = []
    for (src, stype, d), g in sorted(groups.items()):
        st = horizon_stats(g["rows"])
        out.append({
            "key": group_key(src, stype, d), "source": src, "signal_type": stype, "direction": d,
            "n_signals": len(g["ids"]), "n": st["n"], "days": st["days"], "hit_rate": st["hit_rate"],
            "mean_pct": st["mean_pct"], "mean_ci": st["mean_ci"], "verdict": VERDICT_CODE[st["verdict"]],
        })
    return out
