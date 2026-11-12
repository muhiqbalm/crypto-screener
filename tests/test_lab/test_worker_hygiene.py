"""Audit 2026-11-13: P2 (Telegram token in the worker log) and P6 (paper double close).

No network: the HTTP transport is a mock and the token is a fake.
"""
import io
import logging

import httpx
import pytest

from src.lab import db as labdb
from src.lab import paper, watch_eval
from src.lab import worker as worker_module
from src.lab.settings import get_lab_settings
from src.lab.universal import alerts

FAKE_TOKEN = "123456:FAKE-TOKEN-FOR-TESTS"


# ── P2 ────────────────────────────────────────────────────────────────────

@pytest.fixture
def worker_log(monkeypatch):
    """The worker's log format on a buffer, with httpx/httpcore as chatty as they get."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    old_level = root.level
    old = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    for n in old:
        logging.getLogger(n).setLevel(logging.DEBUG)
    yield buf
    root.removeHandler(handler)
    root.setLevel(old_level)
    for n, level in old.items():
        logging.getLogger(n).setLevel(level)


def _mock_telegram(monkeypatch, status=200):
    seen = []
    real_init = httpx.AsyncClient.__init__

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, json={"ok": status == 200, "description": "x"})

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    return seen


def _settings(lab_env, monkeypatch):
    monkeypatch.setenv("LAB_TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    from dataclasses import replace
    return replace(get_lab_settings(), telegram_bot_token=FAKE_TOKEN, telegram_chat_id="1")


@pytest.mark.parametrize("status", [200, 401])
def test_lab_telegram_send_never_logs_the_token(lab_env, monkeypatch, worker_log, status):
    seen = _mock_telegram(monkeypatch, status)

    alerts.default_sender(_settings(lab_env, monkeypatch))("hello")

    assert seen and FAKE_TOKEN in seen[0]  # the request really went out with the token
    assert FAKE_TOKEN not in worker_log.getvalue()
    assert "api.telegram.org" not in worker_log.getvalue()


def test_worker_main_quiets_http_loggers_before_running(lab_env, monkeypatch):
    for n in ("httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(n), "level", logging.NOTSET)
    levels = {}

    def run_forever(self, hooks=None):
        levels.update({n: logging.getLogger(n).getEffectiveLevel() for n in ("httpx", "httpcore")})

    monkeypatch.setattr(worker_module.Worker, "run_forever", run_forever)
    monkeypatch.setattr(worker_module.signal, "signal", lambda *a: None)
    monkeypatch.setattr(logging, "basicConfig", lambda **k: None)

    worker_module.main()

    assert levels == {"httpx": logging.WARNING, "httpcore": logging.WARNING}


# ── P6 ────────────────────────────────────────────────────────────────────

class CloseInBetween:
    """Connection A; right after A has read the open position, process B closes it."""

    def __init__(self, conn, other, position_id):
        self.conn, self.other, self.position_id = conn, other, position_id
        self.done = False
        self.other_result = None

    def execute(self, sql, *args):
        cur = self.conn.execute(sql, *args)
        if not self.done and sql.startswith("SELECT * FROM paper_positions WHERE id"):
            self.done = True
            row = cur.fetchone()
            self.other_result = paper.close_position(self.other, self.position_id, 90.0, "hard_sl")

            class One:
                def fetchone(self_inner):
                    return row
            return One()
        return cur

    def __getattr__(self, name):
        return getattr(self.conn, name)


@pytest.fixture
def two_conns(lab_env):
    a, b = labdb.connect(), labdb.connect()
    yield a, b
    a.close()
    b.close()


def _open(conn):
    acct = paper.create_account(conn, "t", 10000.0)
    pos = paper.open_position(conn, account_id=acct, symbol="ETHUSDT", side="long", price=100.0,
                              sl=90.0, qty=10.0)
    return acct, pos


def _state(conn, acct, pos):
    bal, realized = conn.execute(
        "SELECT balance, realized_pnl FROM paper_accounts WHERE id=?", (acct,)).fetchone()
    journal = conn.execute(
        "SELECT COUNT(*) FROM journal_entries WHERE account_id=?", (acct,)).fetchone()[0]
    row = dict(conn.execute("SELECT * FROM paper_positions WHERE id=?", (pos["id"],)).fetchone())
    return bal, realized, journal, row


def test_interleaved_double_close_counts_the_result_once(two_conns):
    a, b = two_conns
    acct, pos = _open(a)
    racing = CloseInBetween(a, b, pos["id"])

    with pytest.raises(paper.PaperError, match="already closed"):
        paper.close_position(racing, pos["id"], 90.0, "strategy_exit:flat")

    assert racing.done and racing.other_result["status"] == "closed"
    bal, realized, journal, row = _state(b, acct, pos)
    first_pnl = racing.other_result["pnl"]
    assert journal == 1
    assert bal == pytest.approx(10000.0 + first_pnl) and realized == pytest.approx(first_pnl)
    # The first close stands untouched: reason, price and journal link are B's.
    assert (row["exit_reason"], row["pnl"], row["journal_id"]) == (
        "hard_sl", first_pnl, racing.other_result["journal_id"])
    # The loser left no open transaction behind, so other writers are not blocked.
    assert not a.in_transaction
    paper.create_account(b, "still-writable", 1.0)


def test_loser_keeps_the_callers_open_transaction(two_conns):
    """A caller that already wrote something keeps it: the loser must not roll it back."""
    a, b = two_conns
    acct, pos = _open(a)
    paper.close_position(b, pos["id"], 90.0, "hard_sl")
    a.execute("UPDATE paper_accounts SET name='renamed' WHERE id=?", (acct,))
    assert a.in_transaction

    class StaleRead:
        """A still sees the position as open (it read before B closed)."""
        def __init__(self, conn):
            self.conn = conn
        def execute(self, sql, *args):
            if sql.startswith("SELECT * FROM paper_positions WHERE id"):
                class One:
                    def fetchone(self_inner):
                        return {**pos, "status": "open"}
                return One()
            return self.conn.execute(sql, *args)
        def __getattr__(self, name):
            return getattr(self.conn, name)

    with pytest.raises(paper.PaperError, match="already closed"):
        paper.close_position(StaleRead(a), pos["id"], 90.0, "strategy_exit:flat")

    assert a.in_transaction
    a.commit()
    assert a.execute("SELECT name FROM paper_accounts WHERE id=?", (acct,)).fetchone()[0] == "renamed"
    assert _state(a, acct, pos)[2] == 1


def test_single_close_is_unchanged(two_conns):
    a, _b = two_conns
    acct, pos = _open(a)

    out = paper.close_position(a, pos["id"], 90.0, "hard_sl")

    bal, realized, journal, row = _state(a, acct, pos)
    assert out["status"] == "closed" and journal == 1 and row["journal_id"] is not None
    assert bal == pytest.approx(10000.0 + out["pnl"]) and realized == pytest.approx(out["pnl"])
    with pytest.raises(paper.PaperError, match="already closed"):
        paper.close_position(a, pos["id"], 90.0, "again")
    assert _state(a, acct, pos)[:3] == (bal, realized, 1)


def test_watch_job_accepts_that_the_stop_check_closed_first(two_conns, monkeypatch, caplog):
    """The watch's strategy exit loses the race to the worker's stop check: no error, one result."""
    a, b = two_conns
    acct, pos = _open(a)
    racing = CloseInBetween(a, b, pos["id"])

    with caplog.at_level(logging.INFO, logger="lab.watch"):
        watch_eval._close_mirror(racing, pos["id"], 90.0, "strategy_exit:flat")

    assert "already closed" in caplog.text
    assert _state(b, acct, pos)[2] == 1
