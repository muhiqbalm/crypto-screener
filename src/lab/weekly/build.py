"""Build the weekly report for one ISO week (stdlib; lab.db + read-only sources).

Each section returns ``{"available": bool, ...}``; ``available`` is False when the
source has no data for the week, so the UI says "belum ada data" instead of zeros.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Optional

from ..db import utcnow
from . import store, system

TRADES_TARGET = 30                 # paper trades before a preset's record is worth judging
SNOOP_RULE = {"runs": 4, "timeframes": 3, "trials": 100}   # same thresholds as the Preset page
EXECUTED = {"success", "filled", "ok", "done", "executed"}
REJECTED = {"rejected", "failed", "failure", "error"}

# Pages built in parallel by other teams; the UI links to them, data can be wired in later.
HOOKS = [
    {"id": "arena", "title": "Arena Paper", "href": "/lab/arena",
     "note": "Perbandingan preset paper berdampingan."},
    {"id": "live_check", "title": "Cek Live vs Strategi", "href": "/lab/live-check",
     "note": "Apakah bot live mengikuti strategi acuannya."},
    {"id": "outlook", "title": "Outlook Koin", "href": "/lab/outlook",
     "note": "Pandangan per koin untuk minggu berikutnya."},
]


def _have(conn, *tables: str) -> bool:
    ph = ",".join("?" * len(tables))
    n = conn.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ({ph})", tables).fetchone()[0]
    return n == len(tables)


def _epoch(v) -> Optional[float]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000.0 if v > 1e11 else 1.0)
    s = str(v).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def _avg(xs):
    return mean(xs) if xs else None


def _med(xs):
    return median(xs) if xs else None


# ── paper presets ─────────────────────────────────────────────────────────

def _max_dd(start_balance: float, pnls: list[float]) -> Optional[float]:
    """Max drawdown (%) of the realised equity curve (closed trades only)."""
    if not pnls:
        return None
    eq = peak = start_balance
    dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, (peak - eq) / peak * 100.0)
    return dd


def paper_section(conn, start: str, end: str, partial: bool) -> dict:
    if not _have(conn, "lab_presets", "lab_preset_links"):
        return {"available": False, "presets": [], "best": None, "worst": None, "target_trades": TRADES_TARGET}
    rows = conn.execute(
        "SELECT p.id AS preset_id, p.name, p.live_reference, w.id AS watch_id, w.active, w.autopaper_enabled, "
        "w.created_at AS started_at, a.id AS account_id, a.starting_balance, a.balance "
        "FROM lab_preset_links l JOIN lab_presets p ON p.id = l.preset_id JOIN watches w ON w.id = l.ref_id "
        "JOIN paper_accounts a ON a.id = w.autopaper_account_id WHERE l.kind='watch' AND w.created_at < ? "
        "ORDER BY p.name", (end,)).fetchall()
    out = []
    for r in rows:
        closed = conn.execute(
            "SELECT pnl, exit_time, side, symbol FROM paper_positions WHERE account_id=? AND status='closed' "
            "AND exit_time < ? ORDER BY exit_time, id", (r["account_id"], end)).fetchall()
        before = [c["pnl"] or 0.0 for c in closed if c["exit_time"] < start]
        week = [c["pnl"] or 0.0 for c in closed if c["exit_time"] >= start]
        sb = float(r["starting_balance"])
        bal_start = sb + sum(before)
        bal_end = bal_start + sum(week)
        open_pos = conn.execute(
            "SELECT side, qty, entry_price, mark_price, fees, funding FROM paper_positions WHERE account_id=? "
            "AND entry_time < ? AND (status='open' OR exit_time >= ?)", (r["account_id"], end, end)).fetchall()
        upnl = None
        if partial and open_pos:
            upnl = 0.0
            for p in open_pos:
                if p["mark_price"] is not None:
                    d = 1.0 if p["side"] == "long" else -1.0
                    upnl += (p["mark_price"] - p["entry_price"]) * p["qty"] * d - (p["fees"] or 0) - (p["funding"] or 0)
        out.append({
            "preset": r["name"], "preset_id": r["preset_id"], "live_reference": bool(r["live_reference"]),
            "watch_id": r["watch_id"], "account_id": r["account_id"], "started_at": r["started_at"],
            "active": bool(r["active"] and r["autopaper_enabled"]),
            "starting_balance": sb, "balance_start": bal_start, "balance_end": bal_end,
            "week_pnl": sum(week), "week_return_pct": (bal_end - bal_start) / bal_start * 100 if bal_start else None,
            "total_return_pct": (bal_end - sb) / sb * 100 if sb else None,
            "trades_week": len(week), "wins_week": sum(1 for p in week if p > 0),
            "trades_total": len(closed), "wins_total": sum(1 for c in closed if (c["pnl"] or 0) > 0),
            "max_dd_pct": _max_dd(sb, [c["pnl"] or 0.0 for c in closed]),
            "week_dd_pct": _max_dd(bal_start, week),
            "open_positions": len(open_pos), "unrealized_pnl": upnl,
            "progress_pct": min(100.0, len(closed) / TRADES_TARGET * 100),
        })
    traded = [p for p in out if p["trades_week"] > 0]
    best = max(traded, key=lambda p: p["week_return_pct"]) if traded else None
    worst = min(traded, key=lambda p: p["week_return_pct"]) if len(traded) > 1 else None
    return {
        "available": bool(out), "presets": out, "target_trades": TRADES_TARGET,
        "best": best and {"preset": best["preset"], "week_return_pct": best["week_return_pct"]},
        "worst": worst and {"preset": worst["preset"], "week_return_pct": worst["week_return_pct"]},
        "trades_week": sum(p["trades_week"] for p in out), "trades_total": sum(p["trades_total"] for p in out),
        "note": "Return dan DD dari trade yang sudah ditutup (ekuitas terealisasi); posisi terbuka dihitung terpisah.",
    }


# ── Signal Ledger ─────────────────────────────────────────────────────────

def ledger_section(conn, start: str, end: str) -> dict:
    from ..ledger.verdicts import verdicts
    overall = {v["key"]: v for v in verdicts(conn, until=end)}
    week = {v["key"]: v for v in verdicts(conn, since=start, until=end)}
    if not overall:
        return {"available": False, "groups": [], "counts_week": {}, "counts_overall": {}}
    groups = []
    for k, o in overall.items():
        w = week.get(k)
        groups.append({
            "key": k, "source": o["source"], "signal_type": o["signal_type"], "direction": o["direction"],
            "overall": {x: o[x] for x in ("n_signals", "n", "days", "hit_rate", "mean_pct", "mean_ci", "verdict")},
            "week": {x: w[x] for x in ("n_signals", "n", "days", "hit_rate", "mean_pct", "mean_ci", "verdict")}
            if w else None,
        })

    def counts(vs) -> dict:
        c: dict[str, int] = {}
        for v in vs:
            c[v["verdict"]] = c.get(v["verdict"], 0) + 1
        return c
    return {
        "available": True, "horizon": "1d", "groups": groups,
        "counts_overall": counts(overall.values()), "counts_week": counts(week.values()),
        "signals_week": sum(v["n_signals"] for v in week.values()),
        "note": "Vonis horizon 1 hari (CI 95% klaster per hari, minimal 10 sinyal di 5 hari). Sinyal hari terakhir "
                "minggu ini belum punya hasil 1 hari saat laporan dibuat.",
    }


# ── execution quality (shadow) ────────────────────────────────────────────

def execution_section(conn, start: str, end: str) -> dict:
    if not _have(conn, "shadow_signals", "shadow_results"):
        return {"available": False}
    from ..shadow.report import cell_stats
    from ..shadow.store import shadow_settings

    def actual(sigs: list) -> dict:
        counted = [s for s in sigs if not s["off_close"]]
        fills = [s for s in counted if s["slippage_bps"] is not None]
        lat = [s["latency_s"] for s in counted if s["latency_s"] is not None]
        return {"n_signals": len(sigs), "n_counted": len(counted), "n_with_fill": len(fills),
                "mean_slippage_bps": _avg([s["slippage_bps"] for s in fills]),
                "median_slippage_bps": _med([s["slippage_bps"] for s in fills]),
                "mean_latency_s": _avg(lat), "median_latency_s": _med(lat),
                "latency_upper_bound": any(s["arrival_basis"] == "created_at" for s in counted)}

    cols = "id, symbol, action, side, arrival_ts, arrival_basis, off_close, slippage_bps, latency_s"
    all_sigs = [dict(r) for r in conn.execute(f"SELECT {cols} FROM shadow_signals WHERE arrival_ts < ?", (end,))]
    wk = [s for s in all_sigs if s["arrival_ts"] >= start]
    if not all_sigs:
        return {"available": False}
    ids = {s["id"] for s in wk if not s["off_close"]}
    res = [dict(r) for r in conn.execute("SELECT * FROM shadow_results")] if ids else []
    cfg = shadow_settings()
    grid = []
    for k in cfg.ks:
        for ttl in cfg.ttls_min:
            rows = [x for x in res if x["signal_id"] in ids and x["k"] == k and x["ttl_min"] == ttl]
            if rows:
                grid.append({"k": k, "ttl_min": ttl, **cell_stats(rows)})
    return {"available": bool(wk), "week": actual(wk), "overall": actual(all_sigs), "grid_week": grid,
            "signals": [{"symbol": s["symbol"], "action": s["action"], "side": s["side"], "arrival_ts": s["arrival_ts"],
                         "slippage_bps": s["slippage_bps"], "latency_s": s["latency_s"],
                         "off_close": bool(s["off_close"])} for s in wk][:50]}


# ── live bot activity (trade_logs, read-only) ─────────────────────────────

def read_trade_logs(path: str, limit: int = 50000) -> Optional[list[dict]]:
    """symbol / action / side / status / created_at / user_id only. None = DB or table missing.
    Separate mode=ro + query_only connection, same as the ledger collector and shadow source."""
    if not path or not Path(path).exists():
        return None
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    try:
        src.execute("PRAGMA query_only=1")
        cols = {r[1] for r in src.execute("PRAGMA table_info(trade_logs)")}
        if not {"symbol", "action", "side", "created_at"} <= cols:
            return None
        sel = ["symbol", "action", "side", "created_at",
               "status" if "status" in cols else "NULL AS status",
               "user_id" if "user_id" in cols else "NULL AS user_id"]
        rows = src.execute(f"SELECT {', '.join(sel)} FROM trade_logs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(zip(("symbol", "action", "side", "created_at", "status", "user_id"), r)) for r in rows]
    finally:
        src.close()


def live_bot_section(trading_db_path: str, start: str, end: str, tf_s: int = 14400) -> dict:
    from ..ledger.store import iso, norm_symbol
    try:
        rows = read_trade_logs(trading_db_path)
    except sqlite3.Error as e:
        return {"available": False, "error": f"bmtm_trading.db tidak bisa dibaca ({type(e).__name__})"}
    if rows is None:
        return {"available": False}
    a, b = _epoch(start), _epoch(end)
    week = []
    for r in rows:
        t = _epoch(r["created_at"])
        if t is not None and a <= t < b:
            week.append({**r, "_t": t})
    if not week:
        return {"available": False, "orders": 0}
    status: dict[str, int] = {}
    alerts: dict[str, dict] = {}
    for r in sorted(week, key=lambda x: x["_t"]):
        st = (r["status"] or "unknown").lower()
        status[st] = status.get(st, 0) + 1
        sym = norm_symbol(r["symbol"])
        bar = r["_t"] - r["_t"] % tf_s
        key = f"{sym}|{(r['action'] or '').lower()}|{(r['side'] or '').lower()}|{bar}"
        g = alerts.setdefault(key, {"ts": iso(r["_t"]), "symbol": sym, "action": (r["action"] or "").lower(),
                                    "side": (r["side"] or "").lower(), "orders": 0, "executed": 0, "rejected": 0,
                                    "other": 0, "users": set()})
        g["orders"] += 1
        g["executed" if st in EXECUTED else "rejected" if st in REJECTED else "other"] += 1
        if r["user_id"] is not None:
            g["users"].add(str(r["user_id"]))
    out_alerts = []
    for g in alerts.values():
        g["users"] = len(g["users"])
        out_alerts.append(g)
    by_symbol: dict[str, int] = {}
    for g in out_alerts:
        by_symbol[g["symbol"]] = by_symbol.get(g["symbol"], 0) + 1
    return {
        "available": True, "signals": len(out_alerts), "orders": len(week),
        "executed": sum(v for k, v in status.items() if k in EXECUTED),
        "rejected": sum(v for k, v in status.items() if k in REJECTED),
        "by_status": status, "by_symbol": by_symbol, "alerts": out_alerts[-50:],
        "note": "Satu sinyal = satu alert TradingView (simbol, aksi, sisi, bar 4H); satu order = satu baris per user.",
    }


# ── Lab activity ──────────────────────────────────────────────────────────

def lab_section(conn, start: str, end: str) -> dict:
    runs = [dict(r) for r in conn.execute(
        "SELECT id, scan_id, template_id, symbol, timeframe, mode, status, verdict, net_return_pct, max_dd_pct, "
        "trades FROM lab_runs WHERE created_at >= ? AND created_at < ?", (start, end))]
    by_mode: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in runs:
        by_mode[r["mode"]] = by_mode.get(r["mode"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    passes = [r for r in runs if r["verdict"] == "PASS"]
    fails = [r for r in runs if r["verdict"] == "FAIL"]
    scans = conn.execute("SELECT COUNT(*) FROM lab_scans WHERE created_at >= ? AND created_at < ?",
                         (start, end)).fetchone()[0]
    presets = []
    if _have(conn, "lab_presets"):
        presets = [dict(r) for r in conn.execute(
            "SELECT id, name, verdict, source_run_id, source_mode, archived, created_at FROM lab_presets "
            "WHERE created_at >= ? AND created_at < ? ORDER BY created_at", (start, end))]
    warnings = []
    from ..presets import snooping_at
    combos = sorted({(r["template_id"], r["symbol"]) for r in runs if r["mode"] in ("validate", "optimize")})
    for tpl, sym in combos:
        s = snooping_at(conn, tpl, sym)
        if any(s[k] >= v for k, v in SNOOP_RULE.items()):
            warnings.append({"template_id": tpl, "symbol": sym, **s})
    jobs: dict[str, dict] = {}
    for r in conn.execute("SELECT kind, status, COUNT(*) AS n FROM lab_jobs WHERE created_at >= ? AND created_at < ? "
                          "GROUP BY kind, status", (start, end)):
        jobs.setdefault(r["kind"], {})[r["status"]] = r["n"]
    available = bool(runs or scans or presets or jobs)
    return {
        "available": available, "runs": len(runs), "runs_by_mode": by_mode, "runs_by_status": by_status,
        "scans": scans, "pass": len(passes), "fail": len(fails),
        "pass_runs": [{k: r[k] for k in ("id", "template_id", "symbol", "timeframe", "mode", "net_return_pct",
                                         "max_dd_pct", "trades", "scan_id")} for r in passes][:30],
        "presets_saved": [{"id": p["id"], "name": p["name"], "verdict": p["verdict"], "source_run_id": p["source_run_id"],
                           "archived": bool(p["archived"]), "created_at": p["created_at"]} for p in presets],
        "snooping_warnings": warnings, "snooping_rule": SNOOP_RULE, "jobs": jobs,
    }


# ── assemble ──────────────────────────────────────────────────────────────

def _section(fn, *a) -> dict:
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 - one broken source must not hide the rest of the report
        return {"available": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def build(conn, week: str, trading_db_path: str, now: Optional[datetime] = None,
          deploy_log: Optional[str] = None, backup_log: Optional[str] = None, pm2_runner=None) -> dict:
    now = now or datetime.now(timezone.utc)
    s_dt, e_dt = store.bounds(week)
    start, end = store.iso(s_dt), store.iso(e_dt)
    partial = now < e_dt
    sys_sec = {
        "available": True,
        "deploys": _section(system.deploys, start, end, deploy_log),
        "backups": _section(system.backups, start, end, backup_log),
        # PM2 is a "now" reading: meaningful for the current week and frozen into the snapshot
        "processes": system.pm2_processes(pm2_runner) if (partial or now - e_dt < (e_dt - s_dt)) else None,
        "processes_at": store.iso(now),
    }
    return {
        "week": week, "start": start, "end": end, "partial": partial, "generated_at": utcnow(),
        "sections": {
            "paper": _section(paper_section, conn, start, end, partial),
            "ledger": _section(ledger_section, conn, start, end),
            "execution": _section(execution_section, conn, start, end),
            "live_bot": _section(live_bot_section, trading_db_path, start, end),
            "lab": _section(lab_section, conn, start, end),
            "system": sys_sec,
        },
        "hooks": HOOKS,
    }


def get_or_build(conn, week: str, trading_db_path: str, now: Optional[datetime] = None) -> dict:
    """The frozen snapshot when there is one, else a live build (current or un-snapshotted week)."""
    snap = store.get(conn, week)
    if snap is not None:
        snap["source"] = "snapshot"
        return snap
    rep = build(conn, week, trading_db_path, now=now)
    rep["source"] = "live"
    rep["snapshot"] = None
    return rep

