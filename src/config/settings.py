"""Centralized configuration via Pydantic BaseSettings.

Reads configuration from environment variables with SCREENER_ prefix,
falling back to .env file and default values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file.

    All environment variables use the SCREENER_ prefix.
    Example: SCREENER_API_HOST=0.0.0.0
    """

    model_config = SettingsConfigDict(
        env_prefix="SCREENER_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cache_ttl: int = 60
    log_level: str = "INFO"
    symbols: str = "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,AAVE/USDT:USDT,LINK/USDT:USDT,AVAX/USDT:USDT,DOGE/USDT:USDT"
    mock_mode: bool = False
    cors_origins: str = "*"
    shutdown_timeout: int = 30
    
    # Rate limiting configuration for debug endpoints
    debug_rate_limit_enabled: bool = False
    debug_rate_limit_requests: int = 10  # Number of requests allowed
    debug_rate_limit_window: int = 60  # Time window in seconds
    debug_api_auth_enabled: bool = False
    debug_api_auth_token: str = ""

    @property
    def symbols_list(self) -> list[str]:
        """Get symbols as a parsed list."""
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        """Get CORS origins as a parsed list."""
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
