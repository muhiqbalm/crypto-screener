from src.lab import market, paper, watch_eval
from src.lab.db import utcnow


def _watch(conn, acct):
    wid = conn.execute(
        "INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, autopaper_account_id, "
        "autopaper_enabled, created_at) VALUES ('rosyade_family','ETHUSDT','4h','{}','{}',?,1,?)",
        (acct, utcnow())).lastrowid
    conn.commit()
    return dict(conn.execute("SELECT * FROM watches WHERE id=?", (wid,)).fetchone())


def _open_auto(conn, wid):
    return conn.execute("SELECT * FROM paper_positions WHERE watch_id=? AND status='open'", (wid,)).fetchall()


def test_autopaper_mirrors_open_trail_and_close(conn, monkeypatch):
    monkeypatch.setattr(market, "last_price", lambda s, ttl=5.0: 2000.0)
    acct = paper.create_account(conn, "auto")
    w = _watch(conn, acct)
    pos = {"side": "short", "entry_price": 2000.0, "entry_time": "2026-11-08T20:00:00Z", "sl": 2060.0,
           "tp": 1750.0}
    sig = {"time": "2026-11-08T20:00:00Z", "action": "open", "side": "short", "price": 2000.0}
    # stale (historical) signal -> no position
    watch_eval._autopaper(conn, w, None, {"last_bar": "2026-11-09T00:00:00Z", "position": pos, "last_signal": sig})
    assert _open_auto(conn, w["id"]) == []
    # fresh signal on the just-closed bar -> open with the strategy SL/TP
    watch_eval._autopaper(conn, w, None, {"last_bar": "2026-11-08T20:00:00Z", "position": pos, "last_signal": sig})
    rows = _open_auto(conn, w["id"])
    assert len(rows) == 1 and rows[0]["side"] == "short" and rows[0]["sl"] == 2060.0 and rows[0]["source"] == "paper_auto"
    # trailing stop moves -> mirror follows, no duplicate
    pos2 = {**pos, "sl": 2030.0}
    watch_eval._autopaper(conn, w, sig, {"last_bar": "2026-11-09T00:00:00Z", "position": pos2, "last_signal": sig})
    rows = _open_auto(conn, w["id"])
    assert len(rows) == 1 and rows[0]["sl"] == 2030.0
    # strategy goes flat -> mirror closed and journaled as paper_auto
    close = {"time": "2026-11-09T04:00:00Z", "action": "close", "side": "short", "price": 1990.0, "reason": "ema_exit"}
    watch_eval._autopaper(conn, w, sig, {"last_bar": "2026-11-09T04:00:00Z", "position": None, "last_signal": close})
    assert _open_auto(conn, w["id"]) == []
    j = conn.execute("SELECT * FROM journal_entries WHERE watch_id=?", (w["id"],)).fetchall()
    assert len(j) == 1 and j[0]["source"] == "paper_auto" and j[0]["exit_reason"] == "strategy_exit:ema_exit"


def test_signal_derivation():
    trades = [{"exit_time": "2026-01-02T00:00:00Z", "side": "long", "exit_price": 10.0, "exit_reason": "hard_sl"}]
    assert watch_eval._signal(None, trades)["action"] == "close"
    pos = {"side": "short", "entry_price": 9.0, "entry_time": "2026-01-03T00:00:00Z"}
    assert watch_eval._signal(pos, trades) == {"time": "2026-01-03T00:00:00Z", "action": "open", "side": "short",
                                               "price": 9.0}
    assert watch_eval._signal(None, []) is None
