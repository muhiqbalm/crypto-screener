"""Unit tests for the Settings configuration module."""

import os

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove all SCREENER_ env vars before each test."""
    for key in list(os.environ.keys()):
        if key.startswith("SCREENER_"):
            monkeypatch.delenv(key, raising=False)


class TestSettingsDefaults:
    """Test that all default values are correctly set."""

    def test_api_host_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.api_host == "0.0.0.0"

    def test_api_port_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.api_port == 8000

    def test_cache_ttl_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.cache_ttl == 60

    def test_log_level_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.log_level == "INFO"

    def test_symbols_default(self):
        from src.config.settings import Settings

        s = Settings()
        expected = [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
            "AAVE/USDT:USDT",
            "LINK/USDT:USDT",
            "AVAX/USDT:USDT",
            "DOGE/USDT:USDT",
        ]
        assert s.symbols_list == expected

    def test_mock_mode_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.mock_mode is False

    def test_cors_origins_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.cors_origins_list == ["*"]

    def test_shutdown_timeout_default(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.shutdown_timeout == 30


class TestSettingsEnvOverride:
    """Test that environment variables override defaults."""

    def test_env_overrides_api_host(self, monkeypatch):
        monkeypatch.setenv("SCREENER_API_HOST", "127.0.0.1")
        from src.config.settings import Settings

        s = Settings()
        assert s.api_host == "127.0.0.1"

    def test_env_overrides_api_port(self, monkeypatch):
        monkeypatch.setenv("SCREENER_API_PORT", "9000")
        from src.config.settings import Settings

        s = Settings()
        assert s.api_port == 9000

    def test_env_overrides_cache_ttl(self, monkeypatch):
        monkeypatch.setenv("SCREENER_CACHE_TTL", "120")
        from src.config.settings import Settings

        s = Settings()
        assert s.cache_ttl == 120

    def test_env_overrides_log_level(self, monkeypatch):
        monkeypatch.setenv("SCREENER_LOG_LEVEL", "DEBUG")
        from src.config.settings import Settings

        s = Settings()
        assert s.log_level == "DEBUG"

    def test_env_overrides_symbols(self, monkeypatch):
        monkeypatch.setenv("SCREENER_SYMBOLS", "BTC/USDT:USDT,ETH/USDT:USDT")
        from src.config.settings import Settings

        s = Settings()
        assert s.symbols_list == ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    def test_env_overrides_mock_mode(self, monkeypatch):
        monkeypatch.setenv("SCREENER_MOCK_MODE", "true")
        from src.config.settings import Settings

        s = Settings()
        assert s.mock_mode is True

    def test_env_overrides_cors_origins(self, monkeypatch):
        monkeypatch.setenv(
            "SCREENER_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        )
        from src.config.settings import Settings

        s = Settings()
        assert s.cors_origins_list == [
            "http://localhost:3000",
            "http://localhost:5173",
        ]

    def test_env_overrides_shutdown_timeout(self, monkeypatch):
        monkeypatch.setenv("SCREENER_SHUTDOWN_TIMEOUT", "60")
        from src.config.settings import Settings

        s = Settings()
        assert s.shutdown_timeout == 60


class TestSettingsEnvPrefix:
    """Test that the SCREENER_ prefix is required."""

    def test_env_prefix_is_screener(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.model_config.get("env_prefix") == "SCREENER_"

    def test_env_file_is_dotenv(self):
        from src.config.settings import Settings

        s = Settings()
        assert s.model_config.get("env_file") == ".env"


class TestGetSettings:
    """Test the get_settings factory function."""

    def test_get_settings_returns_settings_instance(self):
        from src.config.settings import Settings, get_settings

        s = get_settings()
        assert isinstance(s, Settings)
