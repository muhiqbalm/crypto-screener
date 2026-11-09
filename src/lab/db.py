"""lab.db access (stdlib sqlite3, WAL). Never touches bmtm_trading.db."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .settings import get_lab_settings

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_init_lock = threading.Lock()
_initialised: set[str] = set()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _default(o: Any) -> Any:
    item = getattr(o, "item", None)  # numpy scalars
    if callable(item):
        try:
            return _sanitize(item())
        except Exception:
            pass
    iso = getattr(o, "isoformat", None)
    if callable(iso):
        return iso()
    return str(o)


def dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(_sanitize(obj), default=_default)


def loads(s: Optional[str], default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def _sanitize(obj: Any) -> Any:
    """Replace NaN/inf with None so the JSON is strict (browsers reject NaN)."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def connect(db_path: Optional[str] = None, readonly: bool = False) -> sqlite3.Connection:
    path = db_path or get_lab_settings().db_path
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=15.0)
        init_db(conn, path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection, path: str) -> None:
    with _init_lock:
        if path in _initialised and path != ":memory:":
            return
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        _initialised.add(path)


@contextmanager
def session(db_path: Optional[str] = None, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path, readonly=readonly)
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None
