"""Named strategy presets: template + symbol + timeframe + params + costs.

One strategy family (a template) needs a different parameter set per coin and
timeframe; a preset is one such set, named ``{TF}-{COIN}-{Label}``
(``4H-ETH-Basic``, ``1H-BTC-Opt1``). ``4H-ETH-Basic`` is seeded from the
template defaults (= the live ETH 4H strategy) and is read-only.

A preset saved from a run snapshots the run's verdict, holdout metrics and how
often that template+symbol had been tried at save time (data-snooping), so the
preset never looks better than the evidence it came from.

Tables are self-contained (CREATE IF NOT EXISTS, like the ledger) and never
alter lab_runs / watches: provenance lives in lab_preset_links.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Optional

from . import db as labdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_presets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,                 -- {TF}-{COIN}-{Label}
    label          TEXT NOT NULL,
    template_id    TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    params_json    TEXT NOT NULL,
    costs_json     TEXT NOT NULL,
    notes          TEXT,
    readonly       INTEGER NOT NULL DEFAULT 0,
    live_reference INTEGER NOT NULL DEFAULT 0,    -- 1 = mirrors the live strategy
    source_run_id  INTEGER,
    source_mode    TEXT,
    verdict        TEXT,                          -- of the source run, at save time
    holdout_json   TEXT,
    snooping_json  TEXT,
    archived       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lab_presets_name ON lab_presets (name) WHERE archived = 0;
CREATE INDEX IF NOT EXISTS idx_lab_presets_combo ON lab_presets (template_id, symbol, timeframe);

-- Which run / watch was started from which preset (kind = run | watch).
CREATE TABLE IF NOT EXISTS lab_preset_links (
    kind       TEXT NOT NULL,
    ref_id     INTEGER NOT NULL,
    preset_id  INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_lab_preset_links_preset ON lab_preset_links (preset_id);

-- The read-only live reference cannot be edited or archived.
CREATE TRIGGER IF NOT EXISTS lab_presets_readonly
BEFORE UPDATE ON lab_presets
WHEN OLD.readonly = 1
BEGIN
    SELECT RAISE(ABORT, 'preset is read-only');
END;
CREATE TRIGGER IF NOT EXISTS lab_presets_no_delete_readonly
BEFORE DELETE ON lab_presets
WHEN OLD.readonly = 1
BEGIN
    SELECT RAISE(ABORT, 'preset is read-only');
END;
"""

LIVE_NAME = "4H-ETH-Basic"
LIVE_TEMPLATE = "rosyade_family"
LIVE_SYMBOL = "ETHUSDT"
LIVE_TF = "4h"
DEFAULT_COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.]{0,23}$")

_lock = threading.Lock()


class PresetError(ValueError):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def ensure_schema(conn: sqlite3.Connection) -> None:
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('lab_presets','lab_preset_links')").fetchone()[0]
    if have == 2:
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


def coin(symbol: str) -> str:
    s = symbol.upper()
    return s[:-4] if s.endswith("USDT") else s


def make_name(timeframe: str, symbol: str, label: str) -> str:
    return f"{timeframe.upper()}-{coin(symbol)}-{label}"


def check_label(label: str) -> str:
    label = (label or "").strip()
    if not LABEL_RE.match(label):
        raise PresetError("label: 1-24 karakter huruf/angka/_/. tanpa spasi (mis. Opt1, Basic)")
    return label


def seed(conn: sqlite3.Connection) -> None:
    """Insert the read-only live reference 4H-ETH-Basic once (template defaults)."""
    ensure_schema(conn)
    if conn.execute("SELECT 1 FROM lab_presets WHERE live_reference=1 AND name=?", (LIVE_NAME,)).fetchone():
        return
    from .templates import get_template
    t = get_template(LIVE_TEMPLATE)
    if t is None:
        return
    with _lock:
        if conn.execute("SELECT 1 FROM lab_presets WHERE name=? AND archived=0", (LIVE_NAME,)).fetchone():
            return
        conn.execute(
            "INSERT INTO lab_presets (name, label, template_id, symbol, timeframe, params_json, costs_json, notes, "
            "readonly, live_reference, created_at) VALUES (?, 'Basic', ?, ?, ?, ?, ?, ?, 1, 1, ?)",
            (LIVE_NAME, LIVE_TEMPLATE, LIVE_SYMBOL, LIVE_TF, labdb.dumps(t.defaults()), labdb.dumps(DEFAULT_COSTS),
             "Setting live strategi ETH 4H (default template). Referensi, tidak bisa diubah. "
             "Hanya berlaku untuk ETH 4H: koin/timeframe lain butuh preset sendiri.", labdb.utcnow()))
        conn.commit()


