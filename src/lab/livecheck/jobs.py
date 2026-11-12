"""``livecheck_cycle`` job: read the webhook evidence (logs + trade_logs, read-only),
recompute the expected 4H-ETH-Basic signals and rebuild the per-bar reconciliation.

Runs in an engine child (needs pandas + the engine). Log facts are stored first, so a
failing engine run never loses evidence that is about to rotate away.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from ..db import dumps, loads, utcnow
from ..ledger.store import iso, kv_get, kv_set, to_epoch
from ..settings import get_lab_settings
from . import logs as L
from .match import build_deliveries, match, merge_variants
from .store import ensure_schema, livecheck_settings
from .trades import read_trade_logs

log = logging.getLogger("lab.livecheck.jobs")
MAX_SIGS = 400


def load_preset(conn, name: str) -> tuple[dict, dict, str]:
    """(params, costs, source). The live reference preset; template defaults if absent."""
    try:
        r = conn.execute("SELECT params_json, costs_json FROM lab_presets WHERE name=? AND archived=0 "
                         "ORDER BY live_reference DESC, id LIMIT 1", (name,)).fetchone()
    except Exception:  # noqa: BLE001 - presets table not created yet
        r = None
    if r is not None:
        return loads(r["params_json"], {}) or {}, loads(r["costs_json"], {}) or {}, f"preset {name}"
    from ..templates.rosyade_family import defaults
    return defaults(), {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}, "template default"


def store_evidence(conn, cfg, now: float) -> dict:
    got = L.collect(cfg.nginx_glob, cfg.app_globs, cfg.webhook_path, cfg.local_ips,
                    skip_sigs=kv_get(conn, "livecheck_file_sigs", []) or [], now=now)
    seen = utcnow()
    new = 0
    for e in got["evidence"]:
        cur = conn.execute("INSERT OR IGNORE INTO livecheck_evidence (hash, source, kind, ts, data_json, seen_at) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (e["hash"], e["source"], e["kind"], e["ts"],
                                                         dumps(e["data"]), seen))
        new += cur.rowcount
    sigs = (kv_get(conn, "livecheck_file_sigs", []) or []) + got["sigs"]
    kv_set(conn, "livecheck_file_sigs", sigs[-MAX_SIGS:])
    for src in ("nginx", "app"):
        old = kv_get(conn, f"livecheck_cov_{src}", []) or []
        kv_set(conn, f"livecheck_cov_{src}",
               L.merge_intervals(old + [c for c in got["coverage"] if c[2] == src]))
    conn.commit()
    return {"files": got["files"], "facts": len(got["evidence"]), "new": new, "errors": got["errors"]}


def load_evidence(conn, since_s: float) -> list[dict]:
    return [{"source": r["source"], "kind": r["kind"], "ts": r["ts"], "data": loads(r["data_json"], {}) or {}}
            for r in conn.execute("SELECT source, kind, ts, data_json FROM livecheck_evidence WHERE ts >= ? "
                                  "ORDER BY ts", (since_s,))]


def execute_cycle(conn, job: Optional[dict] = None, now: Optional[float] = None,
                  compute_fn: Optional[Callable] = None, trading_db_path: Optional[str] = None) -> dict:
    ensure_schema(conn)
    cfg = livecheck_settings()
    now = now or time.time()
    out: dict = {"started": iso(now), "preset": cfg.preset_name, "symbol": cfg.symbol, "tf": cfg.tf,
                 "since": cfg.since, "price_bps": cfg.price_bps}
    out["logs"] = store_evidence(conn, cfg, now)

    params, costs, src = load_preset(conn, cfg.preset_name)
    out["params_source"] = src
    if compute_fn is None:
        from .expected import compute as compute_fn
    try:
        exp = compute_fn(params, costs, cfg.symbol, cfg.tf, cfg.since, cfg.short_history_days)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["finished"] = utcnow()
        kv_set(conn, "livecheck_last_cycle", out)
        conn.commit()
        raise
    step = 14400 if cfg.tf == "4h" else {"1h": 3600, "1d": 86400}.get(cfg.tf, 14400)
    since_s = to_epoch(cfg.since + "T00:00:00Z" if len(cfg.since) == 10 else cfg.since)

    path = trading_db_path if trading_db_path is not None else get_lab_settings().trading_db_path
    tl = [r for r in read_trade_logs(path, cfg.symbol) if r["ts"] >= since_s - step]
    cov_nginx = kv_get(conn, "livecheck_cov_nginx", []) or []
    cov_all = L.merge_intervals(cov_nginx + (kv_get(conn, "livecheck_cov_app", []) or []))
    deliveries = build_deliveries(load_evidence(conn, since_s - step), tl, cfg.symbol, cov_nginx, now,
                                  cfg.pending_s)
    primary, alt = merge_variants(exp["variants"])
    rows = match(primary, alt, deliveries, step=step, coverage=cov_all, now=now,
                 data_last_bar=exp.get("data_last_bar"), price_bps=cfg.price_bps)

    computed = utcnow()
    with conn:
        conn.execute("DELETE FROM livecheck_rows")
        conn.executemany(
            "INSERT INTO livecheck_rows (bar_open_ts, bar_close_ts, status, perlu_dicek, causes_json, action, side, "
            "reason, price_diff_bps, expected_json, delivery_json, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?)",
            [(iso(r["bar_open"]), iso(r["bar_close"]), r["status"], int(r["perlu_dicek"]), dumps(r["causes"]),
              r["action"], r["side"], r["reason"], r["price_diff_bps"], dumps(r["expected"]),
              dumps(r["delivery"]), computed) for r in rows])
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out.update({
        "engine_commit": exp.get("engine_commit"),
        "data_first_bar": iso(exp["data_first_bar"]) if exp.get("data_first_bar") else None,
        "data_last_bar": iso(exp["data_last_bar"]) if exp.get("data_last_bar") else None,
        "expected": {k: len(v) for k, v in exp["variants"].items()},
        "deliveries": len(deliveries), "trade_log_rows": len(tl), "rows": len(rows), "counts": counts,
        "coverage": [[iso(a), iso(b), s] for a, b, s in cov_all],
        "finished": utcnow(),
    })
    kv_set(conn, "livecheck_last_cycle", out)
    conn.commit()
    from ..notify_events import livecheck_alarms  # sticky in-web notification per failed live order; never raises
    livecheck_alarms(conn, rows, cfg.symbol, cfg.preset_name, now)
    log.info("livecheck cycle %s", {k: out[k] for k in ("counts", "deliveries", "data_last_bar")})
    return out


def execute(conn, job: dict) -> None:
    import os
    offline = os.environ.get("LAB_DATA_OFFLINE") == "1"
    fn = None
    if offline:
        from .expected import compute

        def fn(*a, **k):
            return compute(*a, offline=True, **k)
    execute_cycle(conn, job, compute_fn=fn)
