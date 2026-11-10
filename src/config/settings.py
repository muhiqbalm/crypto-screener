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
        extra="ignore",
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cache_ttl: int = 60
    log_level: str = "INFO"
    symbols: str = "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,LINK/USDT:USDT,SUI/USDT:USDT,NEAR/USDT:USDT,APT/USDT:USDT,1000PEPE/USDT:USDT,1000SHIB/USDT:USDT,WIF/USDT:USDT,FET/USDT:USDT,RENDER/USDT:USDT,ARB/USDT:USDT,OP/USDT:USDT,TIA/USDT:USDT,INJ/USDT:USDT,DOT/USDT:USDT,LTC/USDT:USDT,UNI/USDT:USDT,AAVE/USDT:USDT,GALA/USDT:USDT,SEI/USDT:USDT,HYPE/USDT:USDT,ZEC/USDT:USDT"
    mock_mode: bool = False
    cors_origins: str = "*"
    shutdown_timeout: int = 30

    # Global API Key authentication
    # When enabled, all endpoints (except /health) require X-API-Key header
    require_api_key: bool = False
    api_key: str = ""

    # Separate key for the /api/v1/debug/* endpoints.  ``api_key`` is shipped
    # to browsers (NEXT_PUBLIC_API_KEY), so it must not unlock the debug API.
    # When require_api_key is on and this is empty, the debug API is closed.
    debug_api_key: str = ""

    # Rate limiting configuration for debug endpoints (on by default: every
    # debug call spends Binance request weight on the same IP that trades live)
    debug_rate_limit_enabled: bool = True
    debug_rate_limit_requests: int = 10  # Number of requests allowed
    debug_rate_limit_window: int = 60  # Time window in seconds

    # Brute-force protection for POST /trading/auth/{login,refresh,register}
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_requests: int = 10
    auth_rate_limit_window: int = 300

    @property
    def symbols_list(self) -> list[str]:
        """Get symbols as a parsed list."""
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        """Get CORS origins as a parsed list."""
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]

    @property
    def cors_allow_credentials(self) -> bool:
        """Credentials are never combined with a wildcard origin."""
        return "*" not in self.cors_origins_list


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
