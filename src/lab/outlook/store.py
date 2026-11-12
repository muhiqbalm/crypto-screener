"""Outlook storage in lab.db (self-contained tables, like the ledger/presets) + stdlib readers.

  lab_outlook        one row per symbol: the computed outlook row (row_json, small, for the list)
                     and the detail extras (detail_json: candles, recent trades, headlines)
  lab_outlook_calls  every call the page showed, one per symbol per 4H bar (additive, v2), and its
                     after-the-fact outcome (evaluate.py): the live track record "Rekam jejak"
  lab_kv             'outlook_meta' (last run summary), 'outlook_bar' (scheduler), 'regime' (regime.py),
                     'outlook_calibration' (replay.py)

All DDL is CREATE ... IF NOT EXISTS: safe to run against the live lab.db.
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
CREATE TABLE IF NOT EXISTS lab_outlook_calls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    bar                 TEXT NOT NULL,       -- 4H bar open; the call is made at its close
    bar_close           TEXT NOT NULL,
    computed_at         TEXT NOT NULL,
    side                TEXT,                -- long | short | NULL (NETRAL: no call)
    keyakinan           TEXT,
    keyakinan_basis     TEXT,                -- kalibrasi | aturan
    cls                 TEXT,                -- lolos_uji | belum_diuji | gagal_uji
    align               TEXT,                -- searah | campuran | berlawanan
    fase                TEXT,                -- baru | berjalan
    strategy            TEXT,                -- preset name or 'Rosyade default 4H'
    template_id         TEXT,
    timeframe           TEXT,
    strategy_entry_time TEXT,                -- identifies the strategy position (batal when it changes)
    price               REAL,
    sl                  REAL,
    tp                  REAL,
    horizon_bars        INTEGER,
    rr                  REAL,
    ev_r                REAL,
    call_json           TEXT,
    status              TEXT,                -- none | open | tp | sl | batal | expired | invalid
    r_net               REAL,
    r_gross             REAL,
    mfe_r               REAL,
    mae_r               REAL,
    exit_price          REAL,
    bars_to_resolve     INTEGER,
    ambiguous           INTEGER,
    resolved_at         TEXT,
    evaluated_at        TEXT,
    kualitas            TEXT,                -- skor kualitas at call time: A | B | C | D | '-' (quality.py)
    kualitas_json       TEXT,
    UNIQUE (symbol, bar)
);
CREATE INDEX IF NOT EXISTS idx_outlook_calls_status ON lab_outlook_calls (status, symbol);
CREATE INDEX IF NOT EXISTS idx_outlook_calls_sym_bar ON lab_outlook_calls (symbol, bar);
"""
META_KEY = "outlook_meta"
BAR_KEY = "outlook_bar"
TEMPLATE_ID = "rosyade_family"
TIMEFRAME = "4h"
DEFAULT_NAME = "Rosyade default 4H"
MAX_STRATEGIES = 6            # engine runs per coin per refresh (primary + agreement panel)
MAX_PASS = 4
TF_OK = ("15m", "30m", "1h", "4h", "1d")
DONE = ("tp", "sl", "batal", "expired")
# Additive column migrations for lab_outlook_calls created by an earlier version (same pattern as db.py).
_CALL_MIGRATIONS = (("kualitas", "TEXT"), ("kualitas_json", "TEXT"))
_migrated: set[str] = set()
_lock = threading.Lock()


def ensure_schema(conn: sqlite3.Connection) -> None:
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('lab_outlook','lab_outlook_calls')").fetchone()[0]
    if have != 2:
        with _lock:
            if conn.in_transaction:
                conn.commit()
            conn.executescript(SCHEMA)
            conn.commit()
    _migrate_calls(conn)


