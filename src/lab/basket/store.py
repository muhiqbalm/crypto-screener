"""Basket tables in lab.db (created on demand, additive, never alters existing tables).

A basket row freezes its pre-registered definition: template, timeframe, params, costs,
coins, sizing and paper account can never be updated (trigger), and the reference numbers
(``expect_json``) can be set once. Only ``active`` (kill switch / stop) and ``notes`` change.
Members link a coin to its watch; events log every entry the basket skipped or shrank, so
the paper-vs-engine check can explain each miss. Stdlib only.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Callable, Optional

from ..db import dumps, loads, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_baskets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,                  -- 4H-BASKET-DonchianDef
    label         TEXT NOT NULL,
    title         TEXT,
    template_id   TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    costs_json    TEXT NOT NULL,
    symbols_json  TEXT NOT NULL,                  -- the fixed, pre-registered coin list
    sizing_json   TEXT NOT NULL,                  -- {mode, risk_pct, slots, caps, kill_dd_pct, ...}
    account_id    INTEGER NOT NULL,               -- paper_accounts.id (simulated money only)
    prereg_json   TEXT,                           -- {id, doc, json, commit}
    expect_json   TEXT,                           -- frozen reference backtest (set once)
    notes         TEXT,
    active        INTEGER NOT NULL DEFAULT 1,     -- 0 = no new entries (kill switch / stopped)
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lab_baskets_name ON lab_baskets (name);

CREATE TABLE IF NOT EXISTS lab_basket_members (
    basket_id   INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    watch_id    INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (basket_id, symbol)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lab_basket_members_watch ON lab_basket_members (watch_id);

CREATE TABLE IF NOT EXISTS lab_basket_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    basket_id   INTEGER NOT NULL,
    watch_id    INTEGER,
    symbol      TEXT,
    kind        TEXT NOT NULL,                    -- skip | shrink | kill
    reason      TEXT NOT NULL,
    bar         TEXT,                             -- signal bar (open time) of the entry concerned
    detail_json TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_basket_events ON lab_basket_events (basket_id, id DESC);

CREATE TRIGGER IF NOT EXISTS lab_baskets_definition_frozen
BEFORE UPDATE OF name, template_id, timeframe, params_json, costs_json, symbols_json, sizing_json, account_id,
                 prereg_json, created_at ON lab_baskets
BEGIN
    SELECT RAISE(ABORT, 'basket definition is pre-registered and cannot change');
END;
CREATE TRIGGER IF NOT EXISTS lab_baskets_expect_set_once
BEFORE UPDATE OF expect_json ON lab_baskets
WHEN OLD.expect_json IS NOT NULL AND NEW.expect_json IS NOT OLD.expect_json
BEGIN
    SELECT RAISE(ABORT, 'basket reference numbers are frozen');
END;
CREATE TRIGGER IF NOT EXISTS lab_basket_members_frozen
BEFORE UPDATE ON lab_basket_members
BEGIN
    SELECT RAISE(ABORT, 'basket members are pre-registered and cannot change');
END;
"""

TABLES = ("lab_baskets", "lab_basket_members", "lab_basket_events")
SIZING_MODES = ("risk", "slot_engine", "slot_fixed")
NAME_RE = re.compile(r"^[0-9]{1,2}[A-Z]-BASKET-[A-Za-z0-9][A-Za-z0-9_.]{0,23}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")

_lock = threading.Lock()


class BasketError(ValueError):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


# ── schema ─────────────────────────────────────────────────────────────────

def has_schema(conn: sqlite3.Connection) -> bool:
    n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
                     TABLES).fetchone()[0]
    return n == len(TABLES)


def ensure_schema(conn: sqlite3.Connection) -> None:
    if has_schema(conn):
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


# ── reads ──────────────────────────────────────────────────────────────────

