"""Outlook storage in lab.db (self-contained tables, like the ledger/presets) + stdlib readers.

  lab_outlook   one row per symbol: the computed outlook row (row_json, small, for the list)
                and the detail extras (detail_json: candles, recent trades, headlines)
  lab_kv        'outlook_meta' (last run summary), 'outlook_bar' (scheduler), 'regime' (regime.py)
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Optional

from ..db import dumps, loads, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_outlook (
    symbol       TEXT PRIMARY KEY,
    computed_at  TEXT NOT NULL,
    last_bar     TEXT,
    row_json     TEXT,
    detail_json  TEXT,
    error        TEXT
);
"""
META_KEY = "outlook_meta"
BAR_KEY = "outlook_bar"
TEMPLATE_ID = "rosyade_family"
TIMEFRAME = "4h"
_lock = threading.Lock()


def ensure_schema(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_outlook'").fetchone():
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


def kv_get(conn, key: str):
    r = conn.execute("SELECT value FROM lab_kv WHERE key=?", (key,)).fetchone()
    return loads(r["value"]) if r else None


def kv_set(conn, key: str, value) -> None:
    conn.execute("INSERT INTO lab_kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, dumps(value)))


def save_row(conn, symbol: str, row: Optional[dict], detail: Optional[dict], error: Optional[str] = None) -> None:
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO lab_outlook (symbol, computed_at, last_bar, row_json, detail_json, error) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(symbol) DO UPDATE SET computed_at=excluded.computed_at, last_bar=excluded.last_bar, "
        "row_json=COALESCE(excluded.row_json, lab_outlook.row_json), "
        "detail_json=COALESCE(excluded.detail_json, lab_outlook.detail_json), error=excluded.error",
        (symbol, utcnow(), (row or {}).get("last_bar"), dumps(row), dumps(detail), error))


def read_rows(conn) -> list[dict]:
    ensure_schema(conn)
    out = []
    for r in conn.execute("SELECT symbol, computed_at, row_json, error FROM lab_outlook ORDER BY symbol"):
        row = loads(r["row_json"])
        if row is None:
            row = {"symbol": r["symbol"], "unavailable": True}
        out.append({**row, "error": r["error"], "row_computed_at": r["computed_at"]})
    return out


def read_one(conn, symbol: str) -> Optional[dict]:
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM lab_outlook WHERE symbol=?", (symbol,)).fetchone()
    if r is None:
        return None
    return {"row": loads(r["row_json"]), "detail": loads(r["detail_json"], {}) or {}, "error": r["error"],
            "computed_at": r["computed_at"]}


# ── inputs the job reads from lab.db (stdlib) ────────────────────────────

def pick_preset(presets: list[dict], symbol: str, timeframe: str = TIMEFRAME) -> Optional[dict]:
    """The coin's own preset: best PASS (highest holdout PF), else the live reference, else the
    best non-PASS one (a FAIL preset is still that coin's own evidence: keyakinan stays rendah).
    None -> template defaults ("belum diuji untuk koin ini")."""
    cands = [p for p in presets if p["symbol"] == symbol and p["timeframe"] == timeframe
             and p["template_id"] == TEMPLATE_ID]
    if not cands:
        return None

    def pf(p):
        v = (p.get("holdout") or {}).get("profit_factor")
        return v if isinstance(v, (int, float)) else -1.0

    passing = sorted((p for p in cands if p.get("verdict") == "PASS"), key=lambda p: (pf(p), p["id"]), reverse=True)
    if passing:
        return passing[0]
    live = [p for p in cands if p.get("live_reference")]
    if live:
        return live[0]
    return sorted(cands, key=lambda p: (p.get("verdict") is not None, pf(p), p["id"]), reverse=True)[0]


def preset_brief(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    h = p.get("holdout") or {}
    return {"id": p["id"], "name": p["name"], "verdict": p.get("verdict"), "live_reference": p.get("live_reference"),
            "holdout_start": h.get("start"), "holdout_end": h.get("end"), "contaminated": h.get("contaminated"),
            "failed_checks": h.get("failed_checks") or [], "holdout_pf": h.get("profit_factor"),
            "holdout_trades": h.get("trades"), "holdout_win_rate_pct": h.get("win_rate_pct"),
            "holdout_max_dd_pct": h.get("max_dd_pct"), "sizing_rule": h.get("sizing_rule")}


def screener_snapshot(conn) -> tuple[dict[str, dict], Optional[str]]:
    """Latest live screener snapshot from the Signal Ledger: ({symbol: state}, bar)."""
    have = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_screener_snapshots'").fetchone()
    if not have:
        return {}, None
    bar = conn.execute("SELECT MAX(bar) FROM ledger_screener_snapshots WHERE kind='live'").fetchone()[0]
    if not bar:
        return {}, None
    out = {}
    for r in conn.execute("SELECT symbol, data_json FROM ledger_screener_snapshots WHERE kind='live' AND bar=?", (bar,)):
        out[r["symbol"]] = {**(loads(r["data_json"], {}) or {}), "bar": bar}
    return out, bar


def track_map(conn) -> tuple[dict[str, str], Optional[dict]]:
    """{"type:dir": verdict code} from the screener track record (Signal Ledger)."""
    from ..ledger import track_record as tr
    try:
        rec = tr.compute(conn)
    except Exception:  # noqa: BLE001
        return {}, None
    m = {f"{i['signal_type']}:{i['direction']}": i["verdict"] for i in rec.get("items", [])}
    return m, {"period": rec.get("period"), "headline_horizon": rec.get("headline_horizon")}
