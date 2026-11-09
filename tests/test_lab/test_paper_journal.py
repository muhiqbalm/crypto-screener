import sqlite3

import pytest

from src.lab import journal as jr
from src.lab import paper
from src.lab import scheduler as sch
from src.lab.settings import get_lab_settings


def test_risk_sizing_and_fees(conn):
    a = paper.create_account(conn, "t", 10000, risk_pct=0.5, leverage_max=5)
    p = paper.open_position(conn, account_id=a, symbol="ETHUSDT", side="long", price=100.0, sl=95.0, tp=120.0)
    fill = 100.0 * 1.0005
    assert p["entry_price"] == pytest.approx(fill)
    assert p["qty"] == pytest.approx(50.0 / (fill - 95.0))
    assert p["risk_amount"] == pytest.approx(50.0)
    assert p["fees"] == pytest.approx(p["qty"] * fill * 0.0005)


def test_leverage_cap(conn):
    a = paper.create_account(conn, "t", 1000, risk_pct=10, leverage_max=2)
    p = paper.open_position(conn, account_id=a, symbol="ETHUSDT", side="short", price=100.0, sl=100.5)
    assert p["qty"] * p["entry_price"] == pytest.approx(2000.0)


@pytest.mark.parametrize("side,sl,tp", [("long", 101, None), ("short", 99, None), ("long", 95, 99)])
def test_wrong_side_levels_rejected(conn, side, sl, tp):
    a = paper.create_account(conn, "t")
    with pytest.raises(paper.PaperError):
        paper.open_position(conn, account_id=a, symbol="ETHUSDT", side=side, price=100.0, sl=sl, tp=tp)


def test_intrabar_rule_matches_engine():
    # long, both hit, open closer to low -> SL first
    assert paper.candle_exit("long", 95, 110, 96, 111, 94) == (95, "hard_sl")
    # long, both hit, open closer to high -> TP first
    assert paper.candle_exit("long", 95, 110, 109, 111, 94) == (110, "hard_tp")
    # short, both hit, open closer to high -> SL first
    assert paper.candle_exit("short", 105, 90, 104, 106, 89) == (105, "hard_sl")
    # gap through the stop fills at the open
    assert paper.candle_exit("long", 95, None, 93, 94, 90) == (93, "hard_sl")
    assert paper.candle_exit("short", 105, None, 107, 108, 106) == (107, "hard_sl")
    assert paper.candle_exit("long", 95, 110, 100, 105, 96) is None


def test_stop_out_writes_journal_with_r(conn):
    a = paper.create_account(conn, "t", 10000, risk_pct=1)
    p = paper.open_position(conn, account_id=a, symbol="ETHUSDT", side="long", price=100.0, sl=95.0,
                            when="2026-01-01T00:00:30Z")
    candles = [
        {"t": "2026-01-01T00:00:00Z", "o": 100, "h": 100, "l": 50, "c": 99},   # before entry: ignored
        {"t": "2026-01-01T00:01:00Z", "o": 99, "h": 99.5, "l": 98, "c": 98.5},
        {"t": "2026-01-01T00:02:00Z", "o": 98, "h": 98, "l": 94, "c": 94.5},
    ]
    closed = paper.check_candles(conn, p["id"], candles)
    assert closed is not None and closed["exit_reason"] == "hard_sl"
    j = jr.query(conn, account_id=a)
    assert len(j) == 1 and j[0]["source"] == "paper_manual"
    assert j[0]["r_multiple"] == pytest.approx(-1.0, abs=0.05)
    acc = paper.get_account(conn, a)
    assert acc["balance"] == pytest.approx(10000 + j[0]["pnl"])
    assert paper.check_candles(conn, p["id"], candles) is None


def test_funding_charged_once_per_settlement(conn):
    a = paper.create_account(conn, "t")
    p = paper.open_position(conn, account_id=a, symbol="ETHUSDT", side="short", price=100.0, sl=110.0,
                            when="2026-01-01T07:00:00Z")
    ev = [{"t": "2026-01-01T00:00:00Z", "rate": 0.01, "mark": 100},   # before entry
          {"t": "2026-01-01T08:00:00Z", "rate": 0.001, "mark": 100}]
    charged = paper.apply_funding(conn, p["id"], ev)
    assert charged == pytest.approx(-p["qty"] * 100 * 0.001)  # short receives positive funding
    assert paper.apply_funding(conn, p["id"], ev) == 0.0


