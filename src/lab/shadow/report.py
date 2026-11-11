"""Aggregates for the "Kualitas eksekusi" API (stdlib, lab.db only)."""
from __future__ import annotations

from statistics import mean, median
from typing import Optional

from ..db import loads
from ..ledger.stats import MIN_N_ANY, MIN_N_OK, sample_flag, wilson
from ..ledger.store import kv_get
from .store import ensure_schema, shadow_settings

SIGNAL_COLS = ("id", "symbol", "action", "side", "trade_dir", "tf", "bar_close_ts", "arrival_ts", "arrival_basis",
               "off_close", "n_rows", "n_users", "statuses_json", "fill_price", "fill_ts", "bar_close_px", "atr",
               "p0", "p0_basis", "slippage_bps", "drift_bps", "impact_bps", "latency_s", "exec_latency_s",
               "status", "error", "computed_at")


def _avg(xs: list) -> Optional[float]:
    return mean(xs) if xs else None


def _med(xs: list) -> Optional[float]:
    return median(xs) if xs else None


def cell_stats(rows: list[dict]) -> dict:
    """One (k, ttl) cell over the counted signals."""
    n = len(rows)
    filled = [r for r in rows if r["outcome"] == "filled"]
    missed = [r for r in rows if r["outcome"] == "missed"]
    lo, hi = wilson(len(filled), n)
    sav = [r["saving_bps"] for r in rows if r["saving_bps"] is not None]
    return {
        "n": n, "filled": len(filled), "missed": len(missed),
        "postonly": sum(r["outcome"] == "postonly" for r in rows),
        "fill_rate": len(filled) / n if n else None, "fill_ci": [lo, hi] if n else None,
        "mean_saving_bps": _avg(sav), "median_saving_bps": _med(sav),
        "mean_saving_filled_bps": _avg([r["saving_bps"] for r in filled]),
        "mean_saving_missed_bps": _avg([r["saving_bps"] for r in missed]),
        "median_time_to_fill_s": _med([r["time_to_fill_s"] for r in filled if r["time_to_fill_s"] is not None]),
        "mean_runaway_missed_bps": _avg([r["runaway_end_bps"] for r in missed]),
        "proxy_ref": sum(r["ref_basis"] == "proxy" for r in rows),
        "klines_only": sum(r["data_basis"] == "klines_1m" for r in rows),
        "sample": sample_flag(n),
    }


def build(conn) -> dict:
    ensure_schema(conn)
    cfg = shadow_settings()
    sigs = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SIGNAL_COLS)} FROM shadow_signals ORDER BY arrival_ts DESC")]
    res: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT * FROM shadow_results"):
        res.setdefault(r["signal_id"], []).append(dict(r))
    for s in sigs:
        st = loads(s.pop("statuses_json"), {}) or {}
        s["statuses"] = st.get("statuses", [])
        s["logs_final"] = st.get("final", True)
        s["results"] = sorted(res.get(s["id"], []), key=lambda x: (x["k"], x["ttl_min"]))
        for x in s["results"]:
            x.pop("signal_id", None)
    counted = [s for s in sigs if not s["off_close"]]
    grid = {}
    for k in cfg.ks:
        for ttl in cfg.ttls_min:
            rows = [x for s in counted for x in s["results"] if x["k"] == k and x["ttl_min"] == ttl]
            grid[f"{k:g}|{ttl}"] = {"k": k, "ttl_min": ttl, **cell_stats(rows)}
    fills = [s for s in counted if s["slippage_bps"] is not None]
    actual = {
        "n_signals": len(sigs), "n_counted": len(counted), "n_off_close": len(sigs) - len(counted),
        "n_with_fill": len(fills), "n_open": sum(s["action"] == "open" for s in counted),
        "n_close": sum(s["action"] == "close" for s in counted),
        "mean_slippage_bps": _avg([s["slippage_bps"] for s in fills]),
        "median_slippage_bps": _med([s["slippage_bps"] for s in fills]),
        "mean_impact_bps": _avg([s["impact_bps"] for s in fills if s["impact_bps"] is not None]),
        "mean_drift_bps": _avg([s["drift_bps"] for s in counted if s["drift_bps"] is not None]),
        "mean_latency_s": _avg([s["latency_s"] for s in counted if s["latency_s"] is not None]),
        "median_latency_s": _med([s["latency_s"] for s in counted if s["latency_s"] is not None]),
        "latency_upper_bound": any(s["arrival_basis"] == "created_at" for s in counted),
        "sample": sample_flag(len(fills)),
    }
    return {
        "settings": {"ks": list(cfg.ks), "ttls_min": list(cfg.ttls_min), "taker_bps": cfg.taker_bps,
                     "maker_bps": cfg.maker_bps, "fee_diff_bps": cfg.fee_diff_bps, "tf": cfg.tf,
                     "enabled": cfg.enabled},
        "thresholds": {"min_n_any": MIN_N_ANY, "min_n_ok": MIN_N_OK},
        "actual": actual, "grid": list(grid.values()), "signals": sigs,
        "last_cycle": kv_get(conn, "shadow_last_cycle"),
    }
