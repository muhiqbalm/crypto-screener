"""Runtime estimates, per-timeframe defaults, queue ETA and the leaderboard.

Stdlib only and SQL only: imported by the API process, never runs the engine.

Runtime model (calibrated on production, ETH, 2026-11):
  validate  ~ 9.6 ms per evaluated bar (15m 2024->now 16 min, 30m 8 min, 1h 4 min,
            15m since 2020 ~40 min: all linear in bars)
  optimize  = validate + 0.64 ms per "trial-bar", where trial-bars mirrors the
            runner: walk-forward folds x per_fold trials x train-window bars, plus
            n_trials x development-segment bars (15m 2024->now x 60 trials ~1.75 h,
            4h since 2020 x 60 trials ~13 min)
  backtest  ~ 0.6 ms per bar + a few seconds of start-up
The constants are then scaled by the median actual/predicted ratio of the last
finished runs of the same mode, so the estimate tracks the real machine.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable, Optional

from . import db as labdb

TF_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
DATA_START = "2020-01-01"          # data_cache.DEFAULT_START (kept stdlib-only here)
HOLDOUT_FRACTION = 0.20
MONTH_S = 30.44 * 86400

S_PER_BAR = {"backtest": 0.0006, "validate": 0.0096}
S_PER_TRIAL_BAR = 0.00064
STARTUP_S = {"backtest": 5.0, "validate": 20.0, "optimize": 30.0}
DOWNLOAD_S = {"15m": 180.0, "30m": 120.0, "1h": 60.0, "4h": 30.0, "1d": 20.0}
UNIVERSAL_S = 600.0
OTHER_JOB_S = 120.0

# Defaults the UI applies when the user has not picked a period / trial count.
# Lower timeframes get a shorter history and fewer trials so a single job stays
# well inside its timeout (see the estimates in the docstring).
TF_DEFAULTS: dict[str, dict[str, Any]] = {
    "15m": {"start_years": 2, "n_trials": 10,
            "reason": "15m: 2 tahun data & 10 percobaan supaya validasi ±11 mnt, optimize ±20 mnt."},
    "30m": {"start_years": 3, "n_trials": 30,
            "reason": "30m: 3 tahun data supaya validasi ±8 mnt, optimize 30 percobaan ±30 mnt."},
    "1h": {"start": DATA_START, "n_trials": 30, "reason": None},
    "4h": {"start": DATA_START, "n_trials": 30, "reason": None},
    "1d": {"start": DATA_START, "n_trials": 30, "reason": None},
}

LONG_JOB_S = 45 * 60          # UI: "this is a long job" warning
TIMEOUT_DANGER_FRACTION = 0.8  # UI: confirmation needed above this share of the timeout


def _parse_day(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.combine(date.fromisoformat(str(s)[:10]), datetime.min.time())
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def default_start(tf: str, today: Optional[date] = None) -> str:
    d = TF_DEFAULTS.get(tf, {})
    if d.get("start_years"):
        t = today or datetime.now(timezone.utc).date()
        try:
            return t.replace(year=t.year - int(d["start_years"])).isoformat()
        except ValueError:  # 29 Feb
            return (t - timedelta(days=365 * int(d["start_years"]))).isoformat()
    return d.get("start") or DATA_START


def run_defaults(today: Optional[date] = None) -> dict[str, dict]:
    return {tf: {"start": default_start(tf, today), "n_trials": d["n_trials"], "reason": d["reason"]}
            for tf, d in TF_DEFAULTS.items()}


# ── runtime estimate ─────────────────────────────────────────────────────

def eval_bars(tf: str, start: Optional[str], end: Optional[str], data_first: Optional[str] = None,
              data_last: Optional[str] = None, now: Optional[datetime] = None) -> int:
    bar_s = TF_SECONDS.get(tf, 14400)
    now = now or datetime.now(timezone.utc)
    a = _parse_day(start) or _parse_day(DATA_START)
    first = _parse_day(data_first)
    if first and first > a:
        a = first
    b = _parse_day(end) or _parse_day(data_last) or now
    if b > now:
        b = now
    return max(0, int((b - a).total_seconds() // bar_s))


def _wf_trial_bars(dev_bars: int, bar_s: int, n_trials: int) -> int:
    """Mirror of runner.wf_windows / walk_forward_reopt sizing."""
    span_m = dev_bars * bar_s / MONTH_S
    train_m, test_m = (12, 3) if span_m >= 18 else (6, 3)
    windows = 0 if span_m < train_m + test_m else min(6, int((span_m - train_m) // test_m))
    per_fold = max(5, n_trials // 3)
    train_bars = int(train_m * MONTH_S / bar_s)
    return windows * per_fold * min(train_bars, dev_bars)


def base_seconds(mode: str, tf: str, bars: int, n_trials: Optional[int] = None) -> float:
    if mode == "backtest":
        return STARTUP_S["backtest"] + S_PER_BAR["backtest"] * bars
    validate = STARTUP_S["validate"] + S_PER_BAR["validate"] * bars
    if mode != "optimize":
        return validate
    n = int(n_trials or 30)
    dev = int(bars * (1 - HOLDOUT_FRACTION))
    trial_bars = _wf_trial_bars(dev, TF_SECONDS.get(tf, 14400), n) + n * dev
    return validate + STARTUP_S["optimize"] + S_PER_TRIAL_BAR * trial_bars


def calibration(conn: sqlite3.Connection, limit: int = 30) -> dict[str, float]:
    """Median actual/predicted ratio per mode over recently finished runs (1.0 = no data)."""
    rows = conn.execute(
        "SELECT r.mode, r.timeframe, r.n_trials, r.trials_done, r.metrics_json, j.started_at, j.finished_at "
        "FROM lab_runs r JOIN lab_jobs j ON j.id = r.job_id "
        "WHERE r.status='done' AND j.started_at IS NOT NULL AND j.finished_at IS NOT NULL "
        "AND r.template_id != 'universal_v0' ORDER BY r.id DESC LIMIT ?", (limit * 3,)).fetchall()
    ratios: dict[str, list[float]] = {}
    for r in rows:
        if len(ratios.get(r["mode"], [])) >= limit:
            continue
        m = labdb.loads(r["metrics_json"], {}) or {}
        bars = (m.get("data") or {}).get("bars")
        a, b = _parse_day(r["started_at"]), _parse_day(r["finished_at"])
        if not bars or not a or not b:
            continue
        actual = (b - a).total_seconds()
        pred = base_seconds(r["mode"], r["timeframe"], int(bars), r["n_trials"])
        if pred > 30 and actual > 0:  # tiny jobs are dominated by start-up noise
            ratios.setdefault(r["mode"], []).append(actual / pred)
    return {mode: max(0.5, min(3.0, median(v))) for mode, v in ratios.items() if len(v) >= 3}


class Estimator:
    """Per-request helper: data index + calibration loaded once."""

    def __init__(self, conn: sqlite3.Connection, datasets: Optional[dict] = None):
        self.datasets = datasets or {}
        self.calib = calibration(conn)

    def data(self, symbol: str, tf: str) -> Optional[dict]:
        return self.datasets.get(f"{symbol}_{tf}")

    def seconds(self, mode: str, symbol: str, tf: str, start: Optional[str], end: Optional[str],
                n_trials: Optional[int] = None, template_id: Optional[str] = None) -> dict:
        if template_id == "universal_v0":
            return {"seconds": UNIVERSAL_S, "bars": None, "cached": True}
        d = self.data(symbol, tf)
        bars = eval_bars(tf, start, end, (d or {}).get("first"), None)
        s = base_seconds(mode, tf, bars, n_trials) * self.calib.get(mode, 1.0)
        if d is None:
            s += DOWNLOAD_S.get(tf, 60.0)
        return {"seconds": round(s), "bars": bars, "cached": d is not None}


# ── queue snapshot / ETA ─────────────────────────────────────────────────

_HEAVY_SQL = ("SELECT j.id, j.kind, j.ref_id, j.status, j.priority, j.started_at, j.progress_json, "
              "j.payload_json, r.mode, r.symbol, r.timeframe, r.start_date, r.end_date, r.n_trials, "
              "r.scan_id, r.template_id FROM lab_jobs j LEFT JOIN lab_runs r ON j.kind='run' AND r.id=j.ref_id "
              "WHERE j.status IN ('queued','running') AND j.kind NOT IN ({fast}) "
              "ORDER BY CASE j.status WHEN 'running' THEN 0 ELSE 1 END, j.priority DESC, j.id ASC LIMIT 2000")


def _job_estimate(est: Estimator, j) -> float:
    if j["kind"] != "run" or j["mode"] is None:
        return OTHER_JOB_S
    payload = labdb.loads(j["payload_json"], {}) or {}
    return float(est.seconds(j["mode"], j["symbol"], j["timeframe"], j["start_date"], j["end_date"],
                             j["n_trials"] or payload.get("n_trials"), j["template_id"])["seconds"])


def queue_snapshot(conn: sqlite3.Connection, est: Estimator, slots: int, scan_cap: int,
                   fast_kinds: Iterable[str] = (), now: Optional[datetime] = None) -> dict:
    """Simulate the worker's claim order (priority desc, FIFO, scan-cell cap) to get
    a queue position, start ETA and finish ETA (seconds from now) per job."""
    now = now or datetime.now(timezone.utc)
    fast = ",".join(f"'{k}'" for k in fast_kinds) or "''"
    rows = conn.execute(_HEAVY_SQL.format(fast=fast)).fetchall()
    slots = max(1, slots)
    scan_cap = max(1, min(scan_cap, slots))
    jobs: list[dict] = []
    for r in rows:
        e = _job_estimate(est, r)
        d = {"job_id": r["id"], "kind": r["kind"], "run_id": r["ref_id"] if r["kind"] == "run" else None,
             "scan_id": r["scan_id"], "symbol": r["symbol"], "timeframe": r["timeframe"], "mode": r["mode"],
             "status": r["status"], "est_s": round(e), "elapsed_s": None, "remaining_s": None,
             "position": None, "eta_start_s": None, "eta_done_s": None}
        if r["status"] == "running":
            st = _parse_day(r["started_at"])
            elapsed = max(0.0, (now - st).total_seconds()) if st else 0.0
            rem = max(0.0, e - elapsed)
            p = labdb.loads(r["progress_json"], {}) or {}
            if p.get("total") and p.get("done") is not None and elapsed > 0:
                f = float(p["done"]) / float(p["total"])
                if 0.1 <= f < 1.0:
                    rem = elapsed * (1 - f) / f
            rem = max(30.0, rem)
            d.update(elapsed_s=round(elapsed), remaining_s=round(rem), eta_start_s=0, eta_done_s=round(rem))
        jobs.append(d)

    running = [(float(j["eta_done_s"]), j["scan_id"] is not None) for j in jobs if j["status"] == "running"]
    pending = [j for j in jobs if j["status"] == "queued"]
    t, pos = 0.0, 0
    for j in pending:
        pos += 1
        j["position"] = pos
    # discrete-event fill: at time t, start the first eligible queued job(s)
    guard = 0
    while pending and guard < 10000:
        guard += 1
        running = [x for x in running if x[0] > t]
        started = False
        if len(running) < slots:
            scans = sum(1 for x in running if x[1])
            for j in pending:
                is_scan = j["scan_id"] is not None
                if is_scan and scans >= scan_cap:
                    continue
                j["eta_start_s"] = round(t)
                j["eta_done_s"] = round(t + j["est_s"])
                running.append((t + j["est_s"], is_scan))
                pending.remove(j)
                started = True
                break
        if not started:
            t = min(x[0] for x in running) if running else t
    backlog = max([j["eta_done_s"] or 0 for j in jobs], default=0)
    return {"slots": slots, "scan_slots": scan_cap, "jobs": jobs, "backlog_s": backlog,
            "queued": sum(1 for j in jobs if j["status"] == "queued"),
            "running": sum(1 for j in jobs if j["status"] == "running")}


# ── leaderboard ──────────────────────────────────────────────────────────

SNOOP_MEDIUM = {"runs": 4, "timeframes": 3, "trials": 100}
SNOOP_HIGH = {"runs": 10, "timeframes": 5, "trials": 300}

SORT_KEYS = {"oos_pf": "profit_factor", "oos_sharpe": "sharpe", "oos_net": "net_return_pct"}


def snooping_level(runs: int, tfs: int, trials: int) -> str:
    if runs >= SNOOP_HIGH["runs"] or tfs >= SNOOP_HIGH["timeframes"] or trials >= SNOOP_HIGH["trials"]:
        return "high"
    if runs >= SNOOP_MEDIUM["runs"] or tfs >= SNOOP_MEDIUM["timeframes"] or trials >= SNOOP_MEDIUM["trials"]:
        return "medium"
    return "low"


def _n(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _pick(m: dict, keys=("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades", "win_rate_pct")) -> dict:
    return {k: _n(m.get(k)) for k in keys}


def leaderboard(conn: sqlite3.Connection, *, template_id: Optional[str] = None, symbol: Optional[str] = None,
                timeframe: Optional[str] = None, verdict: Optional[str] = None, mode: Optional[str] = None,
                sort: str = "oos_pf", limit: int = 200) -> dict:
    """Finished validate/optimize runs (scan cells included) ranked by HOLDOUT metrics.

    PASS rows always rank above FAIL rows, whatever the sort key, and only PASS
    rows get a rank number: a failing run is never shown as a winner. Every row
    carries how often its template+symbol was tried, so a best-of-many result is
    visibly best-of-many.
    """
    attempts: dict[tuple, dict] = {}
    for a in conn.execute(
            "SELECT template_id, symbol, COUNT(*) AS runs, COUNT(DISTINCT timeframe) AS tfs, "
            "COALESCE(SUM(trials_done), 0) AS trials FROM lab_runs WHERE mode IN ('validate','optimize') "
            "AND status NOT IN ('cancelled','error') GROUP BY template_id, symbol"):
        attempts[(a["template_id"], a["symbol"])] = {"runs": a["runs"], "timeframes": a["tfs"],
                                                      "trials": int(a["trials"] or 0)}
    tf_runs: dict[tuple, int] = {}
    for a in conn.execute(
            "SELECT template_id, symbol, timeframe, COUNT(*) AS n FROM lab_runs WHERE mode IN ('validate','optimize') "
            "AND status NOT IN ('cancelled','error') GROUP BY template_id, symbol, timeframe"):
        tf_runs[(a["template_id"], a["symbol"], a["timeframe"])] = a["n"]
    touches: dict[tuple, int] = {}
    for a in conn.execute("SELECT template_id, symbol, SUM(touches) AS t FROM holdout_locks GROUP BY 1, 2"):
        touches[(a["template_id"], a["symbol"])] = int(a["t"] or 0)

    sql = ("SELECT * FROM lab_runs WHERE status='done' AND mode IN ('validate','optimize') "
           "AND oos_metrics_json IS NOT NULL")
    args: list[Any] = []
    for col, val in (("template_id", template_id), ("symbol", symbol), ("timeframe", timeframe), ("mode", mode)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    if verdict in ("PASS", "FAIL"):
        sql += " AND verdict=?"
        args.append(verdict)
    rows = conn.execute(sql + " ORDER BY id DESC LIMIT 5000", args).fetchall()

    out = []
    for r in rows:
        oos = labdb.loads(r["oos_metrics_json"], {}) or {}
        m = labdb.loads(r["metrics_json"], {}) or {}
        oc = oos.get("costs") or {}
        checks = labdb.loads(r["checks_json"], []) or []
        att = attempts.get((r["template_id"], r["symbol"]), {"runs": 1, "timeframes": 1, "trials": 0})
        att = {**att, "runs_this_tf": tf_runs.get((r["template_id"], r["symbol"], r["timeframe"]), 1),
               "holdout_touches": touches.get((r["template_id"], r["symbol"]), r["holdout_touches"] or 0)}
        out.append({
            "run_id": r["id"], "scan_id": r["scan_id"], "template_id": r["template_id"], "symbol": r["symbol"],
            "timeframe": r["timeframe"], "mode": r["mode"], "verdict": r["verdict"], "created_at": r["created_at"],
            "start": r["start_date"], "end": r["end_date"], "holdout_start": r["holdout_start"],
            "holdout_touches": r["holdout_touches"], "n_trials": r["n_trials"], "trials_done": r["trials_done"],
            "holdout": {**_pick(oos), "stress_net_return_pct": _n(oos.get("stress_net_return_pct")),
                        "cost_drag_pct": _n(oc.get("cost_drag_pct")),
                        "trades_per_month": _n(oc.get("trades_per_month"))},
            "in_sample": _pick(m),
            "failed_checks": [c.get("name") for c in checks if not c.get("passed")],
            "attempts": att,
            "snooping": snooping_level(att["runs"], att["timeframes"], att["trials"]),
        })

    key = SORT_KEYS.get(sort, "profit_factor")

    def sk(x):
        v = x["holdout"].get(key)
        pf_inf = key == "profit_factor" and v is None and (x["holdout"].get("trades") or 0) > 0 \
            and (x["holdout"].get("net_return_pct") or 0) > 0  # PF None = no losing trade
        return (0 if x["verdict"] == "PASS" else 1, 0 if (v is not None or pf_inf) else 1,
                -(1e9 if pf_inf else (v if v is not None else 0)), -int(x["run_id"]))

    out.sort(key=sk)
    rank = 0
    for x in out:
        if x["verdict"] == "PASS":
            rank += 1
            x["rank"] = rank
        else:
            x["rank"] = None
    total = len(out)
    passes = sum(1 for x in out if x["verdict"] == "PASS")
    trials = sum(int(x["trials_done"] or 0) for x in out)
    combos = len({(x["template_id"], x["symbol"], x["timeframe"]) for x in out})
    return {
        "sort": sort if sort in SORT_KEYS else "oos_pf",
        "summary": {"runs": total, "pass": passes, "fail": total - passes, "trials": trials,
                    "combinations": combos},
        "rows": out[:limit],
        "thresholds": {"medium": SNOOP_MEDIUM, "high": SNOOP_HIGH},
    }