def test_manual_close_and_stats(conn):
    a = paper.create_account(conn, "t", 1000, risk_pct=1)
    p1 = paper.open_position(conn, account_id=a, symbol="ETHUSDT", side="long", price=100.0, sl=90.0)
    paper.close_position(conn, p1["id"], 120.0, "manual_close")
    p2 = paper.open_position(conn, account_id=a, symbol="BTCUSDT", side="short", price=100.0, sl=110.0)
    paper.close_position(conn, p2["id"], 105.0, "manual_close")
    with pytest.raises(paper.PaperError):
        paper.close_position(conn, p2["id"], 105.0, "again")
    s = jr.stats(jr.query(conn, account_id=a), 1000)
    assert s["trades"] == 2 and s["winrate"] == 0.5
    assert {g["key"] for g in s["by_symbol"]} == {"ETHUSDT", "BTCUSDT"}
    assert set(s["by_symbol"][0]) == {"key", "trades", "winrate", "pnl", "avg_r"}
    assert s["by_source"][0]["key"] == "paper_manual"
    assert s["equity_curve"][-1]["equity"] == pytest.approx(1000 + s["net_pnl"])
    assert s["max_dd_pct"] < 0


def test_last_closed_bar_open():
    # 2026-01-01T08:00:20Z with 30s delay -> 4h bar that closed at 04:00 opened at 00:00
    t = 1767254420
    assert sch.last_closed_bar_open("4h", t, 30) == "2026-01-01T00:00:00Z"
    assert sch.last_closed_bar_open("4h", t + 15, 30) == "2026-01-01T04:00:00Z"
    assert sch.last_closed_bar_open("1h", t + 15, 30) == "2026-01-01T07:00:00Z"


def test_schedule_watches_once_per_bar(conn):
    conn.execute("INSERT INTO watches (template_id, symbol, timeframe, params_json, costs_json, created_at) "
                 "VALUES ('rosyade_family','ETHUSDT','4h','{}','{}','2026-01-01T00:00:00Z')")
    conn.commit()
    s = get_lab_settings()
    assert len(sch.schedule_watches(conn, s, 1767254450)) == 1
    assert sch.schedule_watches(conn, s, 1767254460) == []        # same bar
    conn.execute("UPDATE lab_jobs SET status='done'")
    assert len(sch.schedule_watches(conn, s, 1767254450 + 14400)) == 1  # next bar


def test_bot_import_read_only_and_idempotent(conn, lab_env, monkeypatch):
    src_path = lab_env / "bmtm_trading.db"
    src = sqlite3.connect(src_path)
    src.execute("CREATE TABLE positions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, symbol TEXT NOT NULL, "
                "side TEXT NOT NULL, size REAL, entry_price REAL, status TEXT NOT NULL, exchange TEXT, "
                "created_at TEXT NOT NULL, closed_at TEXT, quantity REAL, exit_price REAL)")
    src.execute("INSERT INTO positions VALUES ('p1','user-1234567890','ETH/USDT:USDT','long',NULL,2000,'closed',"
                "'binance','2026-01-01T00:00:00Z','2026-01-02T00:00:00Z',0.5,2100)")
    src.execute("INSERT INTO positions VALUES ('p2','u2','ETHUSDT','short',1,2000,'open','binance',"
                "'2026-01-03T00:00:00Z',NULL,1,NULL)")
    src.commit()
    src.close()
    before = src_path.read_bytes()
    monkeypatch.setenv("LAB_TRADING_DB_PATH", str(src_path))
    from src.lab import settings
    settings.get_lab_settings.cache_clear()
    s = settings.get_lab_settings()
    assert sch.import_bot_trades(conn, s) == 1
    assert sch.import_bot_trades(conn, s) == 0
    e = jr.query(conn, source="bot")
    assert len(e) == 1
    assert e[0]["symbol"] == "ETHUSDT" and e[0]["pnl"] == pytest.approx(50.0) and e[0]["r_multiple"] is None
    assert src_path.read_bytes() == before
