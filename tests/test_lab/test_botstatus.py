"""Status bot summary (/api/v1/lab/bot/status): read-only, no secrets, no user ids.

bmtm_trading.db is a throw-away file in tmp_path; the real database is never opened.
"""
import hashlib
import json
import pathlib
import sqlite3

import pytest

from src.lab import botstatus
from src.lab.ledger.store import iso, to_epoch

NOW = to_epoch("2026-11-12T05:00:00Z")
DAY = 86_400

SECRETS = ("pass-ROSYADE-secret", "pass-OLD-secret", "pass-FAFA-secret", "ENC-API-KEY", "ENC-SECRET",
           "ENC-OKX-PASS", "ORDER-123456", "user-rosyade-02", "user-fafa-04", "user-andra-01",
           "rosyade@bmtm.io", "hash-xyz", "error with key=abc")


def _ts(days_ago: float) -> str:
    return iso(NOW - days_ago * DAY).replace("Z", "+00:00")


def _trading_db(path, *, with_logs=True):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, name TEXT, password_hash TEXT, "
              "telegram_chat_id TEXT, is_active INTEGER, created_at TEXT)")
    c.executemany("INSERT INTO users VALUES (?, ?, ?, 'hash-xyz', NULL, ?, ?)", [
        ("user-rosyade-02", "rosyade@bmtm.io", "Rosyade", 1, _ts(60)),
        ("user-fafa-04", "fafa@bmtm.io", None, 1, _ts(3)),
        ("user-andra-01", "andra@bmtm.io", "Andra", 1, _ts(60)),
    ])
    c.execute("CREATE TABLE webhook_configs (id TEXT, user_id TEXT, passphrase TEXT, is_active INTEGER, created_at TEXT)")
    c.executemany("INSERT INTO webhook_configs VALUES (?, ?, ?, ?, ?)", [
        ("w1", "user-rosyade-02", "pass-OLD-secret", 0, _ts(40)),
        ("w2", "user-rosyade-02", "pass-ROSYADE-secret", 1, _ts(30)),
        ("w3", "user-fafa-04", "pass-FAFA-secret", 0, _ts(2)),
    ])
    c.execute("CREATE TABLE exchange_credentials (id TEXT, user_id TEXT, exchange TEXT, api_key_encrypted TEXT, "
              "secret_encrypted TEXT, passphrase_encrypted TEXT, created_at TEXT)")
    c.execute("INSERT INTO exchange_credentials VALUES ('c1', 'user-rosyade-02', 'binance', 'ENC-API-KEY', "
              "'ENC-SECRET', 'ENC-OKX-PASS', ?)", (_ts(50),))
    if with_logs:
        c.execute("CREATE TABLE trade_logs (id TEXT, user_id TEXT, symbol TEXT, action TEXT, side TEXT, exchange TEXT, "
                  "size_value REAL, status TEXT, order_id TEXT, fill_price REAL, filled_quantity REAL, "
                  "created_at TEXT, error_details TEXT)")
        c.executemany("INSERT INTO trade_logs VALUES (?, ?, ?, ?, ?, 'binance', 50, ?, 'ORDER-123456', 2000, 1, ?, ?)", [
            ("t1", "user-rosyade-02", "ETH/USDT:USDT", "open", "short", "success", _ts(20), None),
            ("t2", "user-rosyade-02", "ETH/USDT:USDT", "close", "short", "success", _ts(5), None),
            ("t3", "user-rosyade-02", "ETH/USDT:USDT", "open", "long", "rejected", _ts(1), "error with key=abc"),
            ("t4", "user-rosyade-02", "ETH/USDT:USDT", "open", "long", "failed", _ts(0.5), "error with key=abc"),
            ("t5", "user-andra-01", "BTC/USDT:USDT", "open", "long", "success", _ts(0.1), None),  # no webhook config
        ])
    c.commit()
    c.close()


