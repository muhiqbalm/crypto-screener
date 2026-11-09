"""Honesty report: hard-coded, versioned thresholds and the locked holdout.

Rules (version HONESTY_VERSION):
  * The holdout is the last HOLDOUT_FRACTION of the evaluated range. Its start
    is LOCKED per (template, symbol, timeframe) on first use and never moves,
    so changing the end date cannot be used to peek. The optimizer only ever
    receives bars strictly before holdout_start (plus nothing after).
  * Every evaluation of the holdout increments holdout_touches.
  * Verdict = AND of all checks. Missing inputs count as FAIL.

Pure stdlib: imported by the API, the worker and the engine child.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db import utcnow

HONESTY_VERSION = "2026-11.1"
HOLDOUT_FRACTION = 0.20

THRESHOLDS: dict[str, float] = {
    "oos_pf_min": 1.2,            # holdout profit factor >= 1.2
    "oos_net_min_pct": 0.0,       # holdout net return after all costs > 0
    "mc_dd_p95_min_pct": -50.0,   # Monte Carlo 95th-pct drawdown depth must be shallower than -50%
    "min_oos_trades": 30,         # at least 30 trades in the holdout
    "cost_stress_mult": 2.0,      # holdout re-run at 2x commission+slippage must stay > 0
    "max_unstable_params": 3,     # sensitivity: <= 3 fragile parameters (stability <= 0.5)
    "max_liquidations": 0,        # no liquidation over the full range
}


class HoldoutError(ValueError):
    pass


def _parse(ts: str | datetime) -> datetime:
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s) if "T" in s or " " in s or "+" in s else \
            datetime.fromisoformat(s + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return _parse(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def proposed_holdout_start(eval_start, eval_end, bar_seconds: int) -> str:
    """Start of the last 20% of [eval_start, eval_end], floored to a bar open."""
    s, e = _parse(eval_start), _parse(eval_end)
    if e <= s:
        raise HoldoutError("empty evaluation range")
    raw = s + (e - s) * (1.0 - HOLDOUT_FRACTION)
    epoch = int(raw.timestamp())
    floored = epoch - epoch % bar_seconds
    return iso(datetime.fromtimestamp(floored, tz=timezone.utc))


def get_lock(conn: sqlite3.Connection, template_id: str, symbol: str, tf: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM holdout_locks WHERE template_id=? AND symbol=? AND timeframe=?",
        (template_id, symbol, tf),
    ).fetchone()
    return dict(row) if row else None


def resolve_holdout(conn: sqlite3.Connection, template_id: str, symbol: str, tf: str,
                    eval_start, eval_end, bar_seconds: int) -> str:
    """Return the locked holdout start, creating the lock on first use.

    Raises HoldoutError when the requested range cannot respect the lock
    (range ends before the holdout, or starts inside it).
    """
    lock = get_lock(conn, template_id, symbol, tf)
    if lock is None:
        hs = proposed_holdout_start(eval_start, eval_end, bar_seconds)
        conn.execute(
            "INSERT OR IGNORE INTO holdout_locks (template_id, symbol, timeframe, holdout_start, "
            "touches, created_at) VALUES (?, ?, ?, ?, 0, ?)",
            (template_id, symbol, tf, hs, utcnow()),
        )
        conn.commit()
        lock = get_lock(conn, template_id, symbol, tf)
    hs = lock["holdout_start"]
    if _parse(eval_end) <= _parse(hs):
        raise HoldoutError(
            f"range must extend past the locked holdout start {hs} for {symbol} {tf}")
    if _parse(eval_start) >= _parse(hs):
        raise HoldoutError(
            f"range starts inside the locked holdout ({hs}); the optimizer may not see it")
    # need at least one bar-month of development data
    if _parse(hs) - _parse(eval_start) < timedelta(days=60):
        raise HoldoutError("development segment before the holdout is shorter than 60 days")
    return hs


def touch_holdout(conn: sqlite3.Connection, template_id: str, symbol: str, tf: str) -> int:
    conn.execute(
        "UPDATE holdout_locks SET touches=touches+1, last_touch_at=? "
        "WHERE template_id=? AND symbol=? AND timeframe=?",
        (utcnow(), template_id, symbol, tf),
    )
    conn.commit()
    row = get_lock(conn, template_id, symbol, tf)
    return int(row["touches"]) if row else 0


def assert_dev_only(timestamps, holdout_start) -> None:
    """Guard used before handing data to the optimizer."""
    hs = _parse(holdout_start)
    last = max((_parse(t) for t in timestamps), default=None)
    if last is not None and last >= hs:
        raise HoldoutError(f"optimizer data leaks into the holdout ({iso(last)} >= {iso(hs)})")


@dataclass
class HonestyInputs:
    oos_profit_factor: Optional[float]
    oos_net_return_pct: Optional[float]
    oos_trades: Optional[int]
    mc_dd_p95_pct: Optional[float]
    stress_net_return_pct: Optional[float]
    unstable_params: Optional[int]
    liquidations: Optional[int]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def build_checks(x: HonestyInputs) -> list[dict]:
    th = THRESHOLDS
    pf = x.oos_profit_factor
    pf_val = None if pf is None else (pf if pf != float("inf") else 999.0)

    def c(name, label, value, threshold, ok):
        return {"name": name, "label": label, "value": value, "threshold": threshold,
                "passed": bool(ok) if value is not None else False}

    net, trades = _num(x.oos_net_return_pct), x.oos_trades
    mc, stress = _num(x.mc_dd_p95_pct), _num(x.stress_net_return_pct)
    return [
        c("oos_profit_factor", "Holdout profit factor", pf_val, f">= {th['oos_pf_min']}",
          pf_val is not None and pf_val >= th["oos_pf_min"]),
        c("oos_net_return", "Holdout net return after costs (%)", net,
          f"> {th['oos_net_min_pct']}", net is not None and net > th["oos_net_min_pct"]),
        c("mc_dd_p95", "Monte Carlo 95th-pct drawdown (%)", mc, f"> {th['mc_dd_p95_min_pct']}",
          mc is not None and mc > th["mc_dd_p95_min_pct"]),
        c("min_oos_trades", "Holdout trades", trades, f">= {int(th['min_oos_trades'])}",
          trades is not None and trades >= th["min_oos_trades"]),
        c("cost_stress", f"Holdout net at {th['cost_stress_mult']:g}x costs (%)", stress, "> 0",
          stress is not None and stress > 0),
        c("sensitivity", "Fragile parameters", x.unstable_params,
          f"<= {int(th['max_unstable_params'])}",
          x.unstable_params is not None and x.unstable_params <= th["max_unstable_params"]),
        c("no_liquidation", "Liquidations", x.liquidations, f"<= {int(th['max_liquidations'])}",
          x.liquidations is not None and x.liquidations <= th["max_liquidations"]),
    ]


def verdict(checks: list[dict]) -> str:
    required = {"oos_profit_factor", "oos_net_return", "mc_dd_p95", "min_oos_trades",
                "cost_stress", "sensitivity", "no_liquidation"}
    names = {c["name"] for c in checks}
    if not required <= names:
        return "FAIL"
    return "PASS" if all(c["passed"] for c in checks) else "FAIL"
