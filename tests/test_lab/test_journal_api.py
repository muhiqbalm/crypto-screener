"""GET /api/v1/lab/journal (+ /stats): newest first, limit / order, paper-only filter.

Fake users table, isolated lab.db; never touches bmtm_trading.db.
"""
import pytest

from src.lab import paper


@pytest.fixture
def api(lab_env):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from src.trading.active_user_guard import active_user_guard
    from src.trading.router import get_supabase_client
    from tests.test_lab.test_lab_api import EMAILS, FakeUsers

    def make(sub):
        app = create_app()
        app.dependency_overrides[get_supabase_client] = lambda: FakeUsers(EMAILS)
        app.dependency_overrides[active_user_guard] = lambda: {"sub": sub}
        return TestClient(app)
    return make


@pytest.fixture
def seeded(conn):
    """Three paper trades (ETH closes first, then SOL, then BTC) + one imported live-bot trade."""
    a = paper.create_account(conn, "paper", 1000, risk_pct=1)
    for sym, opened, closed in (("ETHUSDT", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
                                ("SOLUSDT", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
                                ("BTCUSDT", "2026-01-03T00:00:00Z", "2026-01-05T00:00:00Z")):
        p = paper.open_position(conn, account_id=a, symbol=sym, side="long", price=100.0, sl=90.0, when=opened)
        paper.close_position(conn, p["id"], 110.0, "manual_close", when=closed)
    conn.execute("INSERT INTO journal_entries (account_id, source, external_id, symbol, side, entry_time, exit_time, "
                 "pnl, created_at) VALUES (NULL, 'bot', 'p1', 'ETHUSDT', 'long', '2026-01-03T00:00:00Z', "
                 "'2026-01-04T00:00:00Z', -40.0, '2026-01-04T00:00:00Z')")
    conn.commit()
    return a


def test_journal_newest_first_by_default(api, seeded):
    c = api("u-admin")
    rows = c.get("/api/v1/lab/journal").json()
    assert [(r["symbol"], r["source"]) for r in rows] == [
        ("BTCUSDT", "paper_manual"), ("ETHUSDT", "bot"), ("SOLUSDT", "paper_manual"), ("ETHUSDT", "paper_manual")]
    asc = c.get("/api/v1/lab/journal", params={"order": "asc"}).json()
    assert [r["id"] for r in asc] == [r["id"] for r in reversed(rows)]


def test_journal_limit_returns_the_newest(api, seeded):
    c = api("u-admin")
    rows = c.get("/api/v1/lab/journal", params={"limit": 2}).json()
    assert [r["exit_time"][:10] for r in rows] == ["2026-01-05", "2026-01-04"]
    oldest = c.get("/api/v1/lab/journal", params={"limit": 1, "order": "asc"}).json()
    assert [r["exit_time"][:10] for r in oldest] == ["2026-01-02"]


@pytest.mark.parametrize("params", [{"order": "newest"}, {"limit": 0}, {"limit": 5001}])
def test_journal_bad_params_are_422(api, seeded, params):
    assert api("u-admin").get("/api/v1/lab/journal", params=params).status_code == 422


def test_journal_and_stats_exclude_live_bot_trades(api, seeded):
    c = api("u-admin")
    rows = c.get("/api/v1/lab/journal", params={"exclude_source": "bot"}).json()
    assert len(rows) == 3 and {r["source"] for r in rows} == {"paper_manual"}
    everything = c.get("/api/v1/lab/journal/stats").json()
    paper_only = c.get("/api/v1/lab/journal/stats", params={"exclude_source": "bot"}).json()
    assert everything["trades"] == 4 and paper_only["trades"] == 3
    assert {g["key"] for g in paper_only["by_source"]} == {"paper_manual"}
    assert paper_only["net_pnl"] == pytest.approx(everything["net_pnl"] + 40.0)


def test_journal_stats_follow_the_list_filters(api, seeded):
    c = api("u-admin")
    s = c.get("/api/v1/lab/journal/stats", params={"symbol": "ethusdt", "exclude_source": "bot"}).json()
    assert s["trades"] == 1 and s["by_symbol"][0]["key"] == "ETHUSDT"
    s = c.get("/api/v1/lab/journal/stats", params={"from": "2026-01-03", "to": "2026-01-04"}).json()
    assert s["trades"] == 2                       # SOL (closed 01-03) + the bot trade (closed 01-04)
    s = c.get("/api/v1/lab/journal/stats", params={"account_id": seeded, "source": "paper_manual"}).json()
    assert s["trades"] == 3 and s["max_dd_pct"] is not None


def test_journal_stays_admin_only(api, seeded):
    c = api("u-plain")
    assert c.get("/api/v1/lab/journal", params={"order": "asc"}).status_code == 403
    assert c.get("/api/v1/lab/journal/stats", params={"exclude_source": "bot"}).status_code == 403
