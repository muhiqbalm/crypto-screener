"""Isolated lab.db per test (never touches bmtm_trading.db)."""
import pytest

from src.lab import settings as lab_settings


@pytest.fixture
def lab_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_DB_PATH", str(tmp_path / "lab.db"))
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LAB_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("LAB_ADMIN_EMAILS", "boss@bmtm.io,admin-uuid-1")
    monkeypatch.setenv("TRADING_JWT_SECRET", "t" * 64)
    lab_settings.get_lab_settings.cache_clear()
    yield tmp_path
    lab_settings.get_lab_settings.cache_clear()


@pytest.fixture
def conn(lab_env):
    from src.lab import db
    c = db.connect()
    yield c
    c.close()
