"""In-web notifications for Lab admins (stdlib, lab.db). No Telegram, no e-mail.

``notify()`` is the one entry point the Lab code calls when something happens
(job finished / failed, paper preset opened / closed a position, Signal Ledger
verdict changed, deploy recorded). It never raises: a failing notification must
never break the job, order fill or ledger cycle that triggered it.

Abuse limits:
  * ``dedupe_key`` is UNIQUE: the same event is stored once (INSERT OR IGNORE);
  * at most ``MAX_PER_TYPE_PER_HOUR`` notifications of one type per rolling hour
    (anything above is dropped and logged, the source data stays in its own page);
  * rows older than ``RETENTION_DAYS`` are pruned now and then.

Read state is per admin user (JWT ``sub``): a watermark ("everything up to id N is
read", set by "tandai semua sudah dibaca") plus single reads above it.

Sticky notifications (``notify(..., sticky=True)``, audit 2026-11-13 K1: a rejected live
order nobody was asked to look at) stay unread and pinned for EVERY admin until one admin
acknowledges them ("Sudah dicek", ``ack``): "tandai semua sudah dibaca" does not clear them
and the retention prune keeps them. The ack is shared (who + when are stored).
Tables are self-contained (CREATE IF NOT EXISTS), like the ledger / presets.
"""
from __future__ import annotations

import logging
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import utcnow

log = logging.getLogger("lab.notify")

TYPES = ("job", "paper", "ledger", "deploy", "report", "live")
MAX_PER_TYPE_PER_HOUR = 30
RETENTION_DAYS = 90
TITLE_MAX, BODY_MAX = 160, 600

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,                 -- job | paper | ledger | deploy | report
    title       TEXT NOT NULL,
    body        TEXT,
    link        TEXT,                          -- in-app path, e.g. /lab/runs/12
    dedupe_key  TEXT UNIQUE,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications (id DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications (type, created_at);

CREATE TABLE IF NOT EXISTS notification_reads (
    notification_id INTEGER NOT NULL,
    user_key        TEXT NOT NULL,
    read_at         TEXT NOT NULL,
    PRIMARY KEY (notification_id, user_key)
);

-- "read everything up to and including read_upto_id" per user
CREATE TABLE IF NOT EXISTS notification_user_state (
    user_key     TEXT PRIMARY KEY,
    read_upto_id INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);

-- sticky notifications: unread for everyone until one admin acknowledges (acked_at set)
CREATE TABLE IF NOT EXISTS notification_sticky (
    notification_id INTEGER PRIMARY KEY,
    acked_at        TEXT,
    acked_by        TEXT
);
"""
TABLES = ("notifications", "notification_reads", "notification_user_state", "notification_sticky")
PINNED_MAX = 20

_lock = threading.Lock()


def ensure_schema(conn: sqlite3.Connection) -> None:
    have = conn.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        f"({','.join('?' * len(TABLES))})", TABLES).fetchone()[0]
    if have == len(TABLES):
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def notify(conn: sqlite3.Connection, type: str, title: str, body: Optional[str] = None,  # noqa: A002
           link: Optional[str] = None, dedupe_key: Optional[str] = None, sticky: bool = False) -> Optional[int]:
    """Store one notification. Returns its id, or None (duplicate, rate-limited, error). Never raises.

    ``sticky``: stays unread and pinned for every admin until acknowledged (``ack``).
    Commits its own write; call it after the caller's own commit."""
    try:
        ensure_schema(conn)
        if conn.in_transaction:          # never fold the caller's pending writes into ours
            conn.commit()
        if type not in TYPES:
            type = "job" if type is None else str(type)[:16]  # noqa: A001
        now = datetime.now(timezone.utc)
        n = conn.execute("SELECT COUNT(*) FROM notifications WHERE type=? AND created_at >= ?",
                         (type, _iso(now - timedelta(hours=1)))).fetchone()[0]
        if n >= MAX_PER_TYPE_PER_HOUR:
            log.warning("notify: %s rate limit reached, dropped %r", type, title[:80])
            return None
        cur = conn.execute(
            "INSERT OR IGNORE INTO notifications (type, title, body, link, dedupe_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (type, (title or "")[:TITLE_MAX], (body or None) and body[:BODY_MAX],
             link if (link or "").startswith("/") else None, dedupe_key, utcnow()))
        new_id = int(cur.lastrowid) if cur.rowcount else None
        if new_id and sticky:
            conn.execute("INSERT OR IGNORE INTO notification_sticky (notification_id) VALUES (?)", (new_id,))
        if random.random() < 0.02:
            prune(conn, now)
        conn.commit()
        return new_id
    except Exception:  # noqa: BLE001
        log.exception("notify failed (%s: %s)", type, (title or "")[:80])
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


_OPEN_STICKY = "SELECT notification_id FROM notification_sticky WHERE acked_at IS NULL"