def _migrate_calls(conn: sqlite3.Connection) -> None:
    try:
        path = conn.execute("PRAGMA database_list").fetchone()[2] or ""
    except (sqlite3.Error, IndexError, TypeError):
        path = ""
    if path and path in _migrated:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(lab_outlook_calls)")}
    missing = [(c, t) for c, t in _CALL_MIGRATIONS if c not in cols]
    if missing:
        with _lock:
            try:
                if conn.in_transaction:
                    conn.commit()
                for c, t in missing:
                    conn.execute(f"ALTER TABLE lab_outlook_calls ADD COLUMN {c} {t}")
                conn.commit()
            except sqlite3.OperationalError as e:   # read-only connection or a concurrent migration
                if "duplicate column" not in str(e).lower():
                    return
    if path:
        _migrated.add(path)


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


# ── call history (track record) ──────────────────────────────────────────

CALL_COLS = ("symbol", "bar", "bar_close", "computed_at", "side", "keyakinan", "keyakinan_basis", "cls", "align",
             "fase", "strategy", "template_id", "timeframe", "strategy_entry_time", "price", "sl", "tp",
             "horizon_bars", "rr", "ev_r", "call_json", "status", "kualitas", "kualitas_json")


def save_call(conn, call: dict) -> None:
    """Upsert the call of (symbol, bar). A recomputation of the same bar resets its outcome
    (it is re-evaluated by the same job)."""
    ensure_schema(conn)
    vals = {k: call.get(k) for k in CALL_COLS}
    vals["computed_at"] = vals["computed_at"] or utcnow()
    vals["call_json"] = dumps(call.get("call_json")) if not isinstance(call.get("call_json"), str) else call["call_json"]
    if not isinstance(call.get("kualitas_json"), str):
        vals["kualitas_json"] = dumps(call.get("kualitas_json"))
    vals["status"] = vals["status"] or ("open" if vals["side"] else "none")
    cols = ", ".join(CALL_COLS)
    marks = ", ".join("?" * len(CALL_COLS))
    upd = ", ".join(f"{k}=excluded.{k}" for k in CALL_COLS if k not in ("symbol", "bar"))
    conn.execute(
        f"INSERT INTO lab_outlook_calls ({cols}) VALUES ({marks}) ON CONFLICT(symbol, bar) DO UPDATE SET {upd}, "
        "r_net=NULL, r_gross=NULL, mfe_r=NULL, mae_r=NULL, exit_price=NULL, bars_to_resolve=NULL, ambiguous=NULL, "
        "resolved_at=NULL, evaluated_at=NULL", [vals[k] for k in CALL_COLS])


def _call_out(r) -> dict:
    d = dict(r)
    d["call"] = loads(d.pop("call_json", None), {}) or {}
    d["kualitas_info"] = loads(d.pop("kualitas_json", None))
    return d


def prev_call(conn, symbol: str, before_bar: str) -> Optional[dict]:
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM lab_outlook_calls WHERE symbol=? AND bar<? ORDER BY bar DESC LIMIT 1",
                     (symbol, before_bar)).fetchone()
    return _call_out(r) if r else None


def open_calls(conn) -> list[dict]:
    ensure_schema(conn)
    return [_call_out(r) for r in conn.execute(
        "SELECT * FROM lab_outlook_calls WHERE status='open' AND side IS NOT NULL ORDER BY symbol, bar")]


def later_calls(conn, symbol: str, after_bar: str) -> list[dict]:
    """Calls of a symbol after a bar (side + strategy position), oldest first: used to detect 'batal'."""
    return [dict(r) for r in conn.execute(
        "SELECT bar, bar_close, side, strategy, strategy_entry_time, price FROM lab_outlook_calls "
        "WHERE symbol=? AND bar>? ORDER BY bar", (symbol, after_bar))]


def set_outcome(conn, call_id: int, ev: dict, now: Optional[str] = None) -> None:
    now = now or utcnow()
    st = ev.get("status") or "open"
    conn.execute(
        "UPDATE lab_outlook_calls SET status=?, r_net=?, r_gross=?, mfe_r=?, mae_r=?, exit_price=?, bars_to_resolve=?, "
        "ambiguous=?, resolved_at=?, evaluated_at=? WHERE id=?",
        (st, ev.get("r_net"), ev.get("r_gross"), ev.get("mfe_r"), ev.get("mae_r"), ev.get("exit_price"),
         ev.get("bars"), 1 if ev.get("ambiguous") else 0, ev.get("resolved_at") if st in DONE else None, now,
         call_id))


