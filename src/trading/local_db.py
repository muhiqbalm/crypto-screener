"""Local SQLite database adapter for BMTM Trading Module.

Provides LocalDatabaseClient that mirrors the PostgREST / Supabase query API:
  client.table("users").select(...).eq(...).execute()
  client.table("webhook_configs").insert(...).execute()
  client.table("exchange_credentials").update(...).execute()

Eliminates external cloud dependencies (Supabase) and runs 100% self-hosted
directly on the VPS with zero latency (< 0.1ms).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Default SQLite database path
DEFAULT_DB_PATH = os.environ.get(
    "TRADING_LOCAL_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bmtm_trading.db")
)


class LocalResponse:
    """Wrapper that mimics Supabase postgrest response."""
    def __init__(self, data: List[dict]):
        self.data = data


class LocalTableQuery:
    """Fluent query builder mirroring Supabase PostgREST interface."""

    def __init__(self, db_path: str, table_name: str):
        self.db_path = db_path
        self.table_name = table_name
        self._select_cols = "*"
        self._filters: list[tuple[str, str, Any]] = []
        self._order_col: Optional[str] = None
        self._order_desc: bool = False
        self._limit_n: Optional[int] = None
        self._action = "SELECT"
        self._insert_data: Optional[dict | list[dict]] = None
        self._update_data: Optional[dict] = None
        self._single: bool = False

    def select(self, columns: str = "*") -> "LocalTableQuery":
        self._action = "SELECT"
        self._select_cols = columns
        return self

    def single(self) -> "LocalTableQuery":
        self._single = True
        self._limit_n = 1
        return self

    def maybe_single(self) -> "LocalTableQuery":
        self._single = True
        self._limit_n = 1
        return self

    def insert(self, data: dict | list[dict]) -> "LocalTableQuery":
        self._action = "INSERT"
        self._insert_data = data
        return self

    def update(self, data: dict) -> "LocalTableQuery":
        self._action = "UPDATE"
        self._update_data = data
        return self

    def delete(self) -> "LocalTableQuery":
        self._action = "DELETE"
        return self

    def upsert(self, data: dict | list[dict], on_conflict: Optional[str] = None) -> "LocalTableQuery":
        self._action = "UPSERT"
        self._insert_data = data
        self._on_conflict = on_conflict
        return self

    def eq(self, column: str, value: Any) -> "LocalTableQuery":
        # Handle boolean conversion for SQLite
        if isinstance(value, bool):
            value = 1 if value else 0
        self._filters.append((column, "=", value))
        return self

    def neq(self, column: str, value: Any) -> "LocalTableQuery":
        if isinstance(value, bool):
            value = 1 if value else 0
        self._filters.append((column, "!=", value))
        return self

    def limit(self, count: int) -> "LocalTableQuery":
        self._limit_n = count
        return self

    def order(self, column: str, desc: bool = False) -> "LocalTableQuery":
        self._order_col = column
        self._order_desc = desc
        return self

    def execute(self) -> LocalResponse:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            if self._action == "INSERT":
                return self._execute_insert(conn, cursor)
            elif self._action == "UPSERT":
                return self._execute_upsert(conn, cursor)
            elif self._action == "UPDATE":
                return self._execute_update(conn, cursor)
            elif self._action == "DELETE":
                return self._execute_delete(conn, cursor)
            else:
                return self._execute_select(cursor)
        finally:
            conn.close()

    def _execute_upsert(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> LocalResponse:
        items = self._insert_data
        if isinstance(items, dict):
            items = [items]

        inserted_rows = []
        for item in items:
            row = dict(item)
            if "id" not in row or not row["id"]:
                row["id"] = str(uuid.uuid4())
            if "created_at" not in row or not row["created_at"]:
                row["created_at"] = datetime.now(timezone.utc).isoformat()

            for k, v in row.items():
                if isinstance(v, bool):
                    row[k] = 1 if v else 0

            columns = list(row.keys())
            placeholders = ["?"] * len(columns)
            values = [row[c] for c in columns]

            if getattr(self, "_on_conflict", None):
                conflict_cols = [c.strip() for c in self._on_conflict.split(",")]
                update_cols = [c for c in columns if c not in conflict_cols and c not in ("id", "created_at")]
                if update_cols:
                    update_assignments = [f"{c} = excluded.{c}" for c in update_cols]
                    sql = (
                        f"INSERT INTO {self.table_name} ({', '.join(columns)}) "
                        f"VALUES ({', '.join(placeholders)}) "
                        f"ON CONFLICT({', '.join(conflict_cols)}) DO UPDATE SET {', '.join(update_assignments)}"
                    )
                else:
                    sql = (
                        f"INSERT INTO {self.table_name} ({', '.join(columns)}) "
                        f"VALUES ({', '.join(placeholders)}) "
                        f"ON CONFLICT({', '.join(conflict_cols)}) DO NOTHING"
                    )
            else:
                sql = f"INSERT OR REPLACE INTO {self.table_name} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"

            cursor.execute(sql, values)
            inserted_rows.append(row)

        conn.commit()
        return LocalResponse(inserted_rows)

    def _execute_select(self, cursor: sqlite3.Cursor) -> LocalResponse:
        where_clause, params = self._build_where()
        
        # Clean select columns (remove spaces, handle *)
        cols = self._select_cols.strip()
        if not cols:
            cols = "*"

        query = f"SELECT {cols} FROM {self.table_name}"
        if where_clause:
            query += f" WHERE {where_clause}"
        if self._order_col:
            direction = "DESC" if self._order_desc else "ASC"
            query += f" ORDER BY {self._order_col} {direction}"
        if self._limit_n is not None:
            query += f" LIMIT {self._limit_n}"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        result = [self._row_to_dict(r) for r in rows]
        if self._single:
            if not result:
                raise Exception("PGRST116: JSON object requested, multiple (or no) rows returned")
            return LocalResponse(result[0])
        return LocalResponse(result)

    def _execute_insert(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> LocalResponse:
        items = self._insert_data
        if isinstance(items, dict):
            items = [items]

        inserted_rows = []
        for item in items:
            row = dict(item)
            if "id" not in row or not row["id"]:
                row["id"] = str(uuid.uuid4())
            if "created_at" not in row or not row["created_at"]:
                row["created_at"] = datetime.now(timezone.utc).isoformat()
            
            # Convert booleans to int for SQLite
            for k, v in row.items():
                if isinstance(v, bool):
                    row[k] = 1 if v else 0

            columns = list(row.keys())
            placeholders = ["?"] * len(columns)
            values = [row[c] for c in columns]

            sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            cursor.execute(sql, values)
            inserted_rows.append(row)

        conn.commit()
        return LocalResponse(inserted_rows)

    def _execute_update(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> LocalResponse:
        patch = dict(self._update_data or {})
        for k, v in patch.items():
            if isinstance(v, bool):
                patch[k] = 1 if v else 0

        set_clauses = [f"{col} = ?" for col in patch.keys()]
        params = list(patch.values())

        where_clause, where_params = self._build_where()
        params.extend(where_params)

        sql = f"UPDATE {self.table_name} SET {', '.join(set_clauses)}"
        if where_clause:
            sql += f" WHERE {where_clause}"

        cursor.execute(sql, params)
        conn.commit()

        # Fetch updated rows
        select_query = f"SELECT * FROM {self.table_name}"
        if where_clause:
            select_query += f" WHERE {where_clause}"
        cursor.execute(select_query, where_params)
        rows = cursor.fetchall()
        return LocalResponse([self._row_to_dict(r) for r in rows])

    def _execute_delete(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> LocalResponse:
        where_clause, params = self._build_where()
        sql = f"DELETE FROM {self.table_name}"
        if where_clause:
            sql += f" WHERE {where_clause}"

        cursor.execute(sql, params)
        conn.commit()
        return LocalResponse([])

    def _build_where(self) -> tuple[str, list[Any]]:
        if not self._filters:
            return "", []
        clauses = []
        params = []
        for col, op, val in self._filters:
            clauses.append(f"{col} {op} ?")
            params.append(val)
        return " AND ".join(clauses), params

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        # Convert integer booleans back for known columns
        for bool_col in ("is_active", "testnet_enabled"):
            if bool_col in d and d[bool_col] is not None:
                d[bool_col] = bool(d[bool_col])
        return d


class LocalDatabaseClient:
    """Local SQLite Client matching the Supabase-py client interface."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_tables()

    def table(self, table_name: str) -> LocalTableQuery:
        return LocalTableQuery(self.db_path, table_name)

    def _init_tables(self):
        """Create tables if they don't exist."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        cursor = conn.cursor()

        # 1. users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                name TEXT,
                password_hash TEXT,
                telegram_chat_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
        """)

        # 2. webhook_configs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_configs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                passphrase TEXT NOT NULL UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
        """)

        # 3. exchange_credentials
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exchange_credentials (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                secret_encrypted TEXT NOT NULL,
                passphrase_encrypted TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (user_id, exchange)
            );
        """)

        # 4. positions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL,
                entry_price REAL,
                status TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'binance',
                created_at TEXT NOT NULL,
                closed_at TEXT
            );
        """)

        # 5. trade_logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                side TEXT NOT NULL,
                exchange TEXT NOT NULL,
                size_value REAL,
                status TEXT NOT NULL,
                order_id TEXT,
                fill_price REAL,
                filled_quantity REAL,
                created_at TEXT NOT NULL
            );
        """)

        # 6. user_tokens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        conn.commit()
        conn.close()
        logger.info(f"Local SQLite database initialized at {self.db_path}")
