"""lab_ai_summaries in lab.db (self-contained table, created on demand like the outlook and
ledger tables; CREATE ... IF NOT EXISTS, so it is safe against the live lab.db).

One row per coin per 4H bar = the cache: a coin is never summarised twice for the same bar.
``cost_usd`` is the cumulative spend of that row's API call(s); the daily budget sums it over
rows touched since 00:00 UTC (a row retried across midnight counts in full: conservative).
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from ..db import dumps, loads, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_ai_summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    bar                 TEXT NOT NULL,       -- 4H bar open of the Outlook row that was summarised
    bar_close           TEXT,
    input_hash          TEXT NOT NULL,       -- sha256 of prompt version + model + effort + facts
    model               TEXT NOT NULL,       -- model requested (LAB_AI_MODEL)
    served_model        TEXT,                -- model that answered (differs after a refusal fallback)
    effort              TEXT,
    status              TEXT NOT NULL,       -- ok | rejected | refused | error
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL NOT NULL DEFAULT 0,
    output_json         TEXT,                -- validated output: sentence, factors, data_gaps
    validation_json     TEXT,                -- what the number check found / dropped
    facts_json          TEXT,                -- the market facts that were sent (audit, phase 2)
    error               TEXT,
    attempts            INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (symbol, bar)
);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_sym_bar ON lab_ai_summaries (symbol, bar);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_updated ON lab_ai_summaries (updated_at);
"""
STATUSES = ("ok", "rejected", "refused", "error")
_lock = threading.Lock()


def ensure_schema(conn: sqlite3.Connection) -> None:
    have = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_ai_summaries'").fetchone()
    if have:
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


def day_start(now: Optional[datetime] = None) -> str:
    d = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT00:00:00")


def spent_today(conn, now: Optional[datetime] = None) -> float:
    ensure_schema(conn)
    r = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM lab_ai_summaries WHERE updated_at >= ?",
                     (day_start(now),)).fetchone()
    return float(r[0] or 0.0)


def get(conn, symbol: str, bar: str) -> Optional[dict]:
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM lab_ai_summaries WHERE symbol=? AND bar=?", (symbol, bar)).fetchone()
    return _out(r) if r else None


def latest(conn, symbol: str) -> Optional[dict]:
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM lab_ai_summaries WHERE symbol=? ORDER BY bar DESC LIMIT 1", (symbol,)).fetchone()
    return _out(r) if r else None


def _out(r) -> dict:
    d = dict(r)
    d["output"] = loads(d.pop("output_json", None))
    d["validation"] = loads(d.pop("validation_json", None))
    d["facts"] = loads(d.pop("facts_json", None))
    return d


def save(conn, rec: dict) -> None:
    """Insert the (symbol, bar) row, or add a new attempt to it (cost accumulates)."""
    ensure_schema(conn)
    now = utcnow()
    tok = rec.get("tokens") or {}
    vals = (rec["symbol"], rec["bar"], rec.get("bar_close"), rec["input_hash"], rec["model"], rec.get("served_model"),
            rec.get("effort"), rec["status"], int(tok.get("input_tokens") or 0), int(tok.get("output_tokens") or 0),
            int(tok.get("cache_read_input_tokens") or 0), int(tok.get("cache_creation_input_tokens") or 0),
            float(rec.get("cost_usd") or 0.0), dumps(rec.get("output")), dumps(rec.get("validation")),
            dumps(rec.get("facts")), (rec.get("error") or None) and str(rec["error"])[:1000], now, now)
    conn.execute(
        "INSERT INTO lab_ai_summaries (symbol, bar, bar_close, input_hash, model, served_model, effort, status, "
        "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, output_json, validation_json, "
        "facts_json, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(symbol, bar) DO UPDATE SET bar_close=excluded.bar_close, input_hash=excluded.input_hash, "
        "model=excluded.model, served_model=excluded.served_model, effort=excluded.effort, status=excluded.status, "
        "input_tokens=lab_ai_summaries.input_tokens + excluded.input_tokens, "
        "output_tokens=lab_ai_summaries.output_tokens + excluded.output_tokens, "
        "cache_read_tokens=lab_ai_summaries.cache_read_tokens + excluded.cache_read_tokens, "
        "cache_write_tokens=lab_ai_summaries.cache_write_tokens + excluded.cache_write_tokens, "
        "cost_usd=lab_ai_summaries.cost_usd + excluded.cost_usd, output_json=excluded.output_json, "
        "validation_json=excluded.validation_json, facts_json=excluded.facts_json, error=excluded.error, "
        "attempts=lab_ai_summaries.attempts + 1, updated_at=excluded.updated_at", vals)


def bar_counts(conn, bar: Optional[str]) -> dict:
    """{status: n, cost_usd} for one bar (status endpoint)."""
    ensure_schema(conn)
    if not bar:
        return {}
    out: dict = {s: 0 for s in STATUSES}
    cost = 0.0
    for r in conn.execute("SELECT status, COUNT(*), COALESCE(SUM(cost_usd), 0) FROM lab_ai_summaries WHERE bar=? "
                          "GROUP BY status", (bar,)):
        out[r[0]] = int(r[1])
        cost += float(r[2] or 0.0)
    out["cost_usd"] = round(cost, 4)
    return out


def last_bar(conn) -> Optional[str]:
    ensure_schema(conn)
    return conn.execute("SELECT MAX(bar) FROM lab_ai_summaries").fetchone()[0]