def calls_for(conn, symbol: str, limit: int = 30) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute("SELECT * FROM lab_outlook_calls WHERE symbol=? AND side IS NOT NULL ORDER BY bar DESC LIMIT ?",
                        (symbol, int(limit))).fetchall()
    return [_call_out(r) for r in rows]


def _summ(rows: list[dict]) -> dict:
    done = [r for r in rows if r["status"] in DONE and r["r_net"] is not None]
    n = len(done)
    pos = {(r["symbol"], r["strategy"], r["strategy_entry_time"]) for r in done}
    out = {"n_calls": len(rows), "n_done": n, "n_open": sum(1 for r in rows if r["status"] == "open"),
           "n_pos": len(pos)}
    if n:
        out.update({k: sum(1 for r in done if r["status"] == k) / n for k in ("tp", "sl", "batal", "expired")})
        out["mean_r"] = sum(r["r_net"] for r in done) / n
        out["win_rate"] = sum(1 for r in done if r["r_net"] > 0) / n
    return out


def track_record(conn, since: Optional[str] = None, limit: int = 100) -> dict:
    """Live track record of stored calls: by side x keyakinan, by keyakinan, and the latest calls."""
    ensure_schema(conn)
    q = ("SELECT symbol, side, keyakinan, status, r_net, strategy, strategy_entry_time FROM lab_outlook_calls "
         "WHERE side IS NOT NULL" + (" AND bar>=?" if since else "") + " ORDER BY bar")
    rows = [dict(r) for r in conn.execute(q, (since,) if since else ())]
    groups: dict[str, list] = {}
    for r in rows:
        for k in (f"{r['side']}|{r['keyakinan']}", f"*|{r['keyakinan']}", f"{r['side']}|*", "*|*"):
            groups.setdefault(k, []).append(r)
    recent = [_call_out(r) for r in conn.execute(
        "SELECT * FROM lab_outlook_calls WHERE side IS NOT NULL ORDER BY bar DESC, symbol LIMIT ?", (int(limit),))] \
        if limit else []
    first = conn.execute("SELECT MIN(bar) FROM lab_outlook_calls").fetchone()[0]
    return {"since": since or first, "first_call": first, "groups": {k: _summ(v) for k, v in groups.items()},
            "recent": recent}


# ── inputs the job reads from lab.db (stdlib) ────────────────────────────

def _pf(p: dict) -> float:
    v = (p.get("holdout") or {}).get("profit_factor")
    return v if isinstance(v, (int, float)) else -1.0


def _trades(p: dict) -> int:
    v = (p.get("holdout") or {}).get("trades")
    return int(v) if isinstance(v, (int, float)) else 0


def pick_preset(presets: list[dict], symbol: str, timeframe: str = TIMEFRAME) -> Optional[dict]:
    """v1 rule (kept for callers / tests): the coin's own Rosyade preset on ``timeframe``: best PASS
    (highest holdout PF), else the live reference, else the best non-PASS one."""
    cands = [p for p in presets if p["symbol"] == symbol and p["timeframe"] == timeframe
             and p["template_id"] == TEMPLATE_ID]
    if not cands:
        return None
    passing = sorted((p for p in cands if p.get("verdict") == "PASS"), key=lambda p: (_pf(p), p["id"]), reverse=True)
    if passing:
        return passing[0]
    live = [p for p in cands if p.get("live_reference")]
    if live:
        return live[0]
    return sorted(cands, key=lambda p: (p.get("verdict") is not None, _pf(p), p["id"]), reverse=True)[0]


def _params_key(template_id: str, timeframe: str, params: dict) -> str:
    return f"{template_id}|{timeframe}|{dumps(params)}"