def basket_out(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "label": r["label"], "title": r["title"],
        "template_id": r["template_id"], "timeframe": r["timeframe"],
        "params": loads(r["params_json"], {}), "costs": loads(r["costs_json"], {}),
        "symbols": loads(r["symbols_json"], []), "sizing": loads(r["sizing_json"], {}),
        "account_id": r["account_id"], "prereg": loads(r["prereg_json"]), "expect": loads(r["expect_json"]),
        "notes": r["notes"], "active": bool(r["active"]), "created_at": r["created_at"],
    }


def list_baskets(conn) -> list[dict]:
    if not has_schema(conn):
        return []
    return [basket_out(r) for r in conn.execute("SELECT * FROM lab_baskets ORDER BY id")]


def get(conn, basket_id: int) -> Optional[dict]:
    if not has_schema(conn):
        return None
    r = conn.execute("SELECT * FROM lab_baskets WHERE id=?", (basket_id,)).fetchone()
    return basket_out(r) if r is not None else None


def by_name(conn, name: str) -> Optional[dict]:
    if not has_schema(conn):
        return None
    r = conn.execute("SELECT * FROM lab_baskets WHERE name=?", (name,)).fetchone()
    return basket_out(r) if r is not None else None


def members(conn, basket_id: int) -> list[dict]:
    if not has_schema(conn):
        return []
    return [dict(r) for r in conn.execute(
        "SELECT basket_id, symbol, watch_id, created_at FROM lab_basket_members WHERE basket_id=? ORDER BY rowid",
        (basket_id,))]


def basket_of_watch(conn, watch_id: int) -> Optional[dict]:
    """The basket a watch belongs to (None for normal watches, or before the tables exist)."""
    if not has_schema(conn):
        return None
    r = conn.execute("SELECT b.* FROM lab_basket_members m JOIN lab_baskets b ON b.id = m.basket_id "
                     "WHERE m.watch_id=?", (watch_id,)).fetchone()
    return basket_out(r) if r is not None else None


def member_watch_ids(conn) -> set[int]:
    if not has_schema(conn):
        return set()
    return {int(r[0]) for r in conn.execute("SELECT watch_id FROM lab_basket_members")}


def events(conn, basket_id: int, limit: int = 200) -> list[dict]:
    if not has_schema(conn):
        return []
    out = []
    for r in conn.execute("SELECT * FROM lab_basket_events WHERE basket_id=? ORDER BY id DESC LIMIT ?",
                          (basket_id, int(limit))):
        d = dict(r)
        d["detail"] = loads(d.pop("detail_json"))
        out.append(d)
    return out


# ── writes ─────────────────────────────────────────────────────────────────

def log_event(conn, basket_id: int, kind: str, reason: str, *, watch_id: Optional[int] = None,
              symbol: Optional[str] = None, bar: Optional[str] = None, detail: Any = None) -> int:
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO lab_basket_events (basket_id, watch_id, symbol, kind, reason, bar, detail_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (basket_id, watch_id, symbol, kind, reason, bar, dumps(detail), utcnow()))
    conn.commit()
    return int(cur.lastrowid)


def set_active(conn, basket_id: int, active: bool) -> None:
    conn.execute("UPDATE lab_baskets SET active=? WHERE id=?", (1 if active else 0, basket_id))
    conn.commit()


def set_expect(conn, basket_id: int, expect: dict) -> None:
    """Store the frozen reference numbers once (trigger refuses a second, different value)."""
    conn.execute("UPDATE lab_baskets SET expect_json=? WHERE id=?", (dumps(expect), basket_id))
    conn.commit()


