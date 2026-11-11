"""Ledger tables in lab.db (created on demand, additive) + small helpers. Stdlib only."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..db import dumps, loads, utcnow
from ..settings import REPO_ROOT, _read_dotenv

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,             -- screener|screener_rekon|lab_watch|universal|webhook
    signal_type  TEXT    NOT NULL,             -- e.g. komposit, tier_a, rosyade_family_4h, tv_open
    symbol       TEXT    NOT NULL,             -- BTCUSDT
    direction    INTEGER NOT NULL,             -- +1 long, -1 short
    ts           TEXT    NOT NULL,             -- signal time, ISO UTC
    ref          TEXT,                         -- watch:1 | universal:3 | tradingview
    price        REAL,                         -- price reported by the source (informational)
    meta_json    TEXT,
    dedupe_key   TEXT    NOT NULL UNIQUE,
    entry_ts     TEXT,                         -- set by the scorer (open of first 15m bar >= ts)
    entry_price  REAL,
    status       TEXT    NOT NULL DEFAULT 'pending',   -- pending | done | no_data
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_signals_ts ON ledger_signals (ts DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_signals_group ON ledger_signals (source, signal_type, ts);
CREATE INDEX IF NOT EXISTS idx_ledger_signals_symbol ON ledger_signals (symbol, ts);
CREATE INDEX IF NOT EXISTS idx_ledger_signals_status ON ledger_signals (status, symbol);

CREATE TABLE IF NOT EXISTS ledger_outcomes (
    signal_id    INTEGER NOT NULL,
    horizon      TEXT    NOT NULL,             -- 4h | 1d | 3d | 7d
    exit_ts      TEXT,
    exit_price   REAL,
    ret_pct      REAL,                         -- raw coin return entry -> exit
    dir_ret_pct  REAL,                         -- direction * ret_pct
    btc_ret_pct  REAL,                         -- BTC return over the same window
    rel_btc_pct  REAL,                         -- direction * (ret_pct - btc_ret_pct)
    mfe_pct      REAL,                         -- best excursion in the signal's favour (>= 0)
    mae_pct      REAL,                         -- worst excursion against it (<= 0)
    hit          INTEGER,                      -- 1 if dir_ret_pct > 0
    computed_at  TEXT    NOT NULL,
    PRIMARY KEY (signal_id, horizon)
);

-- Raw screener state per (kind, hour, coin): kept so events can be re-derived later.
CREATE TABLE IF NOT EXISTS ledger_screener_snapshots (
    kind       TEXT NOT NULL,                  -- live | rekon
    bar        TEXT NOT NULL,                  -- hour close the snapshot belongs to
    symbol     TEXT NOT NULL,
    data_json  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, bar, symbol)
);
"""

_lock = threading.Lock()


def ensure_schema(conn) -> None:
    """Create the ledger tables if missing (idempotent; one sqlite_master lookup when present)."""
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('ledger_signals','ledger_outcomes','ledger_screener_snapshots')").fetchone()[0]
    if have == 3:
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


# ── settings (LAB_LEDGER_*; read here so the shared LabSettings stays untouched) ──

@dataclass(frozen=True)
class LedgerSettings:
    enabled: bool = True
    backfill_days: int = 27
    snapshot_tf_s: int = 3600          # one screener snapshot per closed hour


def ledger_settings() -> LedgerSettings:
    env = _read_dotenv(REPO_ROOT / ".env")

    def g(k: str, d: str) -> str:
        return os.environ.get(k, env.get(k, d))

    try:
        days = max(0, min(29, int(g("LAB_LEDGER_BACKFILL_DAYS", "27"))))
    except ValueError:
        days = 27
    return LedgerSettings(enabled=g("LAB_LEDGER_ENABLED", "1") != "0", backfill_days=days)


# ── time helpers ──────────────────────────────────────────────────────────

def iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_epoch(s: str) -> float:
    """Parse ISO strings like 2026-11-09T00:00:07.471940+00:00 / ...Z / 2026-11-09 00:00:00."""
    t = s.strip().replace(" ", "T")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    d = datetime.fromisoformat(t)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def norm_symbol(sym: str) -> str:
    """BTC/USDT:USDT | BTCUSDT.P | btcusdt -> BTCUSDT."""
    s = str(sym or "").upper().split(":")[0].replace("/", "").replace("-", "")
    if s.endswith(".P"):
        s = s[:-2]
    return s


# ── kv ─────────────────────────────────────────────────────────────────────

def kv_get(conn, key: str, default: Any = None) -> Any:
    r = conn.execute("SELECT value FROM lab_kv WHERE key=?", (key,)).fetchone()
    return default if r is None else loads(r[0], default)


def kv_set(conn, key: str, value: Any) -> None:
    conn.execute("INSERT INTO lab_kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, dumps(value)))


# ── inserts ────────────────────────────────────────────────────────────────

def insert_signal(conn, *, source: str, signal_type: str, symbol: str, direction: int, ts: str,
                  dedupe_key: str, ref: Optional[str] = None, price: Optional[float] = None,
                  meta: Optional[dict] = None) -> bool:
    """INSERT OR IGNORE on dedupe_key. Returns True when a new row was written."""
    if direction not in (1, -1):
        raise ValueError("direction must be +1 or -1")
    cur = conn.execute(
        "INSERT OR IGNORE INTO ledger_signals (source, signal_type, symbol, direction, ts, ref, price, meta_json, "
        "dedupe_key, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (source, signal_type, norm_symbol(symbol), int(direction), ts, ref,
         float(price) if price not in (None, "") else None, dumps(meta) if meta else None, dedupe_key, utcnow()))
    return cur.rowcount > 0