def _digest(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def test_missing_database_is_reported_not_invented(tmp_path):
    out = botstatus.build(str(tmp_path / "missing.db"), now=NOW)
    assert out["available"] is False and out["accounts"] == [] and out["last_alert"] is None
    assert out["active_accounts"] == 0 and out["reason"]
    assert botstatus.build("", now=NOW)["available"] is False


def test_accounts_active_first_with_counts_and_last_alert(tmp_path):
    p = tmp_path / "t.db"
    _trading_db(p)
    out = botstatus.build(str(p), now=NOW)
    assert out["available"] is True and out["window_days"] == 7 and out["active_accounts"] == 1
    assert [a["label"] for a in out["accounts"]] == ["Rosyade", "fa•••@bmtm.io"]
    ros, fafa = out["accounts"]
    assert ros["webhook_active"] is True and ros["account_active"] is True
    assert ros["webhook_since"] == iso(NOW - 30 * DAY)          # newest ACTIVE config, not the old one
    assert ros["exchanges"] == ["binance"]
    assert ros["last_alert"] == {"at": iso(NOW - 0.5 * DAY), "symbol": "ETHUSDT", "action": "open",
                                 "side": "long", "status": "failed"}
    assert (ros["alerts_window"], ros["failed_window"], ros["rejected_window"]) == (3, 1, 1)
    assert fafa["webhook_active"] is False and fafa["webhook_since"] is None and fafa["exchanges"] == []
    assert fafa["last_alert"] is None and fafa["alerts_window"] == 0
    # Andra has trade logs but no webhook config: not a bot account, not listed.
    assert out["last_alert"]["label"] == "Rosyade" and out["last_alert"]["status"] == "failed"


def test_never_returns_secrets_user_ids_or_error_text(tmp_path):
    p = tmp_path / "t.db"
    _trading_db(p)
    dumped = json.dumps(botstatus.build(str(p), now=NOW))
    for s in SECRETS:
        assert s not in dumped, s


def test_read_only_connection_and_file_untouched(tmp_path):
    p = tmp_path / "t.db"
    _trading_db(p)
    before = _digest(p)
    botstatus.build(str(p), now=NOW)
    assert _digest(p) == before
    src = botstatus._connect(str(p))
    try:
        with pytest.raises(sqlite3.OperationalError):
            src.execute("INSERT INTO users (id, created_at) VALUES ('x', 'y')")
    finally:
        src.close()


def test_missing_tables_degrade_gracefully(tmp_path):
    p = tmp_path / "t.db"
    _trading_db(p, with_logs=False)
    out = botstatus.build(str(p), now=NOW)
    assert out["available"] is True and out["reason"] == "tabel trade_logs tidak ada"
    assert out["accounts"][0]["last_alert"] is None and out["last_alert"] is None
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    out = botstatus.build(str(empty), now=NOW)
    assert out["available"] is False and out["accounts"] == []


def test_inactive_user_account_is_not_counted_as_live(tmp_path):
    p = tmp_path / "t.db"
    _trading_db(p)
    c = sqlite3.connect(p)
    c.execute("UPDATE users SET is_active=0 WHERE id='user-rosyade-02'")
    c.commit()
    c.close()
    out = botstatus.build(str(p), now=NOW)
    assert out["active_accounts"] == 0
    assert out["accounts"][0]["webhook_active"] is True and out["accounts"][0]["account_active"] is False


def test_mask_email():
    assert botstatus.mask_email("rosyade@bmtm.io") == "ro•••@bmtm.io"
    assert botstatus.mask_email(None) is None and botstatus.mask_email("nope") is None


def test_never_imports_trading_or_sends_anything():
    root = pathlib.Path(__file__).resolve().parents[2] / "src"
    for f in (root / "lab" / "botstatus.py", root / "api" / "bot_routes.py"):
        text = f.read_text()
        imports = [ln for ln in text.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any("trading" in ln for ln in imports), f
        for bad in ("/fapi/v1/order", "X-MBX-APIKEY", "telegram", "urlopen", "requests.", "httpx", "ccxt",
                    "passphrase,", "api_key", "secret_encrypted", "INSERT", "UPDATE ", "DELETE"):
            assert bad.lower() not in text.lower(), (f, bad)


@pytest.fixture
def api(lab_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from src.lab import settings as lab_settings
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers

    db = tmp_path / "bot.db"
    _trading_db(db)
    monkeypatch.setenv("LAB_TRADING_DB_PATH", str(db))
    lab_settings.get_lab_settings.cache_clear()

    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    return make


def test_api_admin_only_and_shape(api):
    assert api("u-plain").get("/api/v1/lab/bot/status").status_code == 403
    r = api("u-admin").get("/api/v1/lab/bot/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["active_accounts"] == 1
    assert {"label", "webhook_active", "account_active", "webhook_since", "exchanges", "last_alert",
            "alerts_window", "failed_window", "rejected_window"} <= set(body["accounts"][0])
    for s in SECRETS:
        assert s not in r.text, s
