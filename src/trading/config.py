"""Trading module configuration via Pydantic BaseSettings.

Reads configuration from environment variables with TRADING_ prefix,
falling back to .env file and default values.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingSettings(BaseSettings):
    """Trading module settings loaded from environment variables or .env file.

    All environment variables use the TRADING_ prefix.
    Example: TRADING_SUPABASE_URL=https://your-project.supabase.co
    """

    model_config = SettingsConfigDict(
        env_prefix="TRADING_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Supabase connection
    supabase_url: str = ""
    supabase_key: str = ""

    # Encryption key for storing exchange credentials (Fernet key)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # Telegram bot token for trade notifications (optional)
    telegram_bot_token: str = ""

    # Use testnet/sandbox mode for all exchange connections
    testnet_enabled: bool = True

    # Enable CCXT raw HTTP request/response logging (verbose=True on each
    # exchange instance). Useful for debugging exchange responses; very noisy
    # — leave off in production.
    ccxt_verbose: bool = False

    # Maximum webhook payload size in bytes (default: 1 MB)
    max_payload_size: int = 1_048_576

    # Timeout in seconds for acquiring database advisory lock
    lock_timeout_seconds: int = 5

    # Timeout in seconds for exchange order submission
    order_timeout_seconds: int = 5

    # JWT authentication settings
    # TRADING_JWT_SECRET must be set to a non-empty value; the application will
    # refuse to start if this variable is absent or empty (Req 19.1).
    jwt_secret: str = ""

    # Duration (in minutes) before an access token expires (default: 30)
    # Read from TRADING_ACCESS_TOKEN_EXPIRE_MINUTES (Req 19.2)
    access_token_expire_minutes: int = 30

    # Duration (in days) before a refresh token expires (default: 7)
    # Read from TRADING_REFRESH_TOKEN_EXPIRE_DAYS (Req 19.2)
    refresh_token_expire_days: int = 7

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_not_be_empty(cls, value: str) -> str:
        """Raise ValueError if jwt_secret is absent or empty at startup."""
        if not value or not value.strip():
            raise ValueError(
                "TRADING_JWT_SECRET must be set to a non-empty value. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return value


def get_trading_settings() -> TradingSettings:
    """Create and return a TradingSettings instance."""
    return TradingSettings()