def strategies_for(presets: list[dict], symbol: str, templates: Optional[set] = None,
                   default_params: Optional[dict] = None) -> list[dict]:
    """The strategies the Outlook runs for one coin, primary first.

    Primary = the best PASS preset of ANY template / timeframe (highest holdout PF, then more
    holdout trades, then newest). No PASS preset -> the coin's live reference, else the Rosyade
    4H template default (honest fallback: "belum diuji untuk koin ini").
    The rest (agreement panel) = other PASS presets, then the fallback strategy, then FAIL /
    untested presets, capped at MAX_STRATEGIES; identical parameter sets run once.
    """
    own = [p for p in presets if p["symbol"] == symbol and p["timeframe"] in TF_OK
           and (templates is None or p["template_id"] in templates)]
    passing = sorted((p for p in own if p.get("verdict") == "PASS"),
                     key=lambda p: (_pf(p), _trades(p), p["id"]), reverse=True)
    live = [p for p in own if p.get("live_reference")]
    rest = sorted((p for p in own if p.get("verdict") != "PASS" and not p.get("live_reference")),
                  key=lambda p: (p.get("verdict") == "FAIL", _pf(p), p["id"]), reverse=True)

    def desc(p: Optional[dict]) -> dict:
        if p is None:
            return {"kind": "default", "name": DEFAULT_NAME, "preset": None, "template_id": TEMPLATE_ID,
                    "timeframe": TIMEFRAME, "params": dict(default_params or {}), "costs": None}
        return {"kind": "preset", "name": p["name"], "preset": p, "template_id": p["template_id"],
                "timeframe": p["timeframe"], "params": p["params"], "costs": p.get("costs")}

    fallback = desc(live[0]) if live else desc(None)
    order = [desc(p) for p in passing[:MAX_PASS]] + [fallback] + [desc(p) for p in live[1:]] + [desc(p) for p in rest]
    out, seen = [], set()
    for d in order:
        k = _params_key(d["template_id"], d["timeframe"], d["params"]) if d["params"] else d["name"]
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
        if len(out) >= MAX_STRATEGIES:
            break
    for i, d in enumerate(out):
        d["primary"] = i == 0
    return out


def preset_brief(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    h = p.get("holdout") or {}
    return {"id": p["id"], "name": p["name"], "verdict": p.get("verdict"), "live_reference": p.get("live_reference"),
            "template_id": p.get("template_id"), "timeframe": p.get("timeframe"),
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


# ── open positions (paper accounts + live bot), read-only ────────────────

def paper_positions(conn) -> dict[str, list[dict]]:
    try:
        rows = conn.execute("SELECT p.symbol, p.side, p.entry_price, p.entry_time, p.account_id, a.name AS account "
                            "FROM paper_positions p LEFT JOIN paper_accounts a ON a.id=p.account_id "
                            "WHERE p.status='open'").fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append({"source": "paper", "side": r["side"], "entry_price": r["entry_price"],
                                                "entry_time": r["entry_time"], "account": r["account"]})
    return out


def live_positions(trading_db_path: Optional[str]) -> Optional[dict[str, list[dict]]]:
    """Open positions of the live bot (bmtm_trading.db opened read-only, query_only). None = unavailable."""
    from pathlib import Path
    if not trading_db_path or not Path(trading_db_path).exists():
        return None
    try:
        src = sqlite3.connect(f"file:{trading_db_path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return None
    try:
        src.execute("PRAGMA query_only=1")
        rows = src.execute("SELECT symbol, side, entry_price, created_at FROM positions WHERE status='open'").fetchall()
    except sqlite3.Error:
        return None
    finally:
        src.close()
    out: dict[str, list[dict]] = {}
    for sym, side, entry, created in rows:
        s = str(sym or "").replace("/", "").split(":")[0].upper()
        side = (side or "").lower()
        side = "long" if side in ("long", "buy") else "short" if side in ("short", "sell") else side
        out.setdefault(s, []).append({"source": "live", "side": side, "entry_price": entry, "entry_time": created})
    return out
