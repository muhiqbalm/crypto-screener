"""The API's per-request lab.db connection must survive FastAPI's thread hops.

A sync dependency (src.api.lab_routes._conn) and the sync endpoint that uses it can run on
different threadpool threads. With sqlite's default same-thread check this raised
"SQLite objects created in a thread can only be used in that same thread" on
/api/v1/lab/ledger/signals.
"""
import threading

from src.api.lab_routes import _conn


def _use_in_other_thread(conn) -> list:
    out: list = []

    def work():
        try:
            out.append(conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0])
        except Exception as e:  # noqa: BLE001
            out.append(e)

    t = threading.Thread(target=work)
    t.start()
    t.join()
    return out


def test_request_connection_is_usable_from_another_thread(lab_env):
    gen = _conn()
    conn = next(gen)              # "dependency thread"
    try:
        out = _use_in_other_thread(conn)   # "endpoint thread"
        assert len(out) == 1 and not isinstance(out[0], Exception), out
        assert out[0] >= 1        # lab schema exists
    finally:
        gen.close()               # teardown closes the connection


def test_default_connect_keeps_the_same_thread_check(lab_env):
    from src.lab import db
    conn = db.connect()
    try:
        out = _use_in_other_thread(conn)
        assert len(out) == 1 and isinstance(out[0], Exception)
    finally:
        conn.close()