def preset_out(r, links: Optional[dict] = None) -> dict:
    return {
        "id": r["id"], "name": r["name"], "label": r["label"], "template_id": r["template_id"],
        "symbol": r["symbol"], "timeframe": r["timeframe"], "params": labdb.loads(r["params_json"], {}),
        "costs": labdb.loads(r["costs_json"], {}), "notes": r["notes"], "readonly": bool(r["readonly"]),
        "live_reference": bool(r["live_reference"]), "source_run_id": r["source_run_id"],
        "source_mode": r["source_mode"], "verdict": r["verdict"], "holdout": labdb.loads(r["holdout_json"]),
        "snooping": labdb.loads(r["snooping_json"]), "created_at": r["created_at"],
        "usage": links or {"runs": 0, "watches": 0},
    }


def _usage(conn) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT preset_id, kind, COUNT(*) AS n FROM lab_preset_links GROUP BY 1, 2"):
        out.setdefault(r["preset_id"], {"runs": 0, "watches": 0})["runs" if r["kind"] == "run" else "watches"] = r["n"]
    return out


def list_presets(conn, template_id: Optional[str] = None, symbol: Optional[str] = None,
                 timeframe: Optional[str] = None) -> list[dict]:
    seed(conn)
    sql, args = "SELECT * FROM lab_presets WHERE archived=0", []
    for col, v in (("template_id", template_id), ("symbol", symbol), ("timeframe", timeframe)):
        if v:
            sql += f" AND {col}=?"
            args.append(v)
    use = _usage(conn)
    rows = conn.execute(sql + " ORDER BY live_reference DESC, symbol, timeframe, id", args).fetchall()
    return [preset_out(r, use.get(r["id"])) for r in rows]


def get(conn, preset_id: int) -> dict:
    seed(conn)
    r = conn.execute("SELECT * FROM lab_presets WHERE id=? AND archived=0", (preset_id,)).fetchone()
    if r is None:
        raise PresetError("preset not found", 404)
    return preset_out(r, _usage(conn).get(r["id"]))


def _holdout_summary(oos: dict) -> dict:
    c = oos.get("costs") or {}
    keys = ("net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades", "win_rate_pct",
            "stress_net_return_pct")
    return {**{k: oos.get(k) for k in keys}, "cost_drag_pct": c.get("cost_drag_pct"),
            "start": oos.get("start"), "end": oos.get("end")}


def snooping_at(conn, template_id: str, symbol: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT timeframe) AS tfs, COALESCE(SUM(trials_done), 0) AS trials "
        "FROM lab_runs WHERE template_id=? AND symbol=? AND mode IN ('validate','optimize') "
        "AND status NOT IN ('cancelled','error')", (template_id, symbol)).fetchone()
    t = conn.execute("SELECT COALESCE(SUM(touches), 0) FROM holdout_locks WHERE template_id=? AND symbol=?",
                     (template_id, symbol)).fetchone()[0]
    return {"runs": int(row["n"] or 0), "timeframes": int(row["tfs"] or 0), "trials": int(row["trials"] or 0),
            "holdout_touches": int(t or 0)}


def _insert(conn, *, label: str, template_id: str, symbol: str, timeframe: str, params: dict, costs: dict,
            notes: Optional[str], source_run_id=None, source_mode=None, verdict=None, holdout=None,
            snooping=None) -> int:
    seed(conn)
    name = make_name(timeframe, symbol, check_label(label))
    if conn.execute("SELECT 1 FROM lab_presets WHERE name=? AND archived=0", (name,)).fetchone():
        raise PresetError(f"preset {name} sudah ada; pakai label lain", 409)
    pid = conn.execute(
        "INSERT INTO lab_presets (name, label, template_id, symbol, timeframe, params_json, costs_json, notes, "
        "source_run_id, source_mode, verdict, holdout_json, snooping_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, label.strip(), template_id, symbol, timeframe, labdb.dumps(params), labdb.dumps(costs),
         (notes or None) and notes[:2000], source_run_id, source_mode, verdict, labdb.dumps(holdout),
         labdb.dumps(snooping), labdb.utcnow())).lastrowid
    conn.commit()
    return int(pid)


def create_from_run(conn, run_id: int, label: str, notes: Optional[str] = None) -> dict:
    r = conn.execute("SELECT * FROM lab_runs WHERE id=?", (run_id,)).fetchone()
    if r is None:
        raise PresetError("run not found", 404)
    if r["status"] != "done":
        raise PresetError("hanya run yang selesai bisa disimpan sebagai preset", 409)
    if r["template_id"] == "universal_v0":
        raise PresetError("run Universal bukan strategi satu koin; tidak bisa jadi preset", 422)
    params = labdb.loads(r["best_params_json"]) if r["mode"] == "optimize" else None
    params = params or labdb.loads(r["params_json"], {})
    oos = labdb.loads(r["oos_metrics_json"])
    pid = _insert(conn, label=label, template_id=r["template_id"], symbol=r["symbol"], timeframe=r["timeframe"],
                  params=params, costs=labdb.loads(r["costs_json"], {}) or dict(DEFAULT_COSTS), notes=notes,
                  source_run_id=run_id, source_mode=r["mode"], verdict=r["verdict"],
                  holdout=_holdout_summary(oos) if oos else None,
                  snooping=snooping_at(conn, r["template_id"], r["symbol"]))
    return get(conn, pid)