def check_sizing(sizing: dict, n_symbols: int) -> dict:
    s = dict(sizing or {})
    mode = s.get("mode")
    if mode not in SIZING_MODES:
        raise BasketError(f"sizing.mode must be one of {SIZING_MODES}")
    if mode == "risk" and not (0 < float(s.get("risk_pct") or 0) <= 5):
        raise BasketError("sizing.risk_pct must be in (0, 5]")
    if mode in ("slot_engine", "slot_fixed") and int(s.get("slots") or 0) != n_symbols:
        raise BasketError("sizing.slots must equal the number of coins (one slot per coin)")
    if mode == "slot_fixed" and not (0 < float(s.get("notional_x") or 0) <= 5):
        raise BasketError("sizing.notional_x must be in (0, 5]")
    for key, hi in (("max_position_notional_x", 5.0), ("gross_cap_x", 10.0)):
        if not (0 < float(s.get(key) or 0) <= hi):
            raise BasketError(f"sizing.{key} must be in (0, {hi}]")
    if int(s.get("max_open") or 0) < n_symbols:
        raise BasketError("sizing.max_open must allow one position per coin (no queue between coins)")
    if not (0 <= float(s.get("min_fill_frac", 0.1)) < 1):
        raise BasketError("sizing.min_fill_frac must be in [0, 1)")
    if not (0 < float(s.get("kill_dd_pct") or 0) < 100):
        raise BasketError("sizing.kill_dd_pct must be in (0, 100)")
    return s


def create(conn, spec: dict, *, insert_watch: Callable[..., int]) -> dict:
    """Create a pre-registered basket in ONE transaction: paper account, basket row, one
    auto-paper watch per coin and the member links. ``insert_watch`` is the API's watch insert
    (src.api.lab_routes._insert_watch): same validation, MTF refusal, active-watch cap and
    initial watch_eval job as POST /lab/watches. Nothing is written when any step fails."""
    ensure_schema(conn)
    name = str(spec.get("name") or "")
    if not NAME_RE.match(name):
        raise BasketError("name must look like 4H-BASKET-<Label>")
    if by_name(conn, name) is not None:
        raise BasketError(f"basket {name} already exists", 409)
    symbols = [str(s).upper() for s in spec.get("symbols") or []]
    if not symbols or len(set(symbols)) != len(symbols) or not all(SYMBOL_RE.match(s) for s in symbols):
        raise BasketError("symbols must be a non-empty list of unique XXXUSDT pairs")
    sizing = check_sizing(spec.get("sizing") or {}, len(symbols))
    acct = spec.get("account") or {}
    balance = float(acct.get("starting_balance", 10000.0))
    if balance <= 0:
        raise BasketError("account.starting_balance must be positive")
    now = utcnow()
    try:
        # same columns as paper.create_account (which commits, so it cannot join this transaction)
        aid = conn.execute(
            "INSERT INTO paper_accounts (name, starting_balance, balance, risk_pct, leverage_max, realized_pnl, "
            "created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (f"Paper {name}", balance, balance, float(acct.get("risk_pct", 100.0)),
             float(acct.get("leverage_max", sizing["max_position_notional_x"])), now)).lastrowid
        bid = conn.execute(
            "INSERT INTO lab_baskets (name, label, title, template_id, timeframe, params_json, costs_json, "
            "symbols_json, sizing_json, account_id, prereg_json, expect_json, notes, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (name, spec.get("label") or name.split("-", 2)[-1], spec.get("title"), spec["template_id"],
             spec["timeframe"], dumps(spec.get("params") or {}), dumps(spec.get("costs") or {}), dumps(symbols),
             dumps(sizing), aid, dumps(spec.get("prereg")), dumps(spec.get("expect")),
             (spec.get("notes") or None) and str(spec["notes"])[:2000], now)).lastrowid
        for sym in symbols:
            wid = insert_watch(conn, spec["template_id"], sym, spec["timeframe"], spec.get("params") or {},
                               spec.get("costs") or {})
            conn.execute("UPDATE watches SET autopaper_account_id=?, autopaper_enabled=1 WHERE id=?", (aid, wid))
            conn.execute("INSERT INTO lab_basket_members (basket_id, symbol, watch_id, created_at) VALUES (?, ?, ?, ?)",
                         (bid, sym, wid, now))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    out = get(conn, int(bid))
    assert out is not None
    return out