def prune(conn: sqlite3.Connection, now: Optional[datetime] = None) -> None:
    """Drop rows older than RETENTION_DAYS, except sticky ones nobody has acknowledged yet."""
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS))
    old = f"SELECT id FROM notifications WHERE created_at < ? AND id NOT IN ({_OPEN_STICKY})"
    conn.execute(f"DELETE FROM notification_reads WHERE notification_id IN ({old})", (cutoff,))
    conn.execute(f"DELETE FROM notification_sticky WHERE notification_id IN ({old})", (cutoff,))
    conn.execute(f"DELETE FROM notifications WHERE id IN ({old})", (cutoff,))


# ── read side (API) ───────────────────────────────────────────────────────

def _watermark(conn, user_key: str) -> int:
    r = conn.execute("SELECT read_upto_id FROM notification_user_state WHERE user_key=?", (user_key,)).fetchone()
    return int(r[0]) if r else 0


_STICKY_OPEN_SQL = ("EXISTS (SELECT 1 FROM notification_sticky s WHERE s.notification_id = n.id "
                    "AND s.acked_at IS NULL)")
# unread = above the watermark and not read one by one, OR sticky and not acknowledged yet
_UNREAD_SQL = ("((n.id > ? AND NOT EXISTS (SELECT 1 FROM notification_reads r "
               f"WHERE r.notification_id = n.id AND r.user_key = ?)) OR {_STICKY_OPEN_SQL})")


def unread_count(conn, user_key: str) -> int:
    ensure_schema(conn)
    wm = _watermark(conn, user_key)
    return int(conn.execute(f"SELECT COUNT(*) FROM notifications n WHERE {_UNREAD_SQL}",
                            (wm, user_key)).fetchone()[0])


def list_for(conn, user_key: str, limit: int = 30, unread_only: bool = False,
             before_id: Optional[int] = None) -> dict:
    ensure_schema(conn)
    wm = _watermark(conn, user_key)
    where, args = ["1=1"], []
    if unread_only:
        where.append(_UNREAD_SQL)
        args += [wm, user_key]
    if before_id:
        where.append("n.id < ?")
        args.append(int(before_id))
    rows = conn.execute(
        f"{_ITEM_SQL} WHERE {' AND '.join(where)} ORDER BY n.id DESC LIMIT ?",
        [wm, user_key, *args, int(limit)]).fetchall()
    pinned = conn.execute(f"{_ITEM_SQL} WHERE {_STICKY_OPEN_SQL} ORDER BY n.id DESC LIMIT ?",
                          [wm, user_key, PINNED_MAX]).fetchall()
    return {"items": [_item(r) for r in rows], "pinned": [_item(r) for r in pinned],
            "unread": unread_count(conn, user_key)}


_ITEM_SQL = (
    "SELECT n.id, n.type, n.title, n.body, n.link, n.created_at, "
    "(n.id <= ? OR EXISTS (SELECT 1 FROM notification_reads r WHERE r.notification_id = n.id "
    "AND r.user_key = ?)) AS is_read, s.notification_id AS sticky_id, s.acked_at "
    "FROM notifications n LEFT JOIN notification_sticky s ON s.notification_id = n.id")


def _item(r) -> dict:
    sticky = r["sticky_id"] is not None
    open_sticky = sticky and r["acked_at"] is None
    return {"id": r["id"], "type": r["type"], "title": r["title"], "body": r["body"], "link": r["link"],
            "created_at": r["created_at"], "read": bool(r["is_read"]) and not open_sticky,
            "sticky": sticky, "acked_at": r["acked_at"]}


def mark_read(conn, user_key: str, notification_id: int) -> bool:
    ensure_schema(conn)
    if not conn.execute("SELECT 1 FROM notifications WHERE id=?", (notification_id,)).fetchone():
        return False
    conn.execute("INSERT OR IGNORE INTO notification_reads (notification_id, user_key, read_at) VALUES (?, ?, ?)",
                 (notification_id, user_key, utcnow()))
    conn.commit()
    return True


def ack(conn, user_key: str, notification_id: int) -> bool:
    """Acknowledge a notification for everyone ("Sudah dicek") and mark it read for this admin.
    Non-sticky ids are just marked read. False when the id does not exist. Idempotent."""
    ensure_schema(conn)
    if not conn.execute("SELECT 1 FROM notifications WHERE id=?", (notification_id,)).fetchone():
        return False
    conn.execute("UPDATE notification_sticky SET acked_at=?, acked_by=? WHERE notification_id=? AND acked_at IS NULL",
                 (utcnow(), user_key[:120], notification_id))
    conn.execute("INSERT OR IGNORE INTO notification_reads (notification_id, user_key, read_at) VALUES (?, ?, ?)",
                 (notification_id, user_key, utcnow()))
    conn.commit()
    return True


def mark_all_read(conn, user_key: str) -> int:
    ensure_schema(conn)
    top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]
    conn.execute(
        "INSERT INTO notification_user_state (user_key, read_upto_id, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(user_key) DO UPDATE SET read_upto_id=MAX(read_upto_id, excluded.read_upto_id), "
        "updated_at=excluded.updated_at", (user_key, int(top), utcnow()))
    conn.execute("DELETE FROM notification_reads WHERE user_key=? AND notification_id <= ?", (user_key, int(top)))
    conn.commit()
    return int(top)