def create(conn, *, label: str, template_id: str, symbol: str, timeframe: str, params: dict, costs: dict,
           notes: Optional[str] = None) -> dict:
    """Manual preset (no evidence attached: verdict/holdout stay empty)."""
    pid = _insert(conn, label=label, template_id=template_id, symbol=symbol, timeframe=timeframe, params=params,
                  costs=costs, notes=notes)
    return get(conn, pid)


def update(conn, preset_id: int, notes: Optional[str] = None, label: Optional[str] = None) -> dict:
    p = get(conn, preset_id)
    if p["readonly"]:
        raise PresetError("preset referensi live tidak bisa diubah", 403)
    sets, args = [], []
    if label is not None:
        label = check_label(label)
        name = make_name(p["timeframe"], p["symbol"], label)
        if name != p["name"] and conn.execute(
                "SELECT 1 FROM lab_presets WHERE name=? AND archived=0", (name,)).fetchone():
            raise PresetError(f"preset {name} sudah ada", 409)
        sets += ["label=?", "name=?"]
        args += [label, name]
    if notes is not None:
        sets.append("notes=?")
        args.append(notes[:2000] or None)
    if sets:
        conn.execute(f"UPDATE lab_presets SET {', '.join(sets)} WHERE id=?", [*args, preset_id])
        conn.commit()
    return get(conn, preset_id)


def archive(conn, preset_id: int) -> None:
    p = get(conn, preset_id)
    if p["readonly"]:
        raise PresetError("preset referensi live tidak bisa dihapus", 403)
    conn.execute("UPDATE lab_presets SET archived=1 WHERE id=?", (preset_id,))
    conn.commit()


def link(conn, kind: str, ref_id: int, preset_id: int) -> None:
    ensure_schema(conn)
    conn.execute("INSERT OR REPLACE INTO lab_preset_links (kind, ref_id, preset_id, created_at) VALUES (?, ?, ?, ?)",
                 (kind, ref_id, preset_id, labdb.utcnow()))


def params_match(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    for k in keys:
        x, y = a.get(k), b.get(k)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            if abs(float(x) - float(y)) > 1e-9:
                return False
        elif x != y:
            return False
    return True


def names_for_runs(conn, run_ids: list[int]) -> dict[int, dict]:
    """{run_id: {"preset": {id,name}|None, "saved_as": [names]}} for leaderboard / compare."""
    ensure_schema(conn)
    if not run_ids:
        return {}
    ph = ",".join("?" * len(run_ids))
    out: dict[int, dict] = {int(r): {"preset": None, "saved_as": []} for r in run_ids}
    for r in conn.execute(
            f"SELECT l.ref_id, p.id, p.name FROM lab_preset_links l JOIN lab_presets p ON p.id=l.preset_id "
            f"WHERE l.kind='run' AND l.ref_id IN ({ph})", run_ids):
        out[r["ref_id"]]["preset"] = {"id": r["id"], "name": r["name"]}
    for r in conn.execute(
            f"SELECT source_run_id, name FROM lab_presets WHERE archived=0 AND source_run_id IN ({ph}) "
            "ORDER BY id", run_ids):
        out[r["source_run_id"]]["saved_as"].append(r["name"])
    return out


def _score(p: dict) -> tuple:
    h = p.get("holdout") or {}
    pf = h.get("profit_factor")
    return (1 if p["verdict"] == "PASS" else 0, pf if isinstance(pf, (int, float)) else -1.0, p["id"])


def best_for(conn, template_id: str, symbols: list[str], timeframes: list[str]) -> dict[str, Optional[dict]]:
    """Best preset per "SYMBOL|tf": a PASS preset with the highest holdout PF; else the
    live reference for that combo; else none (the cell then uses the scan's params).
    A FAIL preset is never chosen automatically."""
    presets = [p for p in list_presets(conn, template_id=template_id)
               if p["symbol"] in symbols and p["timeframe"] in timeframes]
    out: dict[str, Optional[dict]] = {}
    for s in symbols:
        for tf in timeframes:
            cands = [p for p in presets if p["symbol"] == s and p["timeframe"] == tf]
            passing = sorted((p for p in cands if p["verdict"] == "PASS"), key=_score, reverse=True)
            live = [p for p in cands if p["live_reference"]]
            pick = passing[0] if passing else (live[0] if live else None)
            out[f"{s}|{tf}"] = pick and {"id": pick["id"], "name": pick["name"], "verdict": pick["verdict"],
                                         "live_reference": pick["live_reference"], "params": pick["params"],
                                         "holdout": pick["holdout"]}
    return out

