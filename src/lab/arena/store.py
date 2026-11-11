"""Arena equity snapshots in lab.db (created on demand, additive). Stdlib only."""
from __future__ import annotations

import threading
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS arena_equity_snapshots (
    account_id  INTEGER NOT NULL,                -- paper_accounts.id
    ts          TEXT    NOT NULL,                -- hour boundary (UTC) the snapshot belongs to
    balance     REAL    NOT NULL,                -- realised balance
    equity      REAL    NOT NULL,                -- balance + unrealised PnL net of fees/funding
    upnl        REAL    NOT NULL DEFAULT 0,
    n_open      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (account_id, ts)
);
"""

_lock = threading.Lock()


def has_schema(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arena_equity_snapshots'"
                        ).fetchone() is not None


def ensure_schema(conn) -> None:
    if has_schema(conn):
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


def snapshots(conn, account_ids: list[int], since: Optional[str] = None) -> dict[int, list[dict]]:
    """{account_id: [{ts, balance, equity}]} oldest first. Empty when the table does not exist yet
    (the API never creates it: read-only)."""
    out: dict[int, list[dict]] = {int(a): [] for a in account_ids}
    if not account_ids or not has_schema(conn):
        return out
    ph = ",".join("?" * len(account_ids))
    sql = f"SELECT account_id, ts, balance, equity FROM arena_equity_snapshots WHERE account_id IN ({ph})"
    args: list = list(account_ids)
    if since:
        sql += " AND ts >= ?"
        args.append(since)
    for r in conn.execute(sql + " ORDER BY account_id, ts", args):
        out[int(r["account_id"])].append({"ts": r["ts"], "balance": r["balance"], "equity": r["equity"]})
    return out
