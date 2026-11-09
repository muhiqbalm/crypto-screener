"""Journal queries and statistics (stdlib only)."""
from __future__ import annotations

from typing import Iterable, Optional

from .db import loads


def entry_out(r) -> dict:
    d = dict(r)
    d["tags"] = loads(d.get("tags"), []) or []
    d.pop("external_id", None)
    return d


def query(conn, account_id: Optional[int] = None, source: Optional[str] = None, symbol: Optional[str] = None,
          date_from: Optional[str] = None, date_to: Optional[str] = None, watch_id: Optional[int] = None,
          limit: int = 1000) -> list[dict]:
    sql, args = ["SELECT * FROM journal_entries WHERE 1=1"], []
    for col, val in (("account_id", account_id), ("source", source), ("symbol", symbol), ("watch_id", watch_id)):
        if val is not None:
            sql.append(f"AND {col}=?")
            args.append(val)
    if date_from:
        sql.append("AND COALESCE(exit_time, entry_time) >= ?")
        args.append(date_from)
    if date_to:
        sql.append("AND COALESCE(exit_time, entry_time) < ?")
        args.append(date_to if "T" in date_to else date_to + "T23:59:59.999999Z")
    sql.append("ORDER BY COALESCE(exit_time, entry_time) ASC, id ASC LIMIT ?")
    args.append(limit)
    return [entry_out(r) for r in conn.execute(" ".join(sql), args)]


def _group(entries: list[dict]) -> dict:
    pnls = [e["pnl"] for e in entries if e.get("pnl") is not None]
    rs = [e["r_multiple"] for e in entries if e.get("r_multiple") is not None]
    wins = [p for p in pnls if p > 0]
    return {
        "trades": len(entries),
        "winrate": (len(wins) / len(pnls)) if pnls else None,
        "pnl": sum(pnls) if pnls else 0.0,
        "avg_r": (sum(rs) / len(rs)) if rs else None,
    }


def stats(entries: list[dict], starting_balance: Optional[float] = None) -> dict:
    """winrate is a fraction 0..1; R stats only over entries that have an R."""
    pnls = [e["pnl"] for e in entries if e.get("pnl") is not None]
    rs = [e["r_multiple"] for e in entries if e.get("r_multiple") is not None]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    base = starting_balance if starting_balance else 0.0
    curve, eq, peak, max_dd = [], base, base, 0.0
    for e in sorted(entries, key=lambda x: (x.get("exit_time") or x.get("entry_time") or "")):
        if e.get("pnl") is None:
            continue
        eq += e["pnl"]
        curve.append({"t": e.get("exit_time") or e.get("entry_time"), "equity": eq})
        if base > 0:
            peak = max(peak, eq)
            if peak > 0:
                max_dd = min(max_dd, (eq - peak) / peak * 100.0)
    g = _group(entries)

    def by(key: str) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for e in entries:
            groups.setdefault(str(e.get(key)), []).append(e)
        return sorted(({"key": k, **_group(v)} for k, v in groups.items()), key=lambda x: -x["trades"])

    return {
        "trades": len(entries),
        "winrate": g["winrate"],
        "avg_r": g["avg_r"],
        "expectancy_r": (sum(rs) / len(rs)) if rs else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "net_pnl": sum(pnls) if pnls else 0.0,
        "max_dd_pct": max_dd if base > 0 else None,
        "equity_curve": curve,
        "by_symbol": by("symbol"),
        "by_source": by("source"),
    }


def summarize_trades(pnls: Iterable[float]) -> dict:
    p = list(pnls)
    wins = [x for x in p if x > 0]
    gl = -sum(x for x in p if x < 0)
    return {"trades": len(p), "winrate": len(wins) / len(p) if p else None,
            "profit_factor": (sum(wins) / gl) if gl > 0 else None, "total": sum(p) if p else 0.0}
